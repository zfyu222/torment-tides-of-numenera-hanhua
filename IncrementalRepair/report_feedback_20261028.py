"""Report only actual API evidence, formal export and offline/installed checks."""
import argparse
import json
import re
import time
from pathlib import Path

import feedback_20261028 as feedback
import repair


def main(candidate_only=False):
    r = feedback.FeedbackRepair()
    work = r.work
    baseline = repair.w.read_json(work / 'baseline.json')
    rows = repair.w.read_json(work / 'records.json')
    path = work / 'torment-tides-of-numenera_text_translated_candidate.csv' if candidate_only else r.project / baseline['translation_file']
    values = repair.read_column(path)
    manifest = repair.w.read_json(work / 'candidate_manifest.json')
    export = repair.w.read_json(r.project / 'TranslateFiles/reports/final_validation.json')
    if (not candidate_only and export['status'] != 'passed') or repair.sha(path) != (
            manifest['candidate_sha256'] if candidate_only else export['translation_sha256']):
        raise ValueError('Formal export is not the validated candidate')
    if not candidate_only and values != repair.read_column(work / 'torment-tides-of-numenera_text_translated_candidate.csv'):
        raise ValueError('Formal export values differ from candidate')
    source_hash = repair.sha(r.project / baseline['source_file'])
    if source_hash != baseline['source_sha256'] or len(values) != len(rows):
        raise ValueError('Source binding or row count changed')
    plan = repair.w.read_json(work / 'repair_plan.json')
    scope = set(plan['scope_ids'])
    if any(values[row['ordinal']-1] != row['translation'] for row in rows if row['id'] not in scope):
        raise ValueError('Translation outside approved scope changed')
    rules = repair.bridge.patterns(baseline['config']['protect_named_curly'], baseline['config']['exclusions'],
        baseline['config'].get('placeholder_family_overrides'))
    counts = {k: {'reviewed': 0, 'changed': 0} for k in ('species', 'mirror', 'branches', 'english_status', 'alive')}
    failures = []
    checks = []
    for row, translated in zip(rows, values):
        source, before, after = row['source'], row['translation'], translated
        for _, pattern in repair.bridge.record_rules(row, baseline['config'], rules):
            source = pattern.sub('', source)
            before = pattern.sub('', before)
            after = pattern.sub('', after)
        categories = []
        if feedback.CREATURE.search(source): categories.append('species')
        if 'doppelganger' in source.casefold(): categories.append('mirror')
        if feedback.BRANCH.search(source): categories.append('branches')
        if feedback.STATUS.search(before): categories.append('english_status')
        if row['ordinal'] == 1912: categories.append('alive')
        if row['id'] in scope:
            for key in categories:
                counts[key]['reviewed'] += 1
                counts[key]['changed'] += translated != row['translation']
        if 'species' in categories and re.search('斯提库斯|斯蒂库斯', after):
            failures.append({'id': row['id'], 'type': 'old_species_variant', 'translation': translated})
        if 'english_status' in categories and feedback.STATUS.search(after):
            failures.append({'id': row['id'], 'type': 'english_status_remaining', 'translation': translated})
        if 53017 <= row['ordinal'] <= 53041 and 'mirror' in categories and '二重身' not in after:
            failures.append({'id': row['id'], 'type': 'mirror_choice_inconsistency', 'translation': translated})
        if 'branches' in categories:
            pairs = feedback.BRANCH.findall(after)
            source_pairs = feedback.BRANCH.findall(source)
            required = sum(not feedback.grammatical_branch(pair) for pair in source_pairs)
            if not required <= len(pairs) <= len(source_pairs) or any(
                re.search(r'[A-Za-z]', re.sub(r'\[[^\]]+\]|<[^>]+>', '', pair)) for pair in pairs):
                failures.append({'id': row['id'], 'type': 'runtime_branch_problem'})
        if row['ordinal'] in (1912, 12619, 12620, 12621, 26904, 45691, 53019, 53020, 53021, 53023, 53027, 62336, 62518, 62699, 63858):
            checks.append(dict(id=row['id'], ordinal=row['ordinal'], resource=row['metadata'].get('resource'),
                source=row['source'], before=row['translation'], after=translated))
    if failures:
        repair.w.write_json(work / 'remaining_feedback_findings.json', failures)
        raise ValueError('Feedback defects remain; inspect preserved findings')
    if candidate_only:
        local = dict(status='candidate_feedback_audit_passed', categories=counts, findings=[])
        repair.w.write_json(work / 'feedback_local_audit.json', local)
        print(json.dumps(local, ensure_ascii=True))
        return
    calls = repair.w.read_json(work / 'calls.json')
    if any(x['status'] == 'reserved' for x in calls):
        raise ValueError('Unknown in-flight requests')
    totals = {k: sum(x.get('usage', {}).get(k, 0) or 0 for x in calls if x.get('usage', {}).get('usage_reported'))
        for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    totals.update(requests=len(calls), unknown_usage_requests=sum(not x.get('usage', {}).get('usage_reported') for x in calls),
        service_failures=sum(repair.service_failure(x['status']) for x in calls),
        billing='Provider-reported tokens; monetary charge not inferred.',
        request_window_seconds=round(max(x['issued_at'] + x.get('elapsed_seconds', 0) for x in calls) - min(x['issued_at'] for x in calls), 2))
    totals['per_stage'] = {stage: dict(requests=sum(x['stage'] == stage for x in calls),
        reported_tokens=sum(x.get('usage', {}).get('total_tokens', 0) or 0 for x in calls if x['stage'] == stage))
        for stage in sorted({x['stage'] for x in calls})}
    report = dict(status='formal_export_and_local_files_verified', date='2026-10-28', revision=export['revision'],
        source_sha256=source_hash, translation_sha256=export['translation_sha256'],
        scope_records=manifest['scope_records'], changed_records=manifest['changed_records'],
        unchanged_outside_scope=manifest['preserved_outside_scope'], categories=counts, usage=totals,
        screenshot_examples=checks, remaining_known_feedback_findings=[],
        methodology='All new translation/repair and semantic term decisions came from configured API; actual replies, checks, source hashes and cumulative attempts retained. No Sol translation/repair.',
        additional_mirror_term_audit='TranslateFiles/feedback_20261028/mirror_terms',
        crop_patch=repair.w.read_json(r.project / 'TranslateFiles/reports/cjk_crop_patch_20261028.json'),
        deployment=repair.w.read_json(r.project / 'TranslateFiles/reports/deployment_feedback_20261028.json'),
        limitations=['No game launch or desktop control; screenshot scenarios and other resolutions remain pending in-game validation.',
            'Crop failure reproduced with the actual item translation plus synthetic prerequisite markup, not a fresh game capture.',
            'Public release unchanged; no ZIP generated or published.'])
    output = r.project / 'IncrementalRepair/feedback_20261028_report.json'
    repair.w.write_json(output, report)
    print(json.dumps({k: report[k] for k in ('status', 'revision', 'scope_records', 'changed_records', 'unchanged_outside_scope', 'categories', 'usage')}, ensure_ascii=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', action='store_true')
    main(parser.parse_args().candidate)
