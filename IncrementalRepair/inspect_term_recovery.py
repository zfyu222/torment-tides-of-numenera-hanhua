"""Read-only per-entry recovery inspection of actual rejected term replies.

No API, no defaults for semantic fields, and no alteration of accepted jobs.
"""
import copy
from collections import Counter
import json

import repair


def decision_object(raw):
    if isinstance(raw.get('decisions'), dict):
        return raw['decisions'], None
    if 'entry_reviews' in raw:
        d = copy.deepcopy(raw)
        if 'review_complete' not in d and type(d.get('stage_review_complete')) is bool:
            d['review_complete'] = d.pop('stage_review_complete')
        for key in ('stage_glossary_review', 'stage'):
            d.pop(key, None)
        return d, 'flat_decision_object'
    if len(raw) == 1:
        value = next(iter(raw.values()))
        if isinstance(value, dict) and 'entry_reviews' in value:
            return value, 'single_wrapper_object'
    return None, None


def ref_value(value, mapping):
    if value in mapping:
        return mapping[value]
    if value in mapping.values():
        return value
    if isinstance(value, (str, int)) and str(value).isdigit():
        return mapping.get('e' + str(value))
    return None


def inspect():
    r = repair.Repair(); r.snapshot()
    folders = [r.work / p for p in repair.w.read_json(r.work / 'glossary_review_jobs.json')]
    ledger = repair.w.read_json(r.work / 'calls.json')
    calls = {}
    for c in ledger:
        if c['status'] in ('rejected', 'received'):
            calls.setdefault(c['job'], []).append(c)
    summary = Counter(); recovered = {}; job_reports = []
    for folder in folders:
        if (folder / 'accepted.json').exists():
            summary['already_accepted_jobs'] += 1
            continue
        payload = repair.w.read_json(folder / 'payload.json'); binding = repair.w.read_json(folder / 'binding.json')
        entries = {e['ref']: e for e in payload['entries']}; mapping = binding['glossary']['entry_refs']
        reverse = {v:k for k,v in mapping.items()}; strict = {}; semantic_only = {}; errors = Counter()
        extras = []
        for call in calls.get(folder.name, []):
            path = folder / call['id'] / 'response.raw.txt'
            if not path.exists():
                continue
            try:
                raw = repair.bridge.parse_response(path.read_text(encoding='utf-8'))
                d, normalization = decision_object(raw)
                if not isinstance(d, dict) or d.get('review_complete') is not True:
                    continue
                review_rows = d.get('entry_reviews', [])
                if not isinstance(review_rows, list):
                    continue
                counts = Counter(ref_value(x.get('ref'), mapping) for x in review_rows if isinstance(x, dict))
                for review in review_rows:
                    if not isinstance(review, dict): continue
                    ref = ref_value(review.get('ref'), mapping)
                    if ref not in entries or counts[ref] != 1: continue
                    sub_d = {k:copy.deepcopy(v) for k,v in d.items()
                             if k not in ('entry_reviews','reviewed_refs','edits','quarantine','additions','allow_no_match','acknowledged_findings')}
                    sub_review = copy.deepcopy(review); sub_review['ref'] = reverse[ref]
                    sub_d.update(entry_reviews=[sub_review], reviewed_refs=[reverse[ref]],
                        edits=[], quarantine=[], additions=[], allow_no_match=[], acknowledged_findings=[])
                    for action in ('edits','quarantine','allow_no_match'):
                        for value in d.get(action, []):
                            if not isinstance(value, dict): continue
                            action_ref = ref_value(value.get('ref'), mapping)
                            if action_ref is None and 'table' in value and type(value.get('index')) is int:
                                action_ref = f"{value['table']}:{value['index']}"
                            if action_ref != ref: continue
                            value = copy.deepcopy(value); value.pop('table',None); value.pop('index',None)
                            value['ref'] = reverse[ref]; sub_d[action].append(value)
                    sub_binding = {**binding,'glossary':{**binding['glossary'],'assigned_refs':[ref]}}
                    sub_payload = {**payload,'entries':[entries[ref]],'audit':{**payload['audit'],'findings':[]}}
                    scope = [row['id'] for row in payload['records']]
                    try:
                        decoded = repair.canonical_api_result({'decisions':sub_d}, sub_binding,
                            binding['session_id'],payload['task_id'],payload['input_hash'],scope)
                        base_payload = {**sub_payload,'terminology_policy':0}
                        repair.validate_glossary_reviews(decoded['decisions'],base_payload)
                    except (ValueError,KeyError,TypeError) as exc:
                        errors[str(exc).split(';')[0][:120]] += 1;continue
                    evidence = {'call_id':call['id'],'job':folder.name,'ref':ref,'normalization':normalization,
                        'raw_sha256':repair.sha(path),'result':decoded['decisions'],
                        'global_findings_not_yet_validated':d.get('acknowledged_findings',[]),
                        'batch_additions_not_merged':d.get('additions',[])}
                    semantic_only[ref] = evidence
                    try:
                        repair.validate_glossary_reviews(decoded['decisions'],sub_payload)
                    except (ValueError,KeyError,TypeError) as exc:
                        errors[str(exc).split(';')[0][:120]] += 1;continue
                    strict[ref] = evidence
            except (ValueError,KeyError,TypeError) as exc:
                errors[str(exc)[:120]] += 1
        missing = sorted(set(entries)-set(strict))
        summary['unaccepted_jobs_inspected'] += 1
        summary['fully_valid_entry_candidates'] += len(strict)
        summary['semantic_evidence_without_complete_policy'] += len(set(semantic_only)-set(strict))
        summary['no_valid_semantic_evidence'] += len(set(entries)-set(semantic_only))
        if not missing:summary['jobs_with_all_entry_candidates'] += 1
        recovered[folder.name] = {'strict':strict,'semantic_only':semantic_only}
        job_reports.append({'job':folder.name,'assigned':len(entries),'strict_valid':len(strict),
            'missing_policy_refs':missing,'errors':dict(errors)})
    output = {'status':'inspection_only_no_acceptance_or_api','counts':dict(summary),'jobs':job_reports}
    repair.w.write_json(r.work/'term_recovery_inspection.json',output)
    repair.w.write_json(r.work/'term_recovery_candidates.json',recovered)
    print(json.dumps(output['counts'],ensure_ascii=False))


if __name__ == '__main__':
    inspect()
