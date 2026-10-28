"""Integrate this project's source-bound API repair through an isolated DB copy.

No API requests, semantic decisions, game deployment or release operations.
"""
import argparse
import copy
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import time
import uuid

import repair
from resume_current_api import run_lock


def backup_db(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)


def history_signature(db):
    return repair.w.fingerprint({table: [tuple(r) for r in db.execute(
        'SELECT * FROM ' + table + ' ORDER BY rowid')] for table in
        ('api_calls', 'quality_attempts', 'quality_authors', 'tasks')})


def verify_history_preserved(source, staged):
    with closing(sqlite3.connect(source)) as old, closing(sqlite3.connect(staged)) as new:
        for table in ('api_calls', 'quality_attempts', 'quality_authors', 'tasks'):
            maximum = old.execute('SELECT coalesce(max(rowid),0) FROM ' + table).fetchone()[0]
            before = old.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()
            after = new.execute('SELECT * FROM ' + table + ' WHERE rowid<=? ORDER BY rowid', (maximum,)).fetchall()
            if before != after:
                raise ValueError('Existing history changed: ' + table)


def jobs(r, stage):
    values = []; response_hashes = {}
    for relative in repair.w.read_json(r.work / (stage + '_jobs.json')):
        folder = r.work / relative
        payload = repair.w.read_json(folder / 'payload.json')
        saved = repair.w.read_json(folder / 'accepted.json')
        if saved['input_hash'] != payload['input_hash']:
            raise ValueError('Accepted input binding mismatch: ' + folder.name)
        if repair.w.fingerprint({k: v for k, v in payload.items() if k != 'input_hash'}) != payload['input_hash']:
            raise ValueError('Payload digest mismatch')
        ids = [v['id'] for v in payload['records']]
        result = saved['result']
        if set(ids) != {v['id'] for v in result['records']} or len(ids) != len(result['records']):
            raise ValueError('Accepted coverage mismatch')
        instances = saved.get('record_instances', {})
        for item in result['records']:
            instance = instances.get(item['id'], saved.get('instance'))
            if not instance or not instance.startswith('api:'):
                raise ValueError('Missing actual API identity')
            raw_hash = saved['record_response_sha256'][item['id']]
            raw = folder / instance.removeprefix('api:') / 'response.raw.txt'
            if instance not in response_hashes:
                if not raw.exists():
                    matches = list(r.work.glob('**/' + instance.removeprefix('api:') + '/response.raw.txt'))
                    if not matches: raise ValueError('Missing original response: ' + instance)
                    raw = matches[0]
                response_hashes[instance] = repair.sha(raw)
            if response_hashes[instance] != raw_hash:
                raise ValueError('Actual API response digest mismatch')
            if stage == 'review' and (item.get('reviewed') is not True or item.get('issues')):
                raise ValueError('Unresolved or missing independent review')
        values.append((folder, payload, saved))
    return values


def preflight(r):
    baseline = r.snapshot()
    manifest = repair.w.read_json(r.work / 'candidate_manifest.json')
    plan = repair.w.read_json(r.work / 'repair_plan.json')
    candidate = r.work / 'torment-tides-of-numenera_text_translated_candidate.csv'
    if manifest['status'] != 'incremental_candidate_validated':
        raise ValueError('Not a fully validated candidate')
    for path, expected in [(candidate, manifest['candidate_sha256']),
                           (r.work / 'new_glossary.json', manifest['new_glossary_sha256'])]:
        if repair.sha(path) != expected:
            raise ValueError('Candidate or glossary changed')
    calls = repair.w.read_json(r.work / 'calls.json')
    if any(c['status'] == 'reserved' for c in calls):
        raise ValueError('Unknown in-flight repair request')
    with r.db() as db:
        if db.execute('SELECT 1 FROM tasks WHERE status="running"').fetchone() or db.execute(
                'SELECT 1 FROM api_calls WHERE status="reserved"').fetchone():
            raise ValueError('Parent has in-flight work')
        if db.execute('SELECT 1 FROM tasks WHERE revision=? AND status IN ("pending","failed")',
                      (baseline['parent_revision'],)).fetchone():
            raise ValueError('Parent has unfinished current tasks')
        history = history_signature(db)
    translations, reviews = jobs(r, 'translate'), jobs(r, 'review')
    translated = {v['id']: v for _, _, s in translations for v in s['result']['records']}
    reviewed = {v['id']: v for _, _, s in reviews for v in s['result']['records']}
    if set(translated) != set(plan['term_affected_ids']) or set(reviewed) != set(plan['scope_ids']):
        raise ValueError('Repair scope changed')
    candidate_rows = repair.read_column(candidate)
    originals = repair.w.read_json(r.work / 'records.json')
    if len(candidate_rows) != len(originals):
        raise ValueError('Candidate CSV count mismatch')
    for row, text in zip(originals, candidate_rows):
        if text != (reviewed[row['id']]['translation'] if row['id'] in reviewed else row['translation']):
            raise ValueError('Candidate does not equal actual reviewed values')
    return baseline, manifest, plan, calls, translations, reviews, history


