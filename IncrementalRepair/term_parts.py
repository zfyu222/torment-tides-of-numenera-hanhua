"""Recover actual term decisions without inventing missing classifications."""
import copy
import re
import repair
from inspect_term_recovery import decision_object

FIELDS = ('reviewed_refs', 'entry_reviews', 'acknowledged_findings', 'edits',
          'quarantine', 'additions', 'allow_no_match')


def normalize_acknowledgments(d, binding):
    """Read explicitly named acknowledgments, retaining raw explanatory notes."""
    result = copy.deepcopy(d)
    values = d.get('acknowledged_findings', [])
    if not isinstance(values, list):
        raise ValueError('Finding acknowledgments must be a list')
    mapping = binding['glossary']['finding_refs']; reverse = {v:k for k,v in mapping.items()}
    refs = []
    for value in values:
        ref = value.get('id') if isinstance(value, dict) else value
        if isinstance(ref, str):
            match = re.fullmatch(r'(f\d+|F\d+)(?:[：:]\s*[^\n]+)?', ref)
            if match: ref = match.group(1)
        ref = reverse.get(ref, ref) if isinstance(ref, str) else ref
        if not isinstance(ref, str) or ref not in mapping:
            raise ValueError('Unknown explicit finding acknowledgment')
        if ref not in refs: refs.append(ref)
    result['acknowledged_findings'] = refs
    return result


def acknowledgments(folder, payload):
    refs = set()
    for path in (folder / 'term_acks').glob('*.json'):
        saved = repair.w.read_json(path)
        if saved['input_hash'] != payload['input_hash']:
            raise ValueError('Finding acknowledgment binding mismatch')
        refs.update(saved['refs'])
    for saved in rows(folder, payload).values():
        refs.update(saved['decisions'].get('acknowledged_findings', []))
    return refs


def rows(folder, payload):
    result = {}
    refs = {e['ref'] for e in payload['entries']}
    for path in (folder / 'term_parts').glob('*.json'):
        saved = repair.w.read_json(path)
        if saved['input_hash'] != payload['input_hash'] or saved['ref'] not in refs:
            raise ValueError('Term partial binding mismatch')
        result[saved['ref']] = saved
    return result


def save(r, folder, payload, request_payload, parsed, binding, instance, raw_path):
    d, normalization = decision_object(parsed)
    if d is None:
        raise ValueError('API glossary review requires decisions')
    d = normalize_acknowledgments(d, binding)
    # A real reply contained all four genuine checks plus a stray empty '.'.
    # Drop that empty punctuation field only; never fill missing dimensions.
    for review in d.get('entry_reviews', []):
        checks = review.get('checks') if isinstance(review, dict) else None
        if isinstance(checks, dict) and checks.get('.') == []:
            checks.pop('.')
    result = repair.canonical_api_result({'decisions': d}, binding, payload['task_id'],
        payload['task_id'], payload['input_hash'], [x['id'] for x in request_payload['records']])
    d = result['decisions']
    if d.get('review_complete') is not True or not str(d.get('review_summary', '')).strip():
        raise ValueError('Explicit term completion and summary required')
    # This repair does not expand the glossary. Never discard additions silently.
    if d.get('additions'):
        raise ValueError('Unrequested term additions need separate investigation')
    repair.w.write_json(folder / 'term_acks' / (instance.replace(':', '_') + '.json'),
        {'input_hash': payload['input_hash'], 'refs': d.get('acknowledged_findings', []),
         'instance': instance, 'response_sha256': repair.sha(raw_path)})
    existing = rows(folder, payload)
    errors = []
    reviews = {x['ref']: x for x in d['entry_reviews']}
    expected = {e['ref'] for e in request_payload['entries']}
    for action in ('edits', 'quarantine'):
        if any(f"{x['table']}:{x['index']}" not in expected for x in d.get(action, [])):
            raise ValueError('Unassigned term action')
    for entry in request_payload['entries']:
        ref = entry['ref']
        if ref in existing:
            continue
        part = {k: copy.deepcopy(v) for k, v in d.items() if k not in FIELDS}
        part.update({k: [] for k in FIELDS})
        part['entry_reviews'] = [reviews[ref]]; part['reviewed_refs'] = [ref]
        part['acknowledged_findings'] = list(d.get('acknowledged_findings', []))
        for action in ('edits', 'quarantine'):
            part[action] = [x for x in d.get(action, []) if f"{x['table']}:{x['index']}" == ref]
        sources = {entry['row']['source']} | {x['patch'].get('source') for x in part['edits']}
        part['allow_no_match'] = [x for x in d.get('allow_no_match', []) if x.get('source') in sources]
        try:
            assigned_rows = set(entry['row'].get('evidence_rows', [])) | set(entry['row'].get('corpus_evidence_rows', []))
            provided = {row['ordinal']: row for row in request_payload['records']}
            actions = part['edits'] + part['quarantine']
            if len(actions) > 1:
                raise ValueError('Repeated or conflicting term action')
            for action in actions:
                if not str(action.get('reason', '')).strip() or not action.get('evidence_rows'):
                    raise ValueError('Term action needs actual reason and evidence')
                if any(type(n) is not int or n not in assigned_rows or n not in provided for n in action['evidence_rows']):
                    raise ValueError('Term action cites unassigned evidence')
            r.validate_result({**request_payload, 'entries': [entry]}, {'decisions': part}, None)
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(ref + ': ' + str(exc)); continue
        repair.w.write_json(folder / 'term_parts' / (ref.replace(':', '_') + '.json'),
            {'ref': ref, 'input_hash': payload['input_hash'], 'decisions': part,
             'instance': instance, 'response_sha256': repair.sha(raw_path),
             'evidence_records': [provided[n] for n in sorted(set(reviews[ref]['evidence_rows']) |
                {n for action in actions for n in action.get('evidence_rows', [])})],
             'normalization': normalization})
    complete = finish(r, folder, payload)
    if not complete:
        raise ValueError('Only missing/invalid term entries need retry: ' + '; '.join(errors)[:1100])


