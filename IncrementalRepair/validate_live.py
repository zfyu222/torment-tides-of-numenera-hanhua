"""At most six real calls on project feedback; separate disposable workspace."""
from pathlib import Path
import copy
import json
import shutil
import threading
import argparse
import uuid

import repair


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', action='store_true', help='Keep previous calls/results and continue within the same six-call cap')
    args = parser.parse_args()
    root = repair.PROJECT / 'TranslateFiles/incremental_repair_20261024_validation_v2'
    if root.exists() and not args.resume:
        raise ValueError('Validation workspace already exists; preserve previous evidence')
    previous = repair.w.read_json(root / 'validation_report.json') if (root / 'validation_report.json').exists() else {}
    if not root.exists():
        root.mkdir()
        for name in ('baseline.json', 'records.json', 'source.csv', 'old_glossary.json', 'preparation.json',
                     'structural_findings.json', 'individual_cases.json'):
            shutil.copy2(repair.WORK / name, root / name)
        shutil.copytree(repair.WORK / 'term_audit', root / 'term_audit')
    r = repair.Repair(root)
    old_report = repair.PROJECT / 'TranslateFiles/incremental_repair_20261024_validation/validation_report.json'
    previous_view_calls = repair.w.read_json(old_report).get('actual_wire_requests', 0) if old_report.exists() else 0
    counter = [previous.get('actual_wire_requests', previous_view_calls)]; lock = threading.Lock(); parent_api = repair.bridge.AINieeAPI
    class BoundedAPI(parent_api):
        def request(self, system, user):
            with lock:
                if counter[0] >= 6:
                    raise repair.bridge.ApiFailure('validation_wire_limit', False, usage={'usage_reported': False})
                counter[0] += 1
            return super().request(system, user)
    repair.bridge.AINieeAPI = BoundedAPI
    report = {'wire_limit': 6, 'validation_only': True, 'prior_view_wire_requests': previous_view_calls,
              'note': 'Uses the compact current-term input; previous 503 input/history retained and counted in the six-call cap.'}
    try:
        r.prepare_terms({'Matkina', 'Numenera', 'Hardened', 'user', 'Child {Female}'})
        report['term_run'] = r.run_jobs('glossary_review')
        if report['term_run']['remaining']:
            raise ValueError('Term smoke sample not accepted')
        old = repair.w.read_json(root / 'old_glossary.json'); new = copy.deepcopy(old)
        quarantined = set(); edits = {}; judgments = []
        for relative in repair.w.read_json(root / 'glossary_review_jobs.json'):
            saved = repair.w.read_json(root / relative / 'accepted.json')
            d = saved['result']['decisions']
            if d.get('additions'):
                raise ValueError('Smoke preview does not silently merge additions')
            for e in d.get('edits', []):
                edits[(e['table'], e['index'])] = e['patch']
            quarantined.update((e['table'], e['index']) for e in d.get('quarantine', []))
            judgments.extend(d['entry_reviews'])
        for table in repair.TABLES:
            for i, row in enumerate(new[table]):
                row.update(edits.get((table, i), {}))
            new[table] = [row for i, row in enumerate(new[table]) if (table, i) not in quarantined]
        retained = {row['source']: row for t in ('characters', 'terms') for row in new[t]}
        if 'user' in retained or 'Child {Female}' in retained:
            raise ValueError('Actual API did not remove ordinary user/Child marker combination')
        if retained['Hardened'].get('recommended_translation') == '硬化':
            raise ValueError('Actual API left the Hardened descriptor mistranslation')
        old_matkina = next(row for row in old['characters'] if row['source'] == 'Matkina')
        if retained['Matkina']['recommended_translation'] != old_matkina['recommended_translation']:
            raise ValueError('Unnecessary established proper-name rewrite in smoke sample')
        repair.w.write_json(root / 'new_glossary.json', new)
        report['full_automatic_scope_preview'] = r.plan()
        full_plan = repair.w.read_json(root / 'repair_plan.json')
        records = repair.w.read_json(root / 'records.json')
        samples = {row['id'] for row in records if row['ordinal'] in (57207, 57530, 62257, 63811)}
        chosen = set(full_plan['term_affected_ids']).intersection(samples)
        if not any(row['id'] in chosen and row['ordinal'] == 57207 for row in records):
            raise ValueError('Hardened was not identified by actual effective term changes')
        full_plan['term_affected_ids'] = sorted(chosen)
        full_plan['scope_ids'] = sorted(chosen | set(full_plan['structural_ids']) | set(full_plan['individual_ids']))
        full_plan['preserved_records'] = len(records) - len(full_plan['scope_ids'])
        full_plan['validation_scope_only'] = True
        repair.w.write_json(root / 'repair_plan.json', full_plan)
        r.prepare_translation(); report['translate_run'] = r.run_jobs('translate')
        if report['translate_run']['remaining']:
            raise ValueError('Source-only translation smoke incomplete')
        r.prepare_review(); report['review_run'] = r.run_jobs('review')
        if report['review_run']['remaining']:
            raise ValueError('Independent review smoke incomplete')
        report['candidate'] = r.export_candidate()
        accepted = r.accepted_body('review', new)
        if any('胡茬' in accepted[rid]['item']['translation'] for rid in full_plan['individual_ids']):
            raise ValueError('Actual review still retained the reported scalp error')
        report['feedback_outputs'] = [{'ordinal': row['ordinal'], 'source': row['source'],
            'translation': accepted[row['id']]['item']['translation']} for row in records if row['id'] in accepted]
        report['term_decisions'] = {'quarantine': sorted(quarantined), 'edits': [
            {'table': t, 'index': i, 'patch': p} for (t, i), p in edits.items()], 'judgments': judgments}
    except Exception as exc:
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        repair.bridge.AINieeAPI = parent_api
        report['actual_wire_requests'] = counter[0]
        report['formal_translation_sha256_after'] = repair.sha(repair.PROJECT / r.snapshot()['translation_file'])
        if previous:
            archive = root / 'validation_history' / (uuid.uuid4().hex + '.json')
            repair.w.write_json(archive, previous)
        repair.w.write_json(root / 'validation_report.json', report)
        print(json.dumps({k: v for k, v in report.items() if k not in ('feedback_outputs', 'term_decisions')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