def prepare(r):
    b, manifest, plan, calls, translations, reviews, history = preflight(r)
    run = r.work / ('integration_' + uuid.uuid4().hex)
    stage_project = run / 'project'; root = stage_project / 'TranslateFiles'
    root.mkdir(parents=True)
    (root / 'backups').mkdir()
    for name in (b['source_file'], b['translation_file']):
        shutil.copy2(r.project / name, stage_project / name)
    (root / 'config').mkdir()
    shutil.copy2(r.project / 'TranslateFiles/config/workflow.json', root / 'config/workflow.json')
    flow = repair.w.Workflow(stage_project)
    backup_db(r.project / 'TranslateFiles/state/workflow.sqlite3', flow.db_path)
    with flow.db() as db:
        approvals = flow.meta(db, 'quality_approvals', {})
        pilot = approvals.get('pilot')
        if not pilot:
            raise ValueError('Missing existing accepted pilot')
        for kind, receipt in approvals.items():
            old_report = Path('reports/accepted') / (kind + '_' + receipt['report_hash'][:16]) / 'report.json'
            (root / old_report).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(r.project / 'TranslateFiles' / old_report, root / old_report)
        # Reuse only prior adjudications whose signatures still match. Avoid
        # reopening an already accepted process pilot during this production
        # repair; its actual assessment is carried explicitly below.
        flow.put(db, 'quality_approvals', {k: v for k, v in approvals.items() if k != 'pilot'})
        flow.preserve_quality_scope(db, flow.config(db), flow.config(db), plan['scope_ids'])
        revision = flow.meta(db, 'revision') + 1
        glossary_path = Path('glossary') / ('incremental_revision_' + str(revision)) / 'glossary_reviewed.json'
        (root / glossary_path).parent.mkdir(parents=True)
        shutil.copy2(r.work / 'new_glossary.json', root / glossary_path)
        for name in ('term_decisions.json', 'term_source_supplements.json', 'term_changes.json'):
            if (r.work / name).exists():
                shutil.copy2(r.work / name, root / glossary_path.parent / name)
        original_terms = repair.w.read_json(r.work / 'old_glossary.json')
        revised_terms = repair.w.read_json(r.work / 'new_glossary.json')
        reviewed_terms_manifest = r.work / 'glossary_review_jobs.json'
        proof = {'source_sha256': b['source_sha256'], 'baseline_glossary_sha256': b['glossary_sha256'],
                 'reviewed_glossary_sha256': manifest['new_glossary_sha256'],
                 'term_decisions_sha256': repair.sha(r.work / 'term_decisions.json'),
                 'retained_non_translate_provenance': ('Unchanged previously frozen protection; not newly reviewed.'
                     if original_terms['non_translate'] == revised_terms['non_translate'] else
                     'Only explicit source-bound corrections in term_changes.json; all other previous protection retained. No new semantic-review votes invented.'),
                 'repair_directory': str(r.work),
                 'term_review_jobs': len(repair.w.read_json(reviewed_terms_manifest)) if reviewed_terms_manifest.exists() else 0}
        extra_audits = r.work / 'additional_term_audits.json'
        if extra_audits.exists():
            proof['additional_term_audits'] = []
            for relative in repair.w.read_json(extra_audits):
                audit = (r.work / relative).resolve()
                if not audit.is_relative_to(r.work.resolve()):
                    raise ValueError('Additional term audit leaves repair directory')
                decisions = repair.w.read_json(audit / 'term_decisions.json')
                snapshot = audit / 'term_audit/glossary_original.json'
                built = repair.w.read_json(audit / 'term_build/glossary_manifest.json')
                if decisions['source_sha256'] != b['source_sha256'] or decisions['snapshot_sha256'] != repair.sha(snapshot):
                    raise ValueError('Additional term evidence binding mismatch')
                if built['decisions_sha256'] != repair.sha(audit / 'term_decisions.json'):
                    raise ValueError('Additional term build binding mismatch')
                evidence = []
                for job in repair.w.read_json(audit / 'glossary_review_jobs.json'):
                    folder = audit / job
                    accepted = repair.w.read_json(folder / 'accepted.json')
                    payload = repair.w.read_json(folder / 'payload.json')
                    if accepted['input_hash'] != payload['input_hash']:
                        raise ValueError('Additional accepted term binding mismatch')
                    for ref, instance in accepted['entry_instances'].items():
                        raw = folder / instance.removeprefix('api:') / 'response.raw.txt'
                        if not instance.startswith('api:') or repair.sha(raw) != accepted['entry_response_sha256'][ref]:
                            raise ValueError('Additional term response provenance mismatch')
                    evidence.append({'job': job, 'accepted': accepted})
                destination = root / glossary_path.parent / 'additional_audits' / Path(relative).name
                for name in ('term_decisions.json', 'term_audit/glossary_original.json',
                             'term_build/glossary_manifest.json', 'term_build/glossary_reviewed.json'):
                    (destination / name).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(audit / name, destination / name)
                repair.w.write_json(destination / 'api_evidence.json', evidence)
                proof['additional_term_audits'].append({'directory': str(destination.relative_to(root)),
                    'decisions_sha256': repair.sha(audit / 'term_decisions.json'), 'original_work': str(audit)})
        repair.w.write_json(root / glossary_path.parent / 'incremental_provenance.json', proof)
        flow.put(db, 'revision', revision)
        flow.put(db, 'source_path', str(stage_project / b['source_file']))
        flow.put(db, 'glossary', {'path': str(glossary_path), 'hash': manifest['new_glossary_sha256'], 'revision': revision})
        # This is an incremental repair of a completed, accepted workflow, not a
        # new pilot assessment. Preserve the actual previous assessment honestly.
        pilot['carried_from_pilot_key'] = pilot['pilot_key']
        pilot['pilot_key'] = flow.pilot_key(db, flow.config(db))
        pilot['carry_reason'] = 'Existing accepted process/style pilot retained; affected production records independently retranslated and reviewed.'
        flow.put(db, 'quality_approvals', {'pilot': pilot})
        flow.put(db, 'paused', True)
        by_job = {}
        for c in calls: by_job.setdefault(c['job'], []).append(c)
        authors = {}
        for stage, packages in [('translate', translations), ('review', reviews)]:
            for folder, payload, saved in packages:
                task_id = folder.name
                if db.execute('SELECT 1 FROM tasks WHERE id=?', (task_id,)).fetchone():
                    raise ValueError('Imported task already exists')
                result = saved['result']; instances = saved.get('record_instances', {})
                token = 'external-incremental-import'
                first = next(iter(instances.values()), saved.get('instance'))
                attempts = sum(c['status'] != 'cancelled' and not repair.service_failure(c['status']) for c in by_job.get(task_id, []))
                db.execute('INSERT INTO tasks(id,stage,revision,ids,payload,input_hash,backend,status,attempt,lease_token,result) VALUES (?,?,?,?,?,?,?,"done",?,?,?)',
                    (task_id, stage, payload['revision'], repair.w.encoded([x['id'] for x in payload['records']]),
                     repair.w.encoded(payload), payload['input_hash'], 'api', attempts, token, repair.w.encoded(result)))
                db.execute('INSERT INTO quality_results VALUES (?,?)', (task_id, first))
                for c in by_job.get(task_id, []):
                    db.execute('INSERT INTO quality_attempts VALUES (?,?,?)', (task_id, c['id'], 'api:' + c['id']))
                for item in result['records']:
                    rid = item['id']; instance = instances.get(rid, saved.get('instance'))
                    if stage == 'translate': authors[rid] = instance
                    elif authors.get(rid) == instance:
                        raise ValueError('Reviewer is the translation author')
                    elif not flow.independent_worker(db, {'stage': 'review', 'ids': repair.w.encoded([rid])}, instance):
                        raise ValueError('Reviewer conflicts with parent translation author')
                    db.execute('INSERT INTO quality_authors VALUES (?,?,?,?)', (rid, stage, instance, task_id))
                    db.execute('INSERT INTO batch_items(task_id,token,record_id,item,instance,valid) VALUES (?,?,?,?,?,1)',
                               (task_id, token, rid, repair.w.encoded(item), instance))
                    if stage == 'review':
                        old = db.execute('SELECT locked,translation FROM records WHERE id=?', (rid,)).fetchone()
                        if old['locked'] and old['translation'] != item['translation']:
                            raise ValueError('Cannot overwrite locked translation')
                        db.execute('UPDATE records SET translation=?,stage="review",exceptions=? WHERE id=?',
                                   (item['translation'], repair.w.encoded(item.get('exceptions', [])), rid))
                flow.event(db, 'submit', {'task': task_id, 'stage': stage, 'origin': 'source-bound incremental API import',
                    'accepted_path': str(folder / 'accepted.json'), 'accepted_sha256': repair.sha(folder / 'accepted.json')})
        # Keep all original API ledger rows and append actual incremental calls.
        # The source ledger remains immutable, including service failures/unknown usage.
        for c in calls:
            db.execute('INSERT INTO api_calls(task_id,time,status,usage,session_id,task_attempt) VALUES (?,?,?,?,?,NULL)',
                       (c['job'], c['issued_at'], c['status'], repair.w.encoded(c.get('usage')), c['id']))
        flow.event(db, 'integrate_incremental', {'source': str(r.work), 'scope': len(plan['scope_ids']),
                   'revision': revision, 'history_before': history, 'requests_added': len(calls), 'api_requests_issued': 0})
    # Reuse the project's tested literal prefilter. Candidate matches still go
    # through the original matcher, protection spans and applicability rules.
    import scope_match
    config = b['config']
    with flow.db() as db:
        scope_match.prepare(flow.glossary(db), config, flow.rules(db, config))
    closure = flow.quality_report('final')
    if closure['remaining_checks'] or closure['carried_finding_records']:
        raise ValueError('Formal quality closure has unresolved disputes; staged copy retained')
    flow.finish_sol_round()  # Empty dispute scope; no invented per-item verdicts.
    exported = flow.export()
    values = repair.read_column(stage_project / b['translation_file'])
    if values != repair.read_column(r.work / 'torment-tides-of-numenera_text_translated_candidate.csv'):
        raise ValueError('Formal export values differ from candidate')
    report = {'status': 'staged_validated', 'stage_project': str(stage_project), 'revision': revision,
              'baseline': b, 'history_before': history, 'candidate_sha256': manifest['candidate_sha256'],
              'formal_export': exported, 'formal_export_values_equal_candidate': True,
              'changed_records': manifest['changed_records'], 'scope_records': manifest['scope_records'],
              'preserved_outside_scope': manifest['preserved_outside_scope'], 'calls_to_import': len(calls),
              'api_requests_issued': 0}
    repair.w.write_json(run / 'integration.json', report)
    repair.w.write_json(r.work / 'integration_staged.json', {'report': str(run / 'integration.json')})
    return report


