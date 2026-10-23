"""Evidence-backed pilot, independent review, Sol acceptance and runtime checks.

Reports propose checks; only the orchestrating Sol writes acceptance decisions.
Worker IDs are actual agent instance IDs supplied by the trusted orchestrator.
"""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import random
import uuid
from workflow_tokens import count_tokens, record_limit, record_tokens, batch_limit

REVIEW_CHECKS = ('accuracy', 'completeness', 'terminology', 'tone', 'logic', 'placeholders')
GLOSSARY_CHECKS = ('source', 'translation', 'category', 'consistency')
SOL_SCOPE_POLICY = 'disputes_only_v1'


def glossary_match_meaning(matches):
    # refs are list coordinates, not terminology semantics. Quarantining an
    # earlier entry renumbers later refs without changing their actual meaning.
    return [{k: v for k, v in item.items() if k != 'ref'} for item in matches]


def glossary_revision_probes(old, new):
    """Conservative source-match prefilter; callers still compare full results.

    A row with no matching changed source cannot change its match result. Fall
    back to the old full scan for duplicate identities or reordered common rows.
    Keep original entries, including applicability and protected-token semantics.
    """
    tables = ('characters', 'terms', 'non_translate')
    def inventory(value):
        rows = [((table, row['source']), row) for table in tables for row in value.get(table, [])]
        return [key for key, _ in rows], dict(rows)
    old_order, a = inventory(old)
    new_order, b = inventory(new)
    if len(a) != len(old_order) or len(b) != len(new_order):
        return None
    common = set(a).intersection(b)
    if [k for k in old_order if k in common] != [k for k in new_order if k in common]:
        return None
    changed = {k for k in set(a).union(b) if a.get(k) != b.get(k)}
    return tuple({table: [row for row in value.get(table, []) if (table, row['source']) in changed]
                  for table in tables} for value in (old, new))


