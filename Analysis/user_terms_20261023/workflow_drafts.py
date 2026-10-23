"""Save production drafts first; audit once at the phase boundary and pool repairs."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import json
import sys
import uuid

import ainiee_bridge as bridge


def ordered_draft_checks(check, rows, workers):
    """Bound queued work and yield in source order; workers never receive SQLite objects."""
    if workers == 1 or len(rows) < 2:
        yield from map(check, rows)
        return
    workers = min(workers, len(rows))
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='draft-scan')
    pending = deque()
    remaining = iter(rows)
    try:
        for row in remaining:
            pending.append(pool.submit(check, row))
            if len(pending) >= workers * 2:
                break
        while pending:
            yield pending.popleft().result()
            row = next(remaining, None)
            if row is not None:
                pending.append(pool.submit(check, row))
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


class DraftMixin:
    @staticmethod
    def is_round_repair(task):
        payload = json.loads(task['payload'])
        return task['stage'] in ('pilot_translate', 'translate') and bool(payload.get('draft_scan_key'))

    @staticmethod
    def is_draft_task(task):
        payload = json.loads(task['payload'])
        return task['stage'] in ('pilot_translate', 'translate') and (not payload.get('strict_translation') or bool(payload.get('draft_scan_key')))

    @staticmethod
    def draft_key(config, key):
        return 'pilot_' + key if config.get('_draft_stage') == 'pilot_translate' else key

    def draft_meta(self, db, config, key, default=None):
        return self.meta(db, self.draft_key(config, key), default)

    def draft_put(self, db, config, key, value):
        self.put(db, self.draft_key(config, key), value)

    @staticmethod
    def best_effort_restore(text, protection):
        for item in protection:
            text = text.replace(item['placeholder'], item['original'])
        return text

    def draft_tables(self, db, stage='translate'):
        prefix = 'pilot_' if stage == 'pilot_translate' else ''
        db.execute(f'CREATE TABLE IF NOT EXISTS {prefix}draft_candidates(record_id TEXT PRIMARY KEY,raw_item TEXT,protection TEXT,translation TEXT,source_hash TEXT,instance TEXT,task_id TEXT)')
        db.execute(f'CREATE TABLE IF NOT EXISTS {prefix}draft_checks(record_id TEXT PRIMARY KEY,policy_key TEXT,signature TEXT,finding TEXT)')
        db.execute(f'CREATE TABLE IF NOT EXISTS {prefix}draft_check_rounds(id INTEGER PRIMARY KEY,report TEXT)')

    def remember_draft(self, db, task, item, original, translation, instance):
        from translation_workflow import encoded, fingerprint
        self.draft_tables(db, task['stage'])
        prefix = 'pilot_' if task['stage'] == 'pilot_translate' else ''
        config = {'_draft_stage': task['stage']}
        source = db.execute('SELECT source FROM records WHERE id=?', (item['id'],)).fetchone()['source']
        db.execute(f'INSERT OR REPLACE INTO {prefix}draft_candidates VALUES (?,?,?,?,?,?,?)',
                   (item['id'], encoded(item), encoded(original.get('protection', [])), translation,
                    fingerprint(source), instance, task['id']))
        if self.is_round_repair(task):
            pending = set(self.draft_meta(db, config, 'draft_repair_pending_check', []))
            pending.add(item['id'])
            self.draft_put(db, config, 'draft_repair_pending_check', sorted(pending))
            attempts = self.draft_meta(db, config, 'draft_repair_attempts', {})
            attempts[item['id']] = max(attempts.get(item['id'], 0),
                                        json.loads(task['payload']).get('repair_counts', {}).get(item['id'], task['attempt']))
            self.draft_put(db, config, 'draft_repair_attempts', attempts)

    def draft_audit_key(self, db, config, generation=None):
        from translation_workflow import fingerprint
        keys = ('source_language', 'target_language', 'case_sensitive', 'whole_word', 'protect_named_curly',
                'placeholder_family_overrides', 'exclusions')
        return fingerprint({'revision': self.meta(db, 'revision'), 'generation': self.draft_meta(db, config, 'draft_generation', 0) if generation is None else generation,
                            'source': self.meta(db, 'source_hash'), 'glossary': self.meta(db, 'glossary'),
                            'term_match_version': bridge.TERM_MATCH_VERSION, 'draft_validator': 3,
                            'rules': {k: config[k] for k in keys}})

    def draft_snapshot(self, db, stage='translate'):
        prefix = 'pilot_' if stage == 'pilot_translate' else ''
        self.draft_tables(db, stage)
        rows = [dict(r) for r in db.execute('SELECT * FROM records ORDER BY ordinal')]
        if stage == 'pilot_translate':
            selected = self.pilot_ids(db, rows, self.config(db))
            rows = [r for r in rows if r['id'] in selected]
        allowed = ('pilot_translate', 'pilot_review') if stage == 'pilot_translate' else ('translate', 'review', 'polish', 'final_review')
        if any(r['stage'] not in allowed or r['translation'] is None for r in rows):
            raise ValueError('Complete all production drafts before the full draft scan')
        if db.execute('SELECT 1 FROM tasks WHERE revision=? AND status="running"', (self.meta(db, 'revision'),)).fetchone():
            raise ValueError('Finish in-flight work before the full draft scan')
        originals = {r['record_id']: dict(r) for r in db.execute(f'SELECT * FROM {prefix}draft_candidates')}
        return rows, originals

    @staticmethod
    def draft_candidate(row, journal):
        from translation_workflow import fingerprint
        if (journal and journal['source_hash'] == fingerprint(row['source']) and journal['translation'] == row['translation']
                and row['stage'] in ('pilot_translate', 'translate')):
            return json.loads(journal['raw_item']), json.loads(journal['protection'])
        return {'id': row['id'], 'translation': row['translation'], 'exceptions': json.loads(row['exceptions'])}, []

    def collect_draft_issues(self, db, config, record_ids=None):
        """Validate only this explicit scope; None means a full acceptance scan."""
        from translation_workflow import encoded
        rows, originals = self.draft_snapshot(db, config.get('_draft_stage', 'translate'))
        if record_ids is not None:
            scope = set(record_ids)
            if scope - {r['id'] for r in rows}:
                raise ValueError('Unknown draft check ID')
            rows = [r for r in rows if r['id'] in scope]
        rules, glossary = self.rules(db, config), self.glossary(db)
        workers = config.get('draft_scan_workers', 1)
        if type(workers) is not int or not 1 <= workers <= 32:
            raise ValueError('draft_scan_workers must be between 1 and 32')
        fake_task = {'stage': config.get('_draft_stage', 'translate'), 'payload': encoded({'strict_translation': True})}
        failures = []
        show_progress = record_ids is None and len(rows) >= 1000
        total = len(rows)
        if show_progress:
            print(f'[draft-scan] full validation started: 0/{total} records', file=sys.stderr, flush=True)
        def check(row):
            # Only detached snapshots and read-only rules/glossary are shared.
            # All report/receipt writes remain on the calling transaction thread.
            item, protection = self.draft_candidate(row, originals.get(row['id']))
            errors = []
            terms = bridge.matched_terms(glossary, [row['source']], config, rules=bridge.record_rules(row, config, rules))
            try:
                self.validate_body_row(row, fake_task, {}, item, {'protection': protection},
                                       config, rules, glossary, terms=terms)
            except ValueError as exc:
                errors.append(str(exc))
            # Collect additional mechanical findings now, rather than spending
            # another model round discovering the next error in the same sentence.
            try:
                exceptions = bridge.normalize_exception_sources(item.get('exceptions', []), terms, config['case_sensitive'])
                known = {t['src'] for t in terms}
                exempt = {e['source'] for e in exceptions if e['source'] in known}
            except ValueError as exc:
                errors.append(str(exc)); exempt = set()
            missing = [t['src'] for t in terms if t['src'] not in exempt and t['dst'] not in row['translation']
                       and not bridge.helper().is_keep_original_translation(t['dst'])]
            structure = bridge.record_structural_issues(row, row['translation'], rules, config)
            if missing:
                errors.append('terminology mismatch: ' + ', '.join(missing))
            if structure:
                errors.append('structural mismatch: ' + ', '.join(structure))
            if errors:
                return {'id': row['id'], 'ordinal': row['ordinal'], 'source': row['source'],
                                 'translation': row['translation'], 'diagnostics': list(dict.fromkeys(errors)),
                                 'missing_terms': missing, 'structural_issues': structure}
            return None

        for index, finding in enumerate(ordered_draft_checks(check, rows, workers), start=1):
            if finding is not None:
                failures.append(finding)
            if show_progress and (index % 500 == 0 or index == total):
                print(f'[draft-scan] full validation progress: {index}/{total} records; failures={len(failures)}',
                      file=sys.stderr, flush=True)
        return rows, failures

    def ensure_draft_audit(self, db, config):
        key = self.draft_audit_key(db, config)
        receipt = self.draft_meta(db, config, 'draft_audit', {})
        if receipt.get('key') == key and receipt.get('clean'):
            return
        report = self.scan_drafts_in_transaction(db, config, prepare_repairs=False)
        if not report['clean']:
            if report.get('phase') == 'awaiting_round':
                raise ValueError('Complete all batches in the current repair round before checking or independent review')
            raise ValueError(f'Full draft scan found {report["failed_records"]} affected IDs; run draft-scan --prepare-repairs before independent review. Report: {report["report_file"]}')

    def check_drafts_before_review(self, stage='translate'):
        # Commit failed checks before prepare raises, preserving the scan baseline.
        with self.db() as db:
            config = self.config(db)
            if stage == 'pilot_translate':
                config = {**config, '_draft_stage': stage}
                rows = self.quality_rows(db)
                selected = self.pilot_ids(db, rows, config)
                rows = [r for r in rows if r['id'] in selected]
                allowed = ('pilot_translate', 'pilot_review')
            else:
                rows = self.quality_rows(db)
                allowed = ('translate', 'review', 'polish', 'final_review')
                if not self.pilot_approved(db, config):
                    return
            if any(r['translation'] is None or r['stage'] not in allowed for r in rows):
                return
            receipt = self.draft_meta(db, config, 'draft_audit', {})
            if receipt.get('key') == self.draft_audit_key(db, config) and receipt.get('clean'):
                return
            report = self.scan_drafts_in_transaction(db, config, prepare_repairs=False)
        if not report['clean']:
            if report.get('phase') == 'awaiting_round':
                raise ValueError('Complete all batches in the current repair round before checking or independent review')
            raise ValueError(f'Full draft scan found {report["failed_records"]} affected IDs; run draft-scan --stage {stage} --prepare-repairs before independent review. Report: {report["report_file"]}')

    def draft_scan(self, prepare_repairs=False, workers=None, stage='translate'):
        if stage == 'pilot_translate':
            return self.pilot_report()  # Compatibility alias; no automatic pilot repair rounds.
        if stage not in ('pilot_translate', 'translate'):
            raise ValueError('Unknown draft stage')
        if workers is not None and (type(workers) is not int or not 1 <= workers <= 32):
            raise ValueError('draft_scan_workers must be between 1 and 32')
        with self.db() as db:
            config = self.config(db)
            if stage == 'pilot_translate':
                config = {**config, '_draft_stage': stage}
            if workers is not None:
                config = {**config, 'draft_scan_workers': workers}
            return self.scan_drafts_in_transaction(db, config, prepare_repairs)

    def unfinished_draft_repairs(self, db, stage='translate'):
        return [dict(t) for t in db.execute('SELECT id,payload,status FROM tasks WHERE stage=? AND revision=? AND status IN ("pending","running","failed")',
                                            (stage, self.meta(db, 'revision')))
                if json.loads(t['payload']).get('draft_scan_key')]

    def adopt_legacy_draft_scan(self, db, config, rows, signatures, policy):
        """Reuse a bound old full scan, even if its strict repair jobs have finished."""
        from translation_workflow import read_json, write_json, encoded
        prefix = ''
        if config.get('_draft_stage') == 'pilot_translate' or db.execute(f'SELECT 1 FROM {prefix}draft_checks').fetchone():
            return None
        path = self.root / 'reports/full_draft_scan.json'
        if not path.exists():
            return None
        report = read_json(path)
        receipt = self.draft_meta(db, config, 'draft_audit', {})
        if report.get('phase') or not report.get('key') or receipt.get('key') != report['key']:
            return None
        completed = [json.loads(t['ids']) for t in db.execute(
            'SELECT ids,payload FROM tasks WHERE stage="translate" AND revision=? AND status="done"',
            (self.meta(db, 'revision'),)) if json.loads(t['payload']).get('draft_scan_key') == report['key']]
        generation = self.draft_meta(db, config, 'draft_generation', 0) - len(completed)
        if generation < 0 or report['key'] != self.draft_audit_key(db, config, generation):
            return None  # Some other input changed; the old scan cannot prove this baseline.
        ids = set(signatures)
        found = report.get('failures')
        if (report.get('records') != len(rows) or not isinstance(found, list)
                or report.get('failed_records') != len(found)
                or any(not isinstance(f, dict) or f.get('id') not in ids for f in found)
                or len({f['id'] for f in found}) != len(found)):
            return None
        findings = {f['id']: f for f in found}
        repaired = {i for group in completed for i in group}
        for record_id in ids:
            db.execute(f'INSERT INTO {prefix}draft_checks VALUES (?,?,?,?)',
                       (record_id, policy, '' if record_id in repaired else signatures[record_id],
                        encoded(findings.get(record_id))))
        archived = self.root / f'reports/draft_checks/legacy_initial_{report["key"][:12]}.json'
        write_json(archived, {**report, 'phase': 'initial_full', 'scope': 'full', 'execution': 'reused',
                              'checked_ids': [r['id'] for r in rows], 'recheck_required_ids': sorted(repaired)})
        self.draft_put(db, config, 'draft_check_glossary', {'version': self.meta(db, 'glossary'), 'analysis': self.glossary(db)})
        self.draft_put(db, config, 'draft_imported_baseline', str(archived))
        self.event(db, 'draft_scan_imported', {'key': report['key'], 'report_file': str(archived),
                                              'recheck_required_ids': sorted(repaired)})
        return str(archived)

    def scan_drafts_in_transaction(self, db, config, prepare_repairs):
        from translation_workflow import write_json, encoded, fingerprint
        stage = config.get('_draft_stage', 'translate')
        prefix = 'pilot_' if stage == 'pilot_translate' else ''
        unfinished = self.unfinished_draft_repairs(db, stage)
        if unfinished:
            # A round is a fixed set of jobs. Neither quality checks nor another
            # repair round may start while any job in this set is unfinished.
            path = self.root / f'reports/{prefix}draft_round_status.json'
            status = {'phase': 'awaiting_round', 'status': 'needs_attention' if any(t['status'] == 'failed' for t in unfinished) else 'waiting_for_round',
                      'clean': False, 'checked_records': 0, 'failed_records': None,
                      'repair_tasks': [t['id'] for t in unfinished],
                      'repair_round': max(json.loads(t['payload']).get('draft_repair_round', 1) for t in unfinished),
                      'unfinished_batches': {s: sum(t['status'] == s for t in unfinished) for s in ('pending', 'running', 'failed')},
                      'next_action': f'Finish every batch in this repair round, then run draft-scan --stage {stage} --prepare-repairs'}
            write_json(path, status)
            return {**status, 'report_file': str(path)}
        rows, originals = self.draft_snapshot(db, config.get('_draft_stage', 'translate'))
        key = self.draft_audit_key(db, config)
        # Generation changes when a repair is submitted, but must not invalidate
        # the unchanged rows' checks. Policy changes do invalidate their receipts.
        keys = ('source_language', 'target_language', 'case_sensitive', 'whole_word', 'protect_named_curly',
                'placeholder_family_overrides', 'exclusions')
        policy = fingerprint({'validator': 3, 'term_match_version': bridge.TERM_MATCH_VERSION,
                              **({'scope': 'pilot'} if prefix else {}),
                              'source': self.meta(db, 'source_hash'),
                              'rules': {k: config[k] for k in keys}})
        signatures = {}
        for row in rows:
            journal = originals.get(row['id'])
            raw = ([journal['raw_item'], journal['protection']] if journal
                   and journal['source_hash'] == fingerprint(row['source'])
                   and journal['translation'] == row['translation'] else None)
            # Advancing into semantic review does not change an unchanged text's
            # signature. Keep raw-marker evidence stable across stage changes.
            signature_data = [row['source'], row['translation'], row['exceptions'], raw]
            if row['id'] in config.get('record_constraints', {}):
                signature_data.append(config['record_constraints'][row['id']])
            signatures[row['id']] = fingerprint(signature_data)
        self.adopt_legacy_draft_scan(db, config, rows, signatures, policy)
        previous = {r['record_id']: dict(r) for r in db.execute(f'SELECT * FROM {prefix}draft_checks WHERE policy_key=?', (policy,))}
        changed = [r['id'] for r in rows if r['id'] not in previous or previous[r['id']]['signature'] != signatures[r['id']]]
        pending_checks = set(self.draft_meta(db, config, 'draft_repair_pending_check', []))
        pending_checks.update(changed)
        changed = [r['id'] for r in rows if r['id'] in pending_checks]
        glossary_state = self.draft_meta(db, config, 'draft_check_glossary', {})
        glossary_version = self.meta(db, 'glossary')
        if previous and glossary_state.get('version') != glossary_version:
            old, new = glossary_state.get('analysis'), self.glossary(db)
            if old is None:
                previous = {}  # Legacy receipts do not prove which terms were checked.
            else:
                matching_rules = self.rules(db, config)
                def matched(analysis, source):
                    return sorted((t['src'], t['dst']) for t in bridge.matched_terms(analysis, [source], config, rules=matching_rules))
                from workflow_quality import glossary_revision_probes
                probes = glossary_revision_probes(old, new)
                affected = {r['id'] for r in rows
                            if (probes is None or any(matched(probe, r['source']) for probe in probes))
                            and matched(old, r['source']) != matched(new, r['source'])}
                affected.update(changed)
                changed = [r['id'] for r in rows if r['id'] in affected]
        findings = {r['id']: json.loads(previous[r['id']]['finding']) for r in rows
                    if r['id'] in previous and previous[r['id']]['finding'] != 'null'}
        rounds = []

        def check(phase, ids):
            scope = len(ids) if ids is not None else len(rows)
            print(f'[draft-scan] phase={phase} started; scope={scope} records', file=sys.stderr, flush=True)
            checked, found = self.collect_draft_issues(db, config, ids)
            by_id = {f['id']: f for f in found}
            for row in checked:
                record_id = row['id']
                journal = originals.get(record_id)
                regression = []
                if journal:
                    repair_task = db.execute('SELECT * FROM tasks WHERE id=?', (journal['task_id'],)).fetchone()
                    if repair_task:
                        failure = by_id.get(record_id)
                        self.record_repair_outcome(db, repair_task, record_id,
                            {k: failure[k] for k in ('diagnostics', 'missing_terms', 'structural_issues')} if failure else None)
                if journal and phase == 'issue_recheck':
                    task = db.execute('SELECT payload FROM tasks WHERE id=?', (journal['task_id'],)).fetchone()
                    if task:
                        original = next((r for r in json.loads(task['payload'])['records'] if r['id'] == record_id), None)
                        if original:
                            regression = self.repair_regression(db, config, stage, record_id, original,
                                row['translation'], json.loads(row['exceptions']), self.glossary(db), journal['task_id'])
                if record_id in by_id:
                    by_id[record_id]['regressed_terms'] = regression
                    if regression:
                        by_id[record_id]['diagnostics'].append('Regression: previously satisfied terms lost: ' + ', '.join(regression))
                findings.pop(record_id, None)
                if record_id in by_id:
                    findings[record_id] = by_id[record_id]
                db.execute(f'INSERT OR REPLACE INTO {prefix}draft_checks VALUES (?,?,?,?)',
                           (record_id, policy, signatures[record_id], encoded(by_id.get(record_id))))
            checked_ids = {r['id'] for r in checked}
            self.draft_put(db, config, 'draft_repair_pending_check', sorted(set(self.draft_meta(db, config, 'draft_repair_pending_check', [])) - checked_ids))
            attempts = self.draft_meta(db, config, 'draft_repair_attempts', {})
            self.draft_put(db, config, 'draft_repair_attempts', {i: n for i, n in attempts.items() if i not in checked_ids or i in by_id})
            rounds.append({'phase': phase, 'scope': 'issues' if ids is not None else 'full',
                           'checked_ids': [r['id'] for r in checked], 'checked_records': len(checked),
                           'passed_ids': [r['id'] for r in checked if r['id'] not in by_id],
                           'failures': found, 'remaining_failed_ids': list(findings)})

        if not previous:
            check('initial_full', None)
        elif changed:
            check('issue_recheck', changed)
            if not findings:
                # Only after the repair pool has converged do we run the one
                # final full acceptance. Never do this after every repair round.
                check('final_full', None)
        if glossary_state.get('version') != glossary_version:
            self.draft_put(db, config, 'draft_check_glossary', {'version': glossary_version, 'analysis': self.glossary(db)})
        failures = [findings[r['id']] for r in rows if r['id'] in findings]
        existing = [r for r in db.execute('SELECT * FROM tasks WHERE stage=? AND revision=? AND status IN ("pending","failed")', (stage, self.meta(db, 'revision')))
                    if json.loads(r['payload']).get('strict_translation')]
        tasks = [r['id'] for r in existing]
        blocked_ids = []
        history_routes = self.repair_routes(db, config, stage)
        routes = {r['id']: history_routes.get(r['id'], (0, 'standard')) for r in failures}
        blocked_ids = [i for i, (_, tier) in routes.items() if tier == 'stopped']
        if prepare_repairs and failures and not existing:
            failed_by_id = {r['id']: r for r in failures}
            contexts = self.meta(db, 'contexts', {})
            eligible = []
            for row in rows:
                if row['id'] in failed_by_id and row['id'] not in blocked_ids:
                    if row['locked']:
                        raise ValueError('Unlock affected confirmed translation before preparing draft repair: ' + row['id'])
                    row['metadata'] = contexts.get(str(row['ordinal']), {})
                    eligible.append(row)
            # Same diagnostic kinds are adjacent; group boundaries and original
            # producer-batch boundaries do not split the repair pool.
            eligible.sort(key=lambda r: (bool(failed_by_id[r['id']]['structural_issues']), bool(failed_by_id[r['id']]['missing_terms']), r['ordinal']))
            glossary, rules = self.glossary(db), self.rules(db, config)
            history = [json.loads(t['payload']) for t in db.execute('SELECT payload FROM tasks WHERE stage=? AND revision=?', (stage, self.meta(db, 'revision')))
                       if json.loads(t['payload']).get('draft_scan_key')]
            round_number = 1 + max((t.get('draft_repair_round', 1) for t in history), default=0)
            groups = [group for used, tier in sorted({routes[r['id']] for r in eligible})
                      for group in self.batches([r for r in eligible if routes[r['id']] == (used, tier)], config, respect_groups=False, stage=stage)]
            for group in groups:
                task_id = prefix + 'draft-repair-' + uuid.uuid4().hex[:20]
                payload = {'task_id': task_id, 'stage': stage, 'revision': self.meta(db, 'revision'),
                           'source_hash': self.meta(db, 'source_hash'), 'layout_policy': config.get('layout_normalization', 'off'), 'strict_translation': True, 'draft_scan_key': key,
                           'draft_repair_round': round_number,
                           **self.repair_routing(config, routes[group[0]['id']][1]),
                           'repair_counts': {r['id']: routes[r['id']][0] + 1 for r in group},
                           'language': {'source': config['source_language'], 'target': config['target_language']},
                           'style': config['style'], 'game_background': '', 'context': [], 'records': [],
                           'glossary_version': self.meta(db, 'glossary'),
                           'terms': bridge.matched_terms(glossary, [r['source'] for r in group], config, rules=rules),
                           'revision_request': '全文草稿已完成；本批为跨批汇总的失败语句。只修复列出的诊断，保留其他已保存译文。'}
                for row in group:
                    row_rules = bridge.record_rules(row, config, rules)
                    protected, protection = bridge.protect(row['source'], row['id'], row_rules)
                    payload['records'].append({'id': row['id'], 'ordinal': row['ordinal'], 'source': protected,
                        'translation': row['translation'], 'protection': protection, 'metadata': row['metadata'],
                        'exceptions': json.loads(row['exceptions']), 'locked': bool(row['locked']),
                        'repair_constraints': self.repair_constraints(row['source'], row['translation'], json.loads(row['exceptions']), glossary, config, rules=row_rules),
                        'diagnostic': failed_by_id[row['id']]['diagnostics'],
                        'candidate': {'id': row['id'], 'translation': row['translation']}})
                signature = fingerprint(payload); payload['input_hash'] = signature
                tasks.extend(self.allocate_task(db, payload,
                    config.get('escalation_backend', 'codex') if payload['repair_tier'] == 'sol' else config['stage_backends'].get(stage, config['backend'])))
        clean = not failures and not tasks
        report_file = self.root / f'reports/{prefix}full_draft_scan.json'
        task_states = [dict(r) for r in db.execute('SELECT id,status,attempt,ids,payload FROM tasks WHERE stage=? AND revision=?',
                                                  (stage, self.meta(db, 'revision')))
                       if json.loads(r['payload']).get('draft_scan_key')]
        for state in task_states:
            state['ids'] = json.loads(state['ids'])
            state['round'] = json.loads(state.pop('payload')).get('draft_repair_round', 1)
        round_files = []
        for report in rounds:
            report.update({'key': key, 'policy_key': policy, 'repair_status': task_states,
                           'result': 'passed' if not report['remaining_failed_ids'] else 'needs_repair'})
            cursor = db.execute(f'INSERT INTO {prefix}draft_check_rounds(report) VALUES (?)', (encoded(report),))
            report['round'] = cursor.lastrowid
            path = self.root / f'reports/{prefix}draft_checks/round_{cursor.lastrowid:05d}.json'
            write_json(path, report)
            db.execute(f'UPDATE {prefix}draft_check_rounds SET report=? WHERE id=?', (encoded(report), cursor.lastrowid))
            round_files.append(str(path))
        summary = {'stage': stage, 'key': key, 'records': len(rows), 'failed_records': len(failures),
                   'clean': clean, 'failures': failures, 'repair_tasks': tasks,
                   'repair_dispatch': self.repair_dispatch(db, tasks),
                   'phase': rounds[-1]['phase'] if rounds else 'cached',
                   'checked_records': sum(r['checked_records'] for r in rounds),
                   'checked_rounds': [{k: r[k] for k in ('round', 'phase', 'scope', 'checked_records', 'result')} for r in rounds],
                   'round_reports': round_files, 'repair_status': task_states,
                   'imported_baseline': self.draft_meta(db, config, 'draft_imported_baseline'),
                   'needs_attention_ids': blocked_ids}
        summary['repair_stop_reasons'] = {i: reason for i, reason in self.repair_stops(db, config, stage=stage).items() if i in blocked_ids}
        summary['status'] = 'needs_attention' if blocked_ids else ('clean' if clean else 'needs_repair')
        write_json(report_file, summary)
        self.draft_put(db, config, 'draft_audit', {'key': key, 'clean': clean})
        self.event(db, 'draft_scan', {k: summary[k] for k in ('key', 'phase', 'checked_records', 'failed_records', 'repair_tasks', 'round_reports')})
        return {k: v for k, v in {**summary, 'report_file': str(report_file)}.items() if k not in ('failures', 'repair_status')}