def finish(r, stage_project):
    """Resume only local staging export after a filesystem preparation error."""
    b, manifest, plan, calls, translations, reviews, history = preflight(r)
    stage_project = Path(stage_project).resolve()
    if not stage_project.is_relative_to(r.work.resolve()) or stage_project.name != 'project':
        raise ValueError('Staging project must be inside this repair workspace')
    flow = repair.w.Workflow(stage_project)
    verify_history_preserved(r.project / 'TranslateFiles/state/workflow.sqlite3', flow.db_path)
    with flow.db() as db:
        if flow.meta(db, 'revision') != b['parent_revision'] + 1 or flow.meta(db, 'glossary')['hash'] != manifest['new_glossary_sha256']:
            raise ValueError('Unexpected staging revision or glossary')
        if [v['translation'] for v in db.execute('SELECT translation FROM records ORDER BY ordinal')] != repair.read_column(r.work / 'torment-tides-of-numenera_text_translated_candidate.csv'):
            raise ValueError('Staged values differ from candidate')
        flow.require_final_approval(db, flow.config(db))
        import scope_match
        scope_match.prepare(flow.glossary(db), flow.config(db), flow.rules(db, flow.config(db)))
    (flow.root / 'backups').mkdir(exist_ok=True)
    exported = flow.export()
    if repair.read_column(stage_project / b['translation_file']) != repair.read_column(r.work / 'torment-tides-of-numenera_text_translated_candidate.csv'):
        raise ValueError('Export differs from candidate')
    report = {'status': 'staged_validated', 'stage_project': str(stage_project), 'revision': b['parent_revision'] + 1,
              'baseline': b, 'history_before': history, 'candidate_sha256': manifest['candidate_sha256'],
              'formal_export': exported, 'formal_export_values_equal_candidate': True,
              'changed_records': manifest['changed_records'], 'scope_records': manifest['scope_records'],
              'preserved_outside_scope': manifest['preserved_outside_scope'], 'calls_to_import': len(calls), 'api_requests_issued': 0}
    repair.w.write_json(stage_project.parent / 'integration.json', report)
    repair.w.write_json(r.work / 'integration_staged.json', {'report': str(stage_project.parent / 'integration.json')})
    return report