def signature(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def quote_matches(excerpt, text):
    """A citation must be contiguous source text, ignoring only whitespace layout.

    Re-wrapped lines and collapsed spaces do not change the quoted words, so the
    same sentence copied across a line break still verifies as evidence;
    paraphrases, joins and omissions remain rejected.
    """
    if not nonempty(excerpt) or not isinstance(text, str):
        return False
    if excerpt in text:
        return True
    return re.sub(r'\s+', ' ', excerpt).strip() in re.sub(r'\s+', ' ', text).strip()


class ReviewContractError(ValueError):
    """Machine-readable evidence errors; never a semantic correctness verdict."""
    def __init__(self, message, code, fields, repair):
        self.detail = {'category': 'review_record_contract', 'code': code,
                       'fields': fields, 'repair': repair}
        super().__init__(message + '; ' + repair + ' Fields: ' + json.dumps(fields, ensure_ascii=False))


def review_failure_detail(error):
    if isinstance(error, ReviewContractError):
        return error.detail
    text = str(error)
    category = ('terminology_gate' if 'terminology mismatch' in text else
                'structure_gate' if 'structural mismatch' in text else
                'reported_blocking_semantic_issue' if 'Unresolved blocking semantic issue' in text else
                'review_record_contract')
    return {'category': category, 'code': 'validation_error', 'message': text}


def review_candidate_failure_detail(error, candidate, source, before):
    """Enrich legacy pending tasks on rendering, without rewriting their state."""
    if isinstance(candidate, dict) and str(error).startswith((
            'Meaning/completeness/logic checks cannot', 'Invalid review change evidence')):
        try:
            validate_review(candidate, source, before, candidate.get('translation'))
        except ReviewContractError as exc:
            return exc.detail
        except ValueError:
            pass
    return review_failure_detail(error)


def check_dimensions(checks, expected):
    if not isinstance(checks, dict) or set(checks) != set(expected):
        raise ReviewContractError('Structured review checks must cover: ' + ', '.join(expected),
            'invalid_check_dimensions', [{'path': 'checks', 'actual': list(checks) if isinstance(checks, dict) else checks,
                                          'expected': list(expected)}],
            'Provide every required check as an object with status and specific evidence; do not fabricate review results.')
    for name, item in checks.items():
        if not isinstance(item, dict) or item.get('status') not in ('pass', 'corrected', 'not_applicable') or not nonempty(item.get('evidence')):
            raise ReviewContractError('Each review check requires status and specific evidence: ' + name,
                'invalid_check_evidence', [{'path': 'checks.' + name, 'actual': item,
                    'expected': {'status': ['pass', 'corrected', 'not_applicable'], 'evidence': 'nonempty specific evidence'}}],
                'Independently check this dimension and record status plus specific evidence; '
                'nonempty review text requires accuracy/completeness/logic status pass or corrected.')


def validate_review(item, source, before, after):
    check_dimensions(item.get('checks'), REVIEW_CHECKS)
    skipped = [name for name in ('accuracy', 'completeness', 'logic')
               if source.strip() and item['checks'][name]['status'] == 'not_applicable']
    if skipped:
        raise ReviewContractError('Meaning/completeness/logic checks cannot be skipped for non-empty text',
            'required_dimension_not_applicable',
            [{'path': f'checks.{name}.status', 'actual': 'not_applicable', 'expected': ['pass', 'corrected']} for name in skipped],
            'Independently recheck each listed dimension and provide specific evidence. For a label without '
            'negation/conditions/numbers, check that the translation adds or changes no relation. '
            'Keep a correct translation unchanged; do not mechanically replace status or fabricate evidence.')
    excerpt = item.get('source_excerpt')
    if not isinstance(excerpt, str) or (source.strip() and not excerpt.strip()) or excerpt not in source:
        raise ValueError('Review source_excerpt must cite the assigned original text')
    changes = item.get('changes', [])
    if not isinstance(changes, list):
        raise ValueError('Review changes must be a list')
    if before != after and not changes:
        raise ValueError('Review correction requires before/after and an error category')
    for index, change in enumerate(changes):
        quote = change.get('source_excerpt') if isinstance(change, dict) else None
        valid_quote = isinstance(quote, str) and (not source.strip() or bool(quote.strip())) and quote in source
        if (not isinstance(change, dict) or change.get('before') != before or change.get('after') != after
                or change.get('category') not in REVIEW_CHECKS or change.get('severity') not in ('minor', 'major', 'critical')
                or not nonempty(change.get('reason')) or not valid_quote or before == after):
            expected = {'before': before, 'after': after}
            fields = [{'path': f'changes[{index}].{key}', 'actual': change.get(key), 'expected': value}
                      for key, value in expected.items() if isinstance(change, dict) and change.get(key) != value]
            if not valid_quote:
                fields.append({'path': f'changes[{index}].source_excerpt', 'actual': quote,
                               'expected': 'A continuous excerpt from this assigned source'})
            raise ReviewContractError('Invalid review change evidence', 'invalid_change_evidence', fields,
                'Use complete task translation for before and complete revised translation for after; '
                'each change source_excerpt must cite this assigned source; different changes may cite different excerpts. '
                'Use a valid category, severity and specific reason; unchanged translations require changes=[].')
    if before != after and not any(c['status'] == 'corrected' for c in item['checks'].values()):
        raise ValueError('Corrected translation must identify a corrected check')


def validate_category_paths(decisions):
    """Reject unsupported glossary categories at submission, not at freeze time."""
    from glossary_tool import TERM_CATEGORIES
    for edit in decisions.get('edits') or []:
        if not isinstance(edit, dict) or edit.get('table') != 'terms':
            continue
        patch = edit.get('patch')
        if isinstance(patch, dict) and 'category_path' in patch:
            value = patch['category_path']
            if value not in TERM_CATEGORIES:
                raise ValueError('terms:' + str(edit.get('index')) + ' category_path must be one of '
                                 + '/'.join(sorted(TERM_CATEGORIES)) + '; got ' + repr(value))
    for item in decisions.get('additions') or []:
        if not isinstance(item, dict) or item.get('table') != 'terms':
            continue
        row = item.get('row') if isinstance(item.get('row'), dict) else {}
        value = row.get('category_path')
        if value not in TERM_CATEGORIES:
            raise ValueError('terms addition category_path must be one of '
                             + '/'.join(sorted(TERM_CATEGORIES)) + '; got ' + repr(value))


def validate_glossary_reviews(decisions, payload):
    validate_category_paths(decisions)
    reviews = decisions.get('entry_reviews')
    refs = {e['ref']: e for e in payload['entries']}
    if (not isinstance(reviews, list) or any(not isinstance(r, dict) for r in reviews)
            or len(reviews) != len(refs) or {r.get('ref') for r in reviews} != set(refs)):
        raise ValueError('Glossary entry_reviews must cover each assigned ref exactly once')
    contexts = {r['ordinal']: r['source'] for r in payload['records']}
    for review in reviews:
        check_dimensions(review.get('checks'), GLOSSARY_CHECKS)
        rows = review.get('evidence_rows')
        excerpt = review.get('source_excerpt')
        entry = refs[review['ref']]['row']
        if (not isinstance(rows, list) or not rows or any(type(n) is not int or n not in entry.get('evidence_rows', []) for n in rows)
                or not nonempty(excerpt) or not any(quote_matches(excerpt, contexts.get(n, '')) for n in rows)
                or not nonempty(review.get('reason'))):
            available = sorted(set(entry.get('evidence_rows', [])).intersection(contexts))
            invalid = [n for n in rows if type(n) is not int or n not in available] if isinstance(rows, list) else rows
            matches = ([n for n in rows if type(n) is int and quote_matches(excerpt, contexts.get(n, ''))]
                       if isinstance(rows, list) else [])
            raise ValueError('Glossary review requires cited source context and specific reason; '
                f'ref={review["ref"]}; available_evidence_rows={available}; '
                f'invalid_or_unprovided_rows={invalid}; excerpt_matches_cited_rows={matches}; '
                f'reason_missing={not nonempty(review.get("reason"))}. '
                'source_excerpt must be one exact contiguous excerpt from a cited, provided source; '
                'do not join paraphrases or insert ellipses.')

    validate_glossary_applicability(decisions, payload)


def validate_glossary_applicability(decisions, payload):
    if payload.get('applicability_policy') != 1:
        return
    from workflow_term_scope import validate_applicability
    edits = {f'{e["table"]}:{e["index"]}': e for e in decisions.get('edits', [])}
    quarantined = {f'{e["table"]}:{e["index"]}' for e in decisions.get('quarantine', [])}
    for entry in payload['entries']:
        if entry['ref'] in quarantined:
            continue
        edit = edits.get(entry['ref'], {})
        if 'applicability' in edit.get('patch', {}) and not edit.get('evidence_rows'):
            raise ValueError('Applicability edit requires actual source evidence rows')
        row = dict(entry['row'], **edit.get('patch', {}))
        validate_applicability(row, required=True)
    for addition in decisions.get('additions', []):
        validate_applicability(addition['row'], required=True)


def risk_reasons(row):
    """Heuristic candidates, never a semantic pass/fail verdict."""
    text, metadata = row['source'], row.get('metadata', {})
    flags = []
    patterns = {
        'numbers': r'\d',
        'negation': r"\b(?:not|never|no|without|unless|cannot|can't|don't|doesn't|won't)\b",
        'conditions': r'\b(?:if|unless|only|until|before|after|must|either|except)\b',
        'relationships': r'\b(?:father|mother|brother|sister|son|daughter|husband|wife|master|servant)\b',
        'variables': r'\{[^{}]+\}|\[[^\[\]]+\]|%[sdif]|\$\w+',
    }
    for name, pattern in patterns.items():
        if re.search(pattern, text, re.I):
            flags.append(name)
    if len(text) >= 600:
        flags.append('long_text')
    if str(metadata.get('text_type', '')).casefold() in ('quest', 'objective', 'choice', 'ui', '任务', '任务目标', '选项'):
        flags.append('interaction')
    if text.strip() and len(text) <= 30 and not (metadata.get('scene') or metadata.get('speaker') or metadata.get('note')):
        flags.append('short_without_context')
    if row.get('exceptions') not in (None, '[]', []):
        flags.append('term_exception')
    return flags


def evenly(rows, count):
    if not rows or count <= 0:
        return []
    if len(rows) <= count:
        return rows
    return [rows[i * (len(rows) - 1) // max(1, count - 1)] for i in range(count)]


def validate_pilot_review(item, source, before, after, summary):
    check_dimensions(summary, REVIEW_CHECKS)
    if source.strip() and any(summary[k]['status'] == 'not_applicable' for k in ('accuracy', 'completeness', 'logic')):
        raise ValueError('Pilot batch summary must cover meaning, completeness and logic')
    if item.get('reviewed') is not True or item.get('verdict') not in ('pass', 'corrected'):
        raise ValueError('Every pilot ID requires an explicit reviewed verdict')
    if item['verdict'] == 'pass':
        if before != after or item.get('changes') or item.get('issues') or item.get('exceptions'):
            raise ValueError('Passing pilot records cannot hide corrections, warnings or exceptions')
    else:
        if not nonempty(item.get('reason')):
            raise ValueError('Pilot corrections/concerns need explicit evidence')
        validate_review(item, source, before, after)


class QualityMixin:
    @staticmethod
    def review_output_budget(config, stage, backend=None):
        limit = config.get('review_output_tokens', 16384)
        return max(1, limit * (100 - config.get('review_output_reserve_percent', 20)) // 100)

    @staticmethod
    def estimate_review_output(row, stage, config=None):
        """Planning estimate, not an exact tokenizer or a semantic evidence limit."""
        from translation_workflow import DEFAULT
        estimate = (config or {}).get('review_estimate', DEFAULT['review_estimate'])
        def tokens(text):
            text = str(text or '')
            ascii_chars = sum(ord(c) < 128 for c in text)
            divisor = estimate['ascii_chars_per_token']
            return (ascii_chars + divisor - 1) // divisor + (len(text) - ascii_chars) * estimate['non_ascii_tokens_per_char']
        source = tokens(row.get('source'))
        translation = tokens(row.get('translation')) or source
        # Full correction may repeat source excerpts, before/after and six checks.
        return estimate['full_base_tokens'] + source + estimate['translation_multiplier'] * translation + tokens(row.get('exceptions', ''))

    def review_batches(self, rows, config, stage, backend=None):
        limit = self.review_output_budget(config, stage, backend)
        batch, output, tokens = [], 0, 0
        cap = record_limit(config, stage)
        for row in rows:
            estimate = self.estimate_review_output(row, stage, config)
            if estimate > limit:
                raise ValueError(f'Review output budget too small for {row["id"]}: estimated {estimate} tokens, budget {limit}; increase output allowance or design an aligned split; no text truncated')
            size = record_tokens(row, stage)
            if batch and ((cap is not None and len(batch) >= cap) or output + estimate > limit or tokens + size > batch_limit(config, stage)):
                yield batch
                batch, output, tokens = [], 0, 0
            batch.append(row); output += estimate; tokens += size
        if batch:
            yield batch

    def pilot_review_batches(self, scope, eligible, config):
        return list(self.review_batches(eligible, config, 'pilot_review'))

    @staticmethod
    def pilot_exclusion_table(db):
        db.execute("CREATE TABLE IF NOT EXISTS pilot_attempt_exclusions (task_id TEXT, token TEXT, session_id TEXT, instance TEXT, reason TEXT, evidence TEXT, authorization TEXT, original_failure TEXT, created_at TEXT, PRIMARY KEY(task_id,token))")
        for operation in ('UPDATE', 'DELETE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS pilot_exclusions_no_{operation.lower()} BEFORE {operation} ON pilot_attempt_exclusions BEGIN SELECT RAISE(ABORT, 'Pilot exclusion ledger is append-only'); END")

    def pilot_usage(self, db):
        # Legacy policy boundary remains unchanged; revisions never reset usage.
        start = self.meta(db, 'pilot_budget_start')
        if start is None:
            legacy = 'pilot_call_limit' not in self.meta(db, 'config')
            start = db.execute('SELECT coalesce(max(rowid),0) FROM quality_attempts').fetchone()[0] if legacy else 0
            self.put(db, 'pilot_budget_start', start)
        self.pilot_exclusion_table(db)
        counts = db.execute('SELECT count(*) raw,count(e.token) exempt FROM quality_attempts a '
            'JOIN tasks t ON t.id=a.task_id LEFT JOIN pilot_attempt_exclusions e '
            'ON e.task_id=a.task_id AND e.token=a.token '
            'WHERE a.rowid>? AND t.stage IN ("pilot_translate","pilot_review")', (start,)).fetchone()
        return {'raw': counts['raw'], 'exempt': counts['exempt'], 'effective': counts['raw'] - counts['exempt']}

    def pilot_spent(self, db):
        return self.pilot_usage(db)['effective']

    def exclude_pilot_attempt(self, entry):
        """Register an explicit human-authorized program-error credit, retaining history."""
        from datetime import datetime, timezone
        required = ('task_id', 'token', 'session_id', 'instance', 'reason', 'authorization')
        if not isinstance(entry, dict) or any(not nonempty(entry.get(k)) for k in required):
            raise ValueError('Explicit task/token/session/instance, reason and human authorization required')
        if entry.get('classification') != 'program_error' or entry.get('human_authorized') is not True:
            raise ValueError('Only explicitly human-authorized program errors may be excluded')
        evidence = entry.get('evidence')
        if not isinstance(evidence, list) or not evidence:
            raise ValueError('Preserved original failure evidence required')
        verified = []
        for item in evidence:
            path = Path(item['path']).resolve()
            if not path.is_relative_to(self.root.resolve()) or not path.is_file():
                raise ValueError('Evidence must be an existing project TranslateFiles artifact')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            excerpt = item.get('excerpt')
            if digest != item.get('sha256') or not nonempty(excerpt) or excerpt not in path.read_text(encoding='utf-8'):
                raise ValueError('Evidence hash/excerpt mismatch')
            verified.append(dict(item, path=str(path)))
        with self.db() as db:
            if list((self.root / 'state').glob('*.lock')) or db.execute('SELECT 1 FROM tasks WHERE status="running"').fetchone() or db.execute('SELECT 1 FROM api_calls WHERE status="reserved"').fetchone():
                raise ValueError('Stop all in-flight work before registering a budget exclusion')
            attempt = db.execute('SELECT a.*,t.stage FROM quality_attempts a JOIN tasks t ON t.id=a.task_id WHERE a.task_id=? AND a.token=?', (entry['task_id'], entry['token'])).fetchone()
            run = db.execute('SELECT * FROM batch_runs WHERE id=?', (entry['session_id'],)).fetchone()
            if (not attempt or attempt['stage'] not in ('pilot_translate', 'pilot_review')
                    or attempt['instance'] != entry['instance'] or not run or run['task_id'] != entry['task_id']
                    or run['worker'] != attempt['instance'] or run['round'] < 1
                    or run['status'] not in ('needs_attention', 'repair_required', 'failed')):
                raise ValueError('Exclusion must identify the exact failed pilot repair attempt and real owner')
            # Batch lease token is intentionally distinct from repair attempt token.
            original = Path(run['result_file'])
            if not original.is_file() or not any(entry['session_id'] in x['excerpt'] for x in verified):
                raise ValueError('Retained result and session-specific original failure evidence required')
            self.pilot_exclusion_table(db)
            if db.execute('SELECT 1 FROM pilot_attempt_exclusions WHERE task_id=? AND token=?', (entry['task_id'], entry['token'])).fetchone():
                raise ValueError('Attempt already excluded; ledger cannot be overwritten')
            failure = {'batch_run': dict(run), 'attempt': dict(attempt), 'result_sha256': hashlib.sha256(original.read_bytes()).hexdigest()}
            created = datetime.now(timezone.utc).isoformat()
            db.execute('INSERT INTO pilot_attempt_exclusions VALUES (?,?,?,?,?,?,?,?,?)',
                (entry['task_id'], entry['token'], entry['session_id'], entry['instance'], entry['reason'],
                 json.dumps(verified, ensure_ascii=False), entry['authorization'], json.dumps(failure, ensure_ascii=False), created))
            return {'registered': True, 'task_id': entry['task_id'], 'token': entry['token'],
                    'session_id': entry['session_id'], 'created_at': created, 'usage': self.pilot_usage(db)}

    def pilot_plan(self):
        from translation_workflow import prompt
        with self.db() as db:
            config = self.config(db)
            rows = self.quality_rows(db)
            selected = self.pilot_ids(db, rows, config)
            scope = [r for r in rows if r['id'] in selected]
            approved = self.pilot_approved(db, config)
            untranslated = [] if approved else [r for r in scope if r['stage'] not in ('pilot_translate', 'pilot_review')]
            unreviewed = [] if approved else [r for r in scope if r['stage'] != 'pilot_review']
            # Active claims already consume pilot_spent. Estimate only future
            # claims, while keeping the accepted-record counts below unchanged.
            claimed = {'pilot_translate': set(), 'pilot_review': set()}
            for task in db.execute('SELECT id,stage,ids FROM tasks WHERE revision=? AND status="running" '
                                   'AND stage IN ("pilot_translate","pilot_review")', (self.meta(db, 'revision'),)):
                if db.execute('SELECT 1 FROM quality_attempts WHERE task_id=?', (task['id'],)).fetchone():
                    claimed[task['stage']].update(json.loads(task['ids']))
            future_translate = [r for r in untranslated if r['id'] not in claimed['pilot_translate']]
            future_review = [r for r in unreviewed if r['id'] not in claimed['pilot_review']]
            translate = sum(1 for batch in self.batches(future_translate, config, respect_groups=False, stage='pilot_translate'))
            review = 0  # Calibration is assessed by the main AI, with no independent API review.
            pending = db.execute('SELECT stage,payload FROM tasks WHERE revision=? AND status IN ("pending","failed") '
                                 'AND stage IN ("pilot_translate","pilot_review")', (self.meta(db, 'revision'),)).fetchall()
            translate = max(translate, sum(t['stage'] == 'pilot_translate' for t in pending))
            review = 0
            self.allocation_tables(db)
            maximum = db.execute('SELECT coalesce(max(max(a.input_tokens,a.compact_tokens)),0) '
                                 'FROM task_allocations a JOIN tasks t ON t.id=a.task_id '
                                 'WHERE t.revision=? AND t.status IN ("pending","failed") '
                                 'AND t.stage IN ("pilot_translate","pilot_review")',
                                 (self.meta(db, 'revision'),)).fetchone()[0]
            running = db.execute('SELECT count(*) FROM tasks WHERE status="running" AND stage IN ("pilot_translate","pilot_review")').fetchone()[0]
            usage = self.pilot_usage(db)
            spent = usage['effective']
            return {'sample_records': len(scope), 'translated_records': len(scope) - len(untranslated),
                    'reviewed_records': 0, 'translation_batches': translate,
                    'review_batches': review, 'executions_used': spent, 'executions_raw': usage['raw'],
                    'executions_exempt': usage['exempt'], 'executions_effective': spent, 'execution_limit': None,
                    'running_tasks': running, 'maximum_prepared_input_tokens': maximum,
                    'within_budget': maximum <= config.get('task_input_tokens', 16384),
                    'note': 'Random calibration sample; production translation batching and task retries apply. No independent pilot review or automatic quality repair loop. Main AI chooses accept, targeted retry, or stop.'}

    def reduce_pilot(self, count, reason):
        """Adopt a smaller calibration sample without discarding its accepted work."""
        from translation_workflow import DEFAULT, merge_config, write_json
        if type(count) is not int or not 1 <= count <= 30 or not nonempty(reason):
            raise ValueError('Reduced pilot requires 1..30 records and a reason')
        with self.db() as db:
            config = self.config(db)
            if not self.meta(db, 'paused') or db.execute('SELECT 1 FROM tasks WHERE status="running"').fetchone():
                raise ValueError('Pause and finish/recover all in-flight tasks before reducing pilot')
            if self.pilot_approved(db, config):
                raise ValueError('Pilot already accepted; do not reopen it merely to reduce cost')
            rows = self.quality_rows(db)
            original = self.pilot_ids(db, rows, config)
            pool = [r for r in rows if r['id'] in original]
            if count > len(pool):
                raise ValueError('reduce-pilot cannot expand the sample')
            complete = [r for r in pool if r['stage'] in ('pilot_translate', 'pilot_review')]
            candidates = complete if len(complete) >= count else pool
            self.put(db, 'pilot_selection', None)
            selected = self.pilot_ids(db, candidates, {'pilot_records': count, 'pilot_ordinals': []})
            prior = self.meta(db, 'pilot_prior', []) or []
            for row in prior:
                if row['id'] not in selected:
                    db.execute('UPDATE records SET stage=?,translation=?,exceptions=? WHERE id=?',
                               (row['stage'], row['translation'], row['exceptions'], row['id']))
            self.put(db, 'pilot_prior', [r for r in prior if r['id'] in selected] if prior else None)
            new = merge_config({**DEFAULT, **config}, {'pilot_records': count,
                               'pilot_ordinals': [r['ordinal'] for r in rows if r['id'] in selected],
                               'pilot_batch_count': None, 'pilot_call_limit': None})
            # Activate once for legacy work. Further scope/config changes preserve spent calls.
            self.pilot_spent(db)
            revision = self.meta(db, 'revision') + 1
            write_json(self.root / f'history/config_r{revision}.json', {'before': config, 'after': new, 'reason': reason})
            self.put(db, 'config', new); self.put(db, 'revision', revision)
            self.put(db, 'quality_approvals', {})
            db.execute('UPDATE tasks SET status="obsolete" WHERE stage IN ("pilot_translate","pilot_review") AND status!="done"')
            write_json(self.root / 'config/workflow.json', new)
            self.write_guide(new, Path(self.meta(db, 'source_path')).name)
            reused = sum(r['id'] in selected for r in complete)
            self.event(db, 'reduce_pilot', {'reason': reason, 'old_count': len(original), 'new_count': count, 'reused': reused})
            return {'sample_records': count, 'reused_translations': reused, 'revision': revision,
                    'executions_used': self.pilot_spent(db), 'execution_limit': None}
    def restore_pilot_baseline(self, db):
        for row in self.meta(db, 'pilot_prior', []) or []:
            db.execute('UPDATE records SET stage=?,translation=?,exceptions=? WHERE id=?',
                       (row['stage'], row['translation'], row['exceptions'], row['id']))
        self.put(db, 'pilot_prior', None)

    def quality_rows(self, db):
        contexts = self.meta(db, 'contexts', {})
        return [{**dict(r), 'metadata': contexts.get(str(r['ordinal']), {})}
                for r in db.execute('SELECT * FROM records ORDER BY ordinal')]

    def pilot_ids(self, db, records, config):
        selected = self.meta(db, 'pilot_selection')
        if selected is not None:
            return set(selected)
        ordinals = config['pilot_ordinals']
        if ordinals:
            if any(n > len(records) for n in ordinals):
                raise ValueError('pilot_ordinals exceeds source record count')
            picks = [r for r in records if r['ordinal'] in ordinals]
        elif len(records) <= config['pilot_records']:
            picks = records
        else:
            picks = random.sample(records, config['pilot_records'])
        selected = [r['id'] for r in picks]
        self.put(db, 'pilot_selection', selected)
        return set(selected)

    def pilot_key(self, db, config):
        keys = ('style', 'game_background', 'source_language', 'target_language', 'case_sensitive',
                'whole_word', 'protect_named_curly', 'placeholder_family_overrides', 'exclusions',
                'pilot_records', 'pilot_ordinals', 'quality_version')
        return signature({'source': self.meta(db, 'source_hash'), 'glossary': self.meta(db, 'glossary'),
                          'rules': {k: config[k] for k in keys}})

    def pilot_approved(self, db, config):
        receipt = self.meta(db, 'quality_approvals', {}).get('pilot', {})
        if receipt.get('pilot_key') != self.pilot_key(db, config):
            return False
        path = self.root / f'reports/accepted/pilot_{receipt["report_hash"][:16]}/report.json'
        from translation_workflow import read_json
        if not path.is_file():
            return False
        report = read_json(path)
        stored = report.pop('report_hash', None)
        return stored == receipt['report_hash'] == signature(report)

    def preserve_quality_scope(self, db, old_config, config, affected):
        """Carry unchanged checks; reopen only records affected by a rule revision."""
        affected = set(affected)
        self.put(db, 'quality_policy_key', self.meta(db, 'quality_policy_key', self.pilot_key(db, old_config)))
        approvals = self.meta(db, 'quality_approvals', {})
        checkpoints = self.meta(db, 'quality_checkpoints', {})
        from translation_workflow import read_json, write_json
        for kind, receipt in approvals.items():
            archived = self.root / f'reports/accepted/{kind}_{receipt["report_hash"][:16]}/report.json'
            if archived.is_file():
                report = read_json(archived)
                legacy_checks = {item['id']: signature({'policy': report['pilot_key'], 'item': item})
                                 for item in report.get('records_to_check', []) + report.get('consistency', []) + report.get('glossary_checks', [])}
                saved = checkpoints.setdefault(kind, {})
                saved.update(report.get('reused_decisions', {}))
                for entry in receipt.get('decisions', {}).get('decisions', []):
                    check_hash = report.get('check_signatures', legacy_checks).get(entry['id'])
                    if check_hash:
                        saved[entry['id']] = {'signature': check_hash, 'report_hash': receipt['report_hash'], 'decision': entry}
        related = set(affected)
        rows = self.quality_rows(db)
        for row in rows:
            if row['id'] in affected:
                related.add('C:' + signature(row['source'])[:16])
                if row['metadata'].get('speaker'):
                    related.add('S:' + signature(str(row['metadata']['speaker']))[:16])
        for saved in checkpoints.values():
            for record_id in related:
                saved.pop(record_id, None)
        self.put(db, 'quality_checkpoints', checkpoints)
        prior = self.meta(db, 'pilot_prior')
        if prior:
            for row in prior:
                if row['id'] in affected:
                    row['stage'] = 'source' if row['stage'] == 'source' else 'translate'
                    row['exceptions'] = '[]'
            self.put(db, 'pilot_prior', prior)
        pilot = approvals.get('pilot')
        sample = self.pilot_ids(db, rows, config)
        if pilot and sample.intersection(affected):
            # An accepted pilot restored the production baseline. Recover its reviewed
            # translations from provenance, keeping the baseline for later restoration.
            if pilot.get('reviewer') == 'main':
                archived = self.root / f'reports/accepted/pilot_{pilot["report_hash"][:16]}/report.json'
                reviews = {r['id']: r for r in read_json(archived)['records']}
            else:
                reviews = self.latest_reviews(db, 'pilot')
            if any(record_id not in reviews for record_id in sample):
                raise ValueError('Cannot reuse accepted pilot without its saved translations')
            self.put(db, 'pilot_prior', [{k: row[k] for k in ('id', 'stage', 'translation', 'exceptions')}
                                       for row in rows if row['id'] in sample])
            for record_id in sample:
                review = reviews[record_id]
                db.execute('UPDATE records SET translation=?,stage=?,exceptions=? WHERE id=?',
                           (review['translation'], 'pilot_translate',
                            json.dumps([] if record_id in affected else review.get('exceptions', [])), record_id))
            approvals.pop('pilot', None)
        elif pilot:
            pilot['carried_from_pilot_key'] = pilot['pilot_key']
            pilot['pilot_key'] = self.pilot_key(db, config)
        final = approvals.get('final')
        if final and not affected:
            report = self.build_quality_report(db, 'final', config)
            final['carried_from_report_hash'] = final['report_hash']
            final['report_hash'] = report['report_hash']
            final['pilot_key'] = self.pilot_key(db, config)
            folder = self.root / f'reports/accepted/final_{report["report_hash"][:16]}'
            write_json(folder / 'report.json', report)
            write_json(folder / 'sol_decisions.json', {**final['decisions'], 'carried_from_report_hash': final['carried_from_report_hash']})
        else:
            approvals.pop('final', None)
        self.put(db, 'quality_approvals', approvals)

    def independent_worker(self, db, task, instance):
        stage = task['stage']
        preceding = {'glossary_review': ('extract',), 'pilot_review': ('pilot_translate',),
                     'review': ('translate', 'pilot_translate'),
                     'final_review': ('polish', 'translate', 'pilot_translate')}.get(stage)
        if not preceding:
            return True
        ids = set(json.loads(task['ids']))
        if stage == 'glossary_review':
            payload = json.loads(task['payload'])
            ordinals = {n for e in payload.get('entries', []) for n in e['row'].get('evidence_rows', [])}
            # A glossary entry normally cites only a few source rows. Avoid a
            # full-corpus scan for every entry while preserving exact ID scope.
            ordered = sorted(ordinals)
            for start in range(0, len(ordered), 800):
                cited = ordered[start:start + 800]
                ids.update(r['id'] for r in db.execute(
                    'SELECT id FROM records WHERE ordinal IN (' + ','.join('?' for _ in cited) + ')', cited))
        authored = db.execute('SELECT record_id,stage FROM quality_authors WHERE instance=?', (instance,)).fetchall()
        return not any(r['record_id'] in ids and r['stage'] in preceding for r in authored)

    def latest_reviews(self, db, kind):
        reviews = {}
        # A downstream batch may contain both repaired and unaffected records.
        # Retain completed evidence for untouched records even when that task is obsolete.
        # Submission order, not task creation order, makes a reopened task supersede old evidence.
        submitted = {}
        for event in db.execute('SELECT id,detail FROM events WHERE kind="submit" ORDER BY id'):
            submitted[json.loads(event['detail'])['task']] = event['id']
        tasks = sorted(db.execute('SELECT * FROM tasks WHERE status IN ("done","obsolete") AND result IS NOT NULL '
                                  'AND stage IN ("pilot_review","review","final_review")').fetchall(),
                       key=lambda t: submitted.get(t['id'], 0))
        batch_sources = {}
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='batch_items'").fetchone():
            batch_sources = {(r['task_id'], r['token'], r['record_id']): r['instance'] for r in db.execute('SELECT task_id,token,record_id,instance FROM batch_items WHERE valid=1')}
        for task in tasks:
            if (kind == 'pilot') != (task['stage'] == 'pilot_review'):
                continue
            payload = json.loads(task['payload'])
            owner = db.execute('SELECT instance FROM quality_attempts WHERE task_id=? AND token=?', (task['id'], task['lease_token'])).fetchone()
            originals = {r['id']: r for r in payload['records']}
            result = json.loads(task['result'])
            for item in result['records']:
                reviews[item['id']] = {'task_id': task['id'], 'instance': batch_sources.get((task['id'], task['lease_token'], item['id']), owner['instance'] if owner else None),
                                      'stage': task['stage'], 'before': originals[item['id']]['translation'],
                                      'translation': item.get('translation', originals[item['id']]['translation']),
                                      'batch_summary': result.get('review_summaries', {}).get(item['id'], result.get('review_summary')), **item}
        return reviews

    def build_quality_report(self, db, kind, config):
        if kind == 'pilot':
            return self.build_pilot_report(db, config)
        if kind != 'final':
            raise ValueError('Quality report kind must be pilot or final')
        self.glossary(db)
        all_rows = self.quality_rows(db)
        rows = all_rows
        required_stage = 'final_review' if config['polish'] else 'review'
        self.require_review_round_complete(db, required_stage)
        if any(r['stage'] != required_stage for r in rows):
            raise ValueError('Complete the required semantic review before quality report: ' + required_stage)
        if db.execute('SELECT 1 FROM tasks WHERE revision=? AND status IN ("running","pending","failed")', (self.meta(db, 'revision'),)).fetchone():
            raise ValueError('Finish all current tasks before Sol review')
        reviews = self.latest_reviews(db, kind)
        risks, ordinary = [], []
        for row in rows:
            review = reviews.get(row['id'])
            if not review or not review['instance'] or review['translation'] != row['translation']:
                raise ValueError('Missing current review provenance: ' + row['id'])
            proof = self.review_proof_key(review, row['source'], review['before'], row['translation'])
            if not db.execute('SELECT 1 FROM review_proof_checks WHERE signature=?', (proof,)).fetchone():
                validate_review(review, row['source'], review['before'], row['translation'])
                db.execute('INSERT OR IGNORE INTO review_proof_checks VALUES (?)', (proof,))
            reasons = risk_reasons(row)
            if review.get('changes'):
                reasons.append('review_correction')
            if review.get('issues'):
                reasons.append('review_warning')
            record = {'id': row['id'], 'ordinal': row['ordinal'], 'source': row['source'],
                      'translation': row['translation'], 'metadata': row['metadata'],
                      'risk_reasons': reasons, 'review': {k: v for k, v in review.items() if k != 'batch_summary'}}
            (risks if reasons else ordinary).append(record)
        # Ordinary errors are handled by independent review. Only unresolved
        # semantic issues enter the final Sol dispute report.
        known = self.meta(db, 'sol_pending_findings', {})
        selected = [r for r in risks if r['review'].get('issues') and r['id'] not in known]
        consistency, glossary_checks = [], []
        items = selected
        glossary_info = self.meta(db, 'glossary')
        key = self.meta(db, 'quality_policy_key', self.pilot_key(db, config))
        checkpoints = self.meta(db, 'quality_checkpoints', {}).get(kind, {})
        signatures = {item['id']: signature({'policy': key, 'item': item}) for item in items}
        reused = {item['id']: checkpoints[item['id']] for item in items
                  if checkpoints.get(item['id'], {}).get('signature') == signatures[item['id']]}
        required = [item['id'] for item in items if item['id'] not in reused]
        report = {'schema': 2, 'kind': kind, 'pilot_key': self.pilot_key(db, config),
                  'source_sha256': self.meta(db, 'source_hash'), 'glossary': glossary_info,
                  'snapshot_hash': signature({'rows': rows, 'reviews': {r['id']: reviews[r['id']] for r in rows},
                                              'polish': config['polish']}),
                  'coverage': {'records': len(rows), 'text_types': dict(Counter(str(r['metadata'].get('text_type', 'unknown')) for r in rows)),
                               'missing_context': sum(not r['metadata'] for r in rows),
                               'risk_records': len(risks), 'ordinary_sample': 0,
                               'sol_records': len(selected)},
                  'risk_detection': 'Heuristic candidates plus reviewer findings; absence of flags is not proof of correctness.',
                  'records_to_check': [r for r in selected if r['id'] not in reused],
                  'consistency': [r for r in consistency if r['id'] not in reused],
                  'glossary_checks': [r for r in glossary_checks if r['id'] not in reused],
                  'pilot_batch_summaries': {},
                  'check_signatures': signatures, 'reused_decisions': reused,
                  'required_decisions': required}
        if kind == 'final':
            report['sol_scope_policy'] = SOL_SCOPE_POLICY
            report['carried_findings'] = self.meta(db, 'sol_pending_findings', {})
            report['selection_explanation'] = ('Only explicit unresolved reviewer issues need Sol adjudication. '
                'Risk flags, corrections, ordinary samples, duplicate-source groups and speaker groups do not trigger Sol. '
                'Known Sol repair findings are carried to standard repair without re-reading; exhausted or regressing '
                'repairs use the existing targeted Sol escalation route.')
        report['report_hash'] = signature(report)
        return report

    def checkpoint_quality(self, kind, decisions):
        """Record Sol's passed checks before repair without approving the whole stage."""
        if kind == 'pilot':
            raise ValueError('Pilot uses an overall main assessment; use pilot-decide')
        with self.db() as db:
            if kind == 'final':
                self.sol_tables(db)
                if db.execute('SELECT 1 FROM sol_review_rounds WHERE status="open"').fetchone():
                    return self.record_sol_checks(db, decisions)
            report = self.build_quality_report(db, kind, self.config(db))
            entries = decisions.get('decisions', [])
            if (decisions.get('report_hash') != report['report_hash'] or decisions.get('reviewer') != 'sol'
                    or not nonempty(decisions.get('summary')) or not isinstance(entries, list) or not entries
                    or any(not isinstance(e, dict) for e in entries)
                    or len({e.get('id') for e in entries}) != len(entries)
                    or any(e.get('id') not in report['required_decisions']
                           or e.get('disposition') not in ('pass', 'contextual') or not nonempty(e.get('reason')) for e in entries)):
                raise ValueError('Checkpoint requires explicit Sol passed decisions bound to the current report')
            checkpoints = self.meta(db, 'quality_checkpoints', {})
            saved = checkpoints.setdefault(kind, {})
            for entry in entries:
                saved[entry['id']] = {'signature': report['check_signatures'][entry['id']],
                                      'report_hash': report['report_hash'], 'decision': entry}
            self.put(db, 'quality_checkpoints', checkpoints)
            self.event(db, 'checkpoint_quality', {'kind': kind, 'decisions': entries, 'report_hash': report['report_hash']})
            return {'status': 'checks_saved', 'saved_checks': len(entries), 'stage_approved': False}

    def quality_report(self, kind):
        if kind == 'pilot':
            return self.pilot_report()
        from translation_workflow import read_json, write_json
        with self.db() as db:
            config = self.config(db)
            if kind == 'final':
                report, round_id = self.open_sol_round(db, config)
            else:
                report, round_id = self.build_quality_report(db, kind, config), None
            saved = {}
            next_input = None
            inspection_manifest = None
            if round_id is not None:
                saved = json.loads(db.execute('SELECT decisions FROM sol_review_rounds WHERE id=?', (round_id,)).fetchone()[0])
                # A compact view of the fixed round scope; its canonical complete
                # report and hash remain archived until the whole round closes.
                report = {**report, 'round_scope': report['required_decisions'],
                          'required_decisions': [i for i in report['required_decisions'] if i not in saved]}
                for key in ('records_to_check', 'consistency', 'glossary_checks'):
                    report[key] = [i for i in report[key] if i['id'] not in saved]
                inspection_manifest = self.root / f'reports/sol_rounds/round_{round_id:05d}.inputs.json'
                manifest = read_json(inspection_manifest)
                for batch in manifest:
                    todo = set(batch['check_ids']) - set(saved)
                    if todo:
                        packet = read_json(batch['file'])
                        packet['checks'] = [i for i in packet['checks'] if i['id'] in todo]
                        if packet.get('output_template'):
                            packet['output_template']['decisions'] = [i for i in packet['output_template']['decisions'] if i['id'] in todo]
                        next_input = self.root / f'reports/sol_rounds/round_{round_id:05d}.next.json'
                        write_json(next_input, packet)
                        break
            path = self.root / f'reports/{kind}_quality_review.json'
            write_json(path, report)
            write_json(self.root / f'reports/{kind}_sol_decisions.template.json', {
                'report_hash': report['report_hash'], 'reviewer': 'sol', 'summary': '',
                'decisions': [{'id': record_id, 'disposition': 'pending', 'reason': ''} for record_id in report['required_decisions']]})
            return {'report_file': str(path), 'report_hash': report['report_hash'], 'coverage': report['coverage'], 'sol_round': round_id,
                    'status': 'already_approved' if kind == 'final' and round_id is None else 'inspection_open',
                    'remaining_checks': 0 if kind == 'final' and round_id is None else len(report['required_decisions']),
                    'carried_finding_records': len(report.get('carried_findings', {})),
                    'next_action': 'sol-round-finish' if kind == 'final' and round_id is not None and not report['required_decisions'] else None,
                    'next_input_file': str(next_input) if next_input else None,
                    'inspection_manifest': str(inspection_manifest) if inspection_manifest else None}

    def approve_quality(self, kind, decisions):
        if kind == 'pilot':
            return self.pilot_decide(decisions)
        from translation_workflow import write_json
        with self.db() as db:
            config = self.config(db)
            report = self.build_quality_report(db, kind, config)
            if kind == 'final':
                self.sol_tables(db)
                active = db.execute('SELECT watch,report,decisions FROM sol_review_rounds WHERE status="open" ORDER BY id DESC LIMIT 1').fetchone()
                if active:
                    if active['watch'] != self.sol_watch(db) or json.loads(active['report'])['report_hash'] != report['report_hash']:
                        raise ValueError('Stale Sol round; request the current quality-report before approval')
                    combined = json.loads(active['decisions'])
                    supplied = decisions.get('decisions', [])
                    if isinstance(supplied, list) and all(isinstance(e, dict) and isinstance(e.get('id'), str) for e in supplied):
                        combined.update({e['id']: e for e in supplied})
                        if len({e['id'] for e in supplied}) == len(supplied):
                            decisions = {**decisions, 'decisions': list(combined.values())}
            entries = decisions.get('decisions', [])
            if (decisions.get('report_hash') != report['report_hash'] or decisions.get('reviewer') != 'sol'
                    or not nonempty(decisions.get('summary')) or not isinstance(entries, list)
                    or any(not isinstance(e, dict) for e in entries)
                    or len(entries) != len(report['required_decisions'])
                    or {e.get('id') for e in entries} != set(report['required_decisions'])):
                raise ValueError('Sol decisions must bind the current report and cover every requested check exactly once')
            if any(e.get('disposition') not in ('pass', 'contextual') or not nonempty(e.get('reason')) for e in entries):
                raise ValueError('Unresolved Sol checks; return defective tasks for revision before approval')
            if kind == 'final':
                self.sol_tables(db)
                for active in db.execute('SELECT decisions FROM sol_review_rounds WHERE status="open"'):
                    if any(e['disposition'] == 'repair' for e in json.loads(active['decisions']).values()):
                        raise ValueError('Unresolved Sol round findings; complete sol-round-finish before approval')
            result = self.accept_quality_in_transaction(db, kind, report, decisions)
            if kind == 'final':
                db.execute('UPDATE sol_review_rounds SET status="finished",result=? WHERE status="open"', (json.dumps(result),))
            return result

    def accept_quality_in_transaction(self, db, kind, report, decisions):
        from translation_workflow import write_json
        if kind == 'final' and report.get('carried_findings'):
            raise ValueError('Unresolved carried Sol findings; use sol-round-finish to dispatch targeted repairs')
        receipt = {'report_hash': report['report_hash'], 'snapshot_hash': report['snapshot_hash'],
                   'pilot_key': report['pilot_key'], 'reviewer': decisions.get('reviewer', 'sol'), 'decisions': decisions}
        approvals = self.meta(db, 'quality_approvals', {}); approvals[kind] = receipt
        self.put(db, 'quality_approvals', approvals)
        folder = self.root / f'reports/accepted/{kind}_{report["report_hash"][:16]}'
        write_json(folder / 'report.json', report)
        write_json(folder / ('main_assessment.json' if kind == 'pilot' else 'sol_decisions.json'), decisions)
        if kind == 'pilot':
            self.restore_pilot_baseline(db)
        self.event(db, 'approve_quality', {'kind': kind, 'report_hash': report['report_hash']})
        return {'status': 'approved', 'kind': kind, 'report_hash': report['report_hash']}

    def require_final_approval(self, db, config):
        if not self.pilot_approved(db, config):
            raise ValueError('Main pilot approval required')
        report = self.build_quality_report(db, 'final', config)
        receipt = self.meta(db, 'quality_approvals', {}).get('final', {})
        if receipt.get('report_hash') != report['report_hash']:
            raise ValueError('Current final quality closure required before export; unresolved disputes/findings cannot be skipped')
        return {'report_hash': receipt['report_hash'], 'reviewer': receipt.get('reviewer', 'sol')}

    def reopen_body(self, task_id, reason, record_ids=None):
        """Return a rejected batch to a subagent, preserving attempt budgets and locks."""
        with self.db() as db:
            config = self.config(db)
            task = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if task and task['stage'] == 'pilot_review':
                raise ValueError('Pilot independent review retired; use pilot-retry for calibration')
            if not nonempty(reason) or not task or task['status'] != 'done' or task['stage'] not in ('pilot_review', 'review', 'final_review') or task['revision'] != self.meta(db, 'revision'):
                raise ValueError('Only completed current body review tasks can be reopened with reason')
            self.require_review_round_complete(db, task['stage'])
            if task['stage'] != 'pilot_review':
                self.guard_sol_dispatch(db)
            if db.execute('SELECT 1 FROM tasks WHERE status="running"').fetchone():
                raise ValueError('Finish/recover in-flight tasks before reopening a review')
            if task['stage'] == 'pilot_review' and self.pilot_approved(db, config):
                raise ValueError('Accepted pilot is immutable; revise configuration/glossary and run a new pilot')
            original_ids = set(json.loads(task['ids']))
            ids = original_ids if record_ids is None else set(record_ids)
            if not ids or not ids.issubset(original_ids) or (record_ids is not None and len(ids) != len(record_ids)):
                raise ValueError('Repair IDs must be a nonempty unique subset of the assigned records')
            # Later stage tasks touching these records must not override the repair.
            order = {'pilot_review': 0, 'review': 1, 'polish': 2, 'final_review': 3}
            for other in db.execute('SELECT * FROM tasks WHERE revision=?', (task['revision'],)).fetchall():
                if other['id'] != task_id and order.get(other['stage'], -1) > order[task['stage']] and ids.intersection(json.loads(other['ids'])):
                    db.execute('UPDATE tasks SET status="obsolete" WHERE id=?', (other['id'],))
            tasks, blocked = self.plan_review_repairs(db, config, task['stage'], {i: reason for i in ids}, 'reopen-body')
            self.event(db, 'reopen_body', {'repair_tasks': tasks, 'record_ids': sorted(ids), 'reason': reason})
            return {'task_id': tasks[0] if tasks else None, 'repair_tasks': tasks, 'needs_attention_ids': blocked,
                    'repair_records': len(ids) - len(blocked), 'preserved_records': len(original_ids - ids)}

    def reopen_body_ids(self, reason, record_ids):
        """Reopen an explicit, cross-batch set after the prior review round is complete."""
        with self.db() as db:
            config = self.config(db)
            if not nonempty(reason) or not isinstance(record_ids, list) or not record_ids:
                raise ValueError('A reason and explicit review IDs are required')
            ids = list(record_ids)
            if any(not isinstance(record_id, str) or not record_id for record_id in ids) or len(set(ids)) != len(ids):
                raise ValueError('Review IDs must be unique non-empty strings')
            rows = {row['id']: row for row in db.execute(
                'SELECT id,stage FROM records WHERE id IN (' + ','.join('?' for _ in ids) + ')', ids)}
            if set(rows) != set(ids):
                raise ValueError('Unknown review ID')
            stages = {row['stage'] for row in rows.values()}
            if len(stages) != 1 or not stages.issubset({'pilot_review', 'review'}):
                raise ValueError('Only records with completed review in the same phase can be reopened')
            stage = next(iter(stages))
            if stage == 'pilot_review':
                raise ValueError('Pilot independent review retired; use pilot-retry for calibration')
            if stage == 'pilot_review' and self.pilot_approved(db, config):
                raise ValueError('Accepted pilot is immutable; revise configuration/glossary and run a new pilot')
            if db.execute('SELECT 1 FROM tasks WHERE revision=? AND status="running"',
                          (self.meta(db, 'revision'),)).fetchone():
                raise ValueError('Finish/recover in-flight tasks before reopening a review')
            self.require_review_round_complete(db, stage)
            if stage != 'pilot_review':
                self.guard_sol_dispatch(db)
            tasks, blocked = self.plan_review_repairs(
                db, config, stage, {record_id: reason for record_id in ids}, 'reopen-body')
            self.event(db, 'reopen_body_ids', {'repair_tasks': tasks, 'record_ids': sorted(ids), 'reason': reason})
            return {'repair_tasks': tasks, 'repair_records': len(ids) - len(blocked),
                    'needs_attention_ids': blocked,
                    'preserved_records': db.execute('SELECT count(*) FROM records').fetchone()[0] - len(ids)}

    def write_game_check_template(self, export):
        from translation_workflow import write_json
        write_json(self.root / 'reports/in_game_check.template.json', {
            'translation_sha256': export['translation_sha256'], 'game_version': '', 'platform': '',
            'payload_files': [], 'evidence_files': [],
            'checks': [{'category': category, 'status': 'pending', 'scene': '', 'notes': ''}
                       for category in ('fonts', 'layout', 'ui', 'dialogue', 'quest')]})

    def checked_files(self, files):
        if not isinstance(files, list) or not files:
            raise ValueError('At least one payload/evidence file is required')
        checked = []
        for entry in files:
            if not isinstance(entry, dict) or not nonempty(entry.get('path')):
                raise ValueError('File evidence requires path and sha256')
            relative = Path(entry['path'])
            path = (self.project / relative).resolve()
            if relative.is_absolute() or '..' in relative.parts or (relative.parts and relative.parts[0].casefold() == 'game') or not path.is_relative_to(self.project) or not path.is_file():
                raise ValueError('Payload/evidence must be saved inside the localization project, outside Game links')
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if entry.get('sha256') != actual:
                raise ValueError('Payload/evidence file hash mismatch')
            record = {'path': relative.as_posix(), 'sha256': actual}
            if 'game_path' in entry:
                destination = PurePosixPath(str(entry['game_path']).replace('\\', '/'))
                if destination.is_absolute() or '..' in destination.parts or ':' in str(destination) or str(destination) in ('', '.'):
                    raise ValueError('game_path must be a safe game-root relative destination')
                record['game_path'] = str(destination)
            checked.append(record)
        return checked

    def record_game_check(self, report):
        from translation_workflow import digest, write_json
        with self.db() as db:
            config = self.config(db)
            self.require_final_approval(db, config)
            export = self.meta(db, 'last_export')
            if not export or report.get('translation_sha256') != export['translation_sha256'] or digest(export['path']) != export['translation_sha256']:
                raise ValueError('Game check must bind the current exported translation')
            if not nonempty(report.get('game_version')) or not nonempty(report.get('platform')):
                raise ValueError('Actual tested game version and platform required')
            checks = report.get('checks', [])
            expected = {'fonts', 'layout', 'ui', 'dialogue', 'quest'}
            if (not isinstance(checks, list) or any(not isinstance(c, dict) for c in checks)
                    or len(checks) != len(expected) or {c.get('category') for c in checks} != expected):
                raise ValueError('Game checks must cover fonts, layout, ui, dialogue and quest')
            for check in checks:
                if (check.get('status') not in ('pass', 'not_applicable') or not nonempty(check.get('notes'))
                        or (check['status'] == 'pass' and not nonempty(check.get('scene')))
                        or (check['category'] in ('fonts', 'layout') and check['status'] != 'pass')):
                    raise ValueError('Unverified/failed game checks cannot be recorded as passed')
            report = {**report, 'payload_files': self.checked_files(report.get('payload_files')),
                      'evidence_files': self.checked_files(report.get('evidence_files')),
                      'quality_report_hash': export['quality_review']['report_hash'], 'status': 'passed'}
            if any(not nonempty(e.get('game_path')) for e in report['payload_files']):
                raise ValueError('Every tested payload file requires its game_path installation destination')
            if len({e['game_path'] for e in report['payload_files']}) != len(report['payload_files']):
                raise ValueError('Duplicate tested payload destinations')
            write_json(self.root / 'reports/in_game_check.json', report)
            self.put(db, 'in_game_check', report)
            self.event(db, 'record_game_check', {'translation_sha256': report['translation_sha256']})
            return {'status': 'passed', 'report_file': str(self.root / 'reports/in_game_check.json')}

    def release_check(self):
        from translation_workflow import digest
        with self.db() as db:
            config = self.config(db)
            self.require_final_approval(db, config)
            export, check = self.meta(db, 'last_export'), self.meta(db, 'in_game_check')
            if (not export or not check or check.get('status') != 'passed'
                    or check['translation_sha256'] != export['translation_sha256']
                    or check['quality_report_hash'] != export['quality_review']['report_hash']
                    or digest(export['path']) != check['translation_sha256']):
                raise ValueError('Current in-game validation required before release')
            self.checked_files(check['payload_files']); self.checked_files(check['evidence_files'])
            return {'status': 'passed', 'game_version': check['game_version'], 'platform': check['platform'],
                    'payload_files': check['payload_files']}