def validation_payload(r, folder, payload, parts=None):
    """Merge only source records actually provided to each accepted part."""
    parts = rows(folder, payload) if parts is None else parts
    contexts = {row['ordinal']: row for row in payload['records']}
    if hasattr(r, 'work') and (r.work / 'source.csv').exists():
        if not hasattr(r, '_term_source_texts'):
            r._term_source_texts = repair.read_column(r.work / 'source.csv')
        texts = r._term_source_texts
    else:
        texts = None
    for part in parts.values():
        supplied = part.get('evidence_records')
        if supplied is None:
            request = folder / part['instance'].removeprefix('api:') / 'payload.json'
            if not request.exists(): continue
            request_payload = repair.w.read_json(request)
            if request_payload['input_hash'] != payload['input_hash']:
                raise ValueError('Part request binding mismatch')
            supplied = request_payload['records']
        for row in supplied:
            ordinal = row['ordinal']
            if texts is not None and (type(ordinal) is not int or not 1 <= ordinal <= len(texts)
                                      or row['source'] != texts[ordinal-1]):
                raise ValueError('Part source differs from immutable corpus')
            if ordinal in contexts and contexts[ordinal]['source'] != row['source']:
                raise ValueError('Conflicting original evidence')
            contexts[ordinal] = row
    return {**payload, 'records': [contexts[n] for n in sorted(contexts)]}


def finish(r, folder, payload):
    parts = rows(folder, payload)
    if set(parts) != {e['ref'] for e in payload['entries']}:
        return False
    summaries = list(dict.fromkeys(p['decisions']['review_summary'] for p in parts.values()))
    decisions = {k: copy.deepcopy(v) for k, v in next(iter(parts.values()))['decisions'].items() if k not in FIELDS}
    decisions['review_summary'] = '\n'.join(summaries)
    for key in FIELDS:
        decisions[key] = [v for e in payload['entries'] for v in parts[e['ref']]['decisions'].get(key, [])]
    decisions['acknowledged_findings'] = sorted(acknowledgments(folder, payload))
    missing = {f['id'] for f in payload['audit']['findings']} - set(decisions['acknowledged_findings'])
    if missing:
        return False
    result = {'decisions': decisions}
    r.validate_result(validation_payload(r, folder, payload, parts), result, None)
    repair.w.write_json(folder / 'accepted.json', {'result': result, 'input_hash': payload['input_hash'],
        'entry_instances': {ref: p['instance'] for ref, p in parts.items()},
        'entry_response_sha256': {ref: p['response_sha256'] for ref, p in parts.items()}})
    return True


def recover():
    r = repair.Repair(); r.snapshot()
    if (r.work / 'runner.lock').exists():
        raise ValueError('A repair runner still owns this workspace')
    calls = repair.w.read_json(r.work / 'calls.json')
    if any(c['status'] == 'reserved' for c in calls):
        raise ValueError('Unknown in-flight request')
    jobs = [r.work / x for x in repair.w.read_json(r.work / 'glossary_review_jobs.json')]
    recovered = 0
    for folder in jobs:
        if (folder / 'accepted.json').exists(): continue
        payload = r.term_payload(repair.w.read_json(folder / 'payload.json'))
        for call in calls:
            if call['job'] != folder.name or call['status'] not in ('received', 'rejected'): continue
            raw = folder / call['id'] / 'response.raw.txt'
            if not raw.exists(): continue
            request = raw.parent / 'payload.json'; bind = raw.parent / 'binding.json'
            try:
                save(r, folder, payload, repair.w.read_json(request) if request.exists() else payload,
                     repair.bridge.parse_response(raw.read_text(encoding='utf8')),
                     repair.w.read_json(bind) if bind.exists() else repair.w.read_json(folder / 'binding.json'),
                     'api:' + call['id'], raw)
            except (ValueError, KeyError, TypeError):
                continue
            recovered += 1; break
    report = {'accepted_jobs': sum((p / 'accepted.json').exists() for p in jobs),
              'offline_recovered_jobs': recovered,
              'valid_parts_in_pending_jobs': sum(len(rows(p, repair.w.read_json(p/'payload.json')))
                 for p in jobs if not (p/'accepted.json').exists())}
    repair.w.write_json(r.work / 'term_parts_recovery.json', report)
    print(__import__('json').dumps(report))


if __name__ == '__main__':
    recover()