def apply(r):
    pointer = repair.w.read_json(r.work / 'integration_staged.json')
    report = repair.w.read_json(pointer['report']); staged = Path(report['stage_project'])
    b = r.snapshot()
    if b != report['baseline']:
        raise ValueError('Baseline changed since staging')
    with r.db() as db:
        if history_signature(db) != report['history_before']:
            raise ValueError('Parent history changed since staging')
    if repair.sha(staged / b['translation_file']) != report['formal_export']['translation_sha256']:
        raise ValueError('Staged export changed')
    if repair.sha(staged / b['source_file']) != b['source_sha256']:
        raise ValueError('Staged source changed')
    staged_flow = repair.w.Workflow(staged)
    original_db = r.project / 'TranslateFiles/state/workflow.sqlite3'
    verify_history_preserved(original_db, staged_flow.db_path)
    source_calls = repair.w.read_json(r.work / 'calls.json')
    with r.db() as db:
        before_budget = repair.budget_requests(db)
    with staged_flow.db() as db:
        for c in source_calls:
            usage = {**(c.get('usage') or {}), 'api_name': c.get('api'),
                     'incremental_call_id': c['id'], 'source_ledger': str(r.work / 'calls.json')}
            changed = db.execute('UPDATE api_calls SET usage=? WHERE session_id=?', (repair.w.encoded(usage), c['id'])).rowcount
            if changed != 1:
                raise ValueError('Imported API call identity is not unique')
        added = sum(c['status'] != 'cancelled' and not repair.service_failure(c['status']) for c in source_calls)
        after_budget = repair.budget_requests(db)
        if after_budget != before_budget + added:
            raise ValueError('Cumulative request budget reconciliation failed')
        staged_flow.require_final_approval(db, staged_flow.config(db))
        staged_flow.put(db, 'source_path', str(r.project / b['source_file']))
        last = staged_flow.meta(db, 'last_export'); last['path'] = str(r.project / b['translation_file'])
        if last.get('mixed_language_audit'):
            last['mixed_language_audit']['path'] = str(r.project / 'TranslateFiles/reports/mixed_language_audit.json')
        staged_flow.put(db, 'last_export', last)
    repair.w.write_json(staged_flow.root / 'reports/final_validation.json', last)
    archive = r.project / 'TranslateFiles/backups' / ('before_incremental_integration_' + uuid.uuid4().hex)
    archive.mkdir(parents=True)
    backup_db(original_db, archive / 'workflow.sqlite3')
    shutil.copy2(r.project / b['translation_file'], archive / b['translation_file'])
    try:
        # Copy only staging-generated artifacts; keep parent audit/history files.
        for f in staged_flow.root.rglob('*'):
            if not f.is_file() or 'state' in f.relative_to(staged_flow.root).parts or 'backups' in f.relative_to(staged_flow.root).parts:
                continue
            target = r.project / 'TranslateFiles' / f.relative_to(staged_flow.root)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                saved = archive / 'overwritten' / f.relative_to(staged_flow.root)
                saved.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(target, saved)
            shutil.copy2(f, target)
        backup_db(staged_flow.db_path, original_db)
        temporary = r.project / (b['translation_file'] + '.integration.tmp')
        temporary.write_bytes((staged / b['translation_file']).read_bytes())
        temporary.replace(r.project / b['translation_file'])
        if repair.sha(r.project / b['translation_file']) != report['formal_export']['translation_sha256']:
            raise ValueError('Installed formal CSV digest mismatch')
    except BaseException:
        backup_db(archive / 'workflow.sqlite3', original_db)
        shutil.copy2(archive / b['translation_file'], r.project / b['translation_file'])
        for f in (archive / 'overwritten').rglob('*'):
            if f.is_file(): shutil.copy2(f, r.project / 'TranslateFiles' / f.relative_to(archive / 'overwritten'))
        raise
    report.update(status='integrated', backup=str(archive), integrated_at=time.time(),
                  formal_export=last,
                  formal_translation_sha256=repair.sha(r.project / b['translation_file']),
                  previous_history_preserved=True, model_request_budget_before=before_budget,
                  model_request_budget_after=after_budget, incremental_model_requests_added=added,
                  not_done=['engine repack', 'in-game verification', 'publication'])
    repair.w.write_json(r.work / 'integration_applied.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'finish', 'apply'))
    parser.add_argument('--staged-project')
    args = parser.parse_args(); r = repair.Repair()
    with run_lock(r):
        if args.command == 'finish':
            if not args.staged_project: parser.error('finish requires --staged-project')
            result = finish(r, args.staged_project)
        else:
            result = prepare(r) if args.command == 'prepare' else apply(r)
    print(json.dumps({k: v for k, v in result.items() if k != 'baseline'}, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
