"""One-off, source-bound incremental repair for this game's v1.3 feedback.

Never changes the shared workflow or the installed game. Outputs a candidate
CSV only after term review, affected-ID translation and independent review.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
import copy
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import threading
import time
import uuid

PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[1]
sys.path.insert(0, str(REPO / 'Tools/localization'))
import translation_workflow as w
import ainiee_bridge as bridge
import glossary_tool
from glossary_corpus_evidence import attach_corpus_evidence
from glossary_merge import review_evidence_rows
from workflow_quality import validate_glossary_reviews, validate_review
from workflow_task_contract import api_id_transport, canonical_api_result, canonical_api_partial_result, render_protocol_input
from workflow_tokens import count_tokens
from workflow_term_policy import validate_term_policy, hidden_marker_wrapper_issues
from workflow_api_budget import service_failure, connection_retry_delay, budget_requests
from workflow_format_normalize import normalize_body_item

WORK = PROJECT / 'TranslateFiles/incremental_repair_20261024'
TABLES = ('characters', 'terms', 'non_translate')
CASE4 = {4147: 'abbc502838', 4257: '58abdf6a8a'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_column(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    if any(len(row) != 1 for row in rows):
        raise ValueError('Single-column CSV required')
    return [row[0] for row in rows]


def effective_term(row, table, config):
    """Ignore newly added labels/reasons that do not change translation policy."""
    scope = row.get('applicability') or {}
    return {'source': row['source'], 'translation': row.get('recommended_translation'),
            'table': 'protected' if table == 'non_translate' else 'translated',
            'enforcement': row.get('enforcement', 'required'),
            'scope': {'mode': scope.get('mode', 'text'),
                      'case_sensitive': scope.get('case_sensitive', config['case_sensitive']),
                      'prefix': scope.get('prefix', '') if scope.get('mode') == 'literal_context' else '',
                      'suffix': scope.get('suffix', '') if scope.get('mode') == 'literal_context' else ''}}


def term_changes(old, new, config):
    def inventory(g):
        result = {}
        for table in TABLES:
            for row in g[table]:
                key = (table, row['source'])
                if key in result:
                    raise ValueError('Duplicate term identity')
                result[key] = row
        return result
    a, b = inventory(old), inventory(new)
    changes, annotation_only = [], []
    for key in sorted(a.keys() | b.keys()):
        table, source = key
        before, after = a.get(key), b.get(key)
        old_policy = effective_term(before, table, config) if before else None
        new_policy = effective_term(after, table, config) if after else None
        if old_policy != new_policy:
            changes.append({'table': table, 'source': source, 'before': old_policy, 'after': new_policy})
        elif before != after:
            annotation_only.append({'table': table, 'source': source})
    return changes, annotation_only


def matched_meaning(matches):
    # Actual matched surface and naming/enforcement, not audit notes or ref indices.
    return sorted((m['src'], m['dst'], m.get('enforcement', 'required')) for m in matches)


def comparison_glossaries(old, new):
    """Unchanged keep-original rows cannot change a term-policy comparison.

    The shared matcher appends these independently after overlap resolution.
    Keep real snapshots/protection rules intact; omit only this identical suffix
    from the two local comparison views.
    """
    if old['non_translate'] != new['non_translate']:
        return old, new
    return ({**old, 'non_translate': []}, {**new, 'non_translate': []})


def policy_change_affects_record(before, after, exceptions):
    """A removed constraint already exempted in this approved row changes nothing.

    Do not hide a still-matching revised term or newly exposed nested name.
    Reasons are inherited source-bound evidence, never generated here.
    """
    if isinstance(exceptions, str):
        exceptions = json.loads(exceptions)
    removed_exempt = {e['source'].casefold() for e in exceptions
                      if isinstance(e, dict) and isinstance(e.get('source'), str) and e.get('reason')}
    removed_exempt.difference_update(m['src'].casefold() for m in after)
    active_before = [m for m in before if m['src'].casefold() not in removed_exempt]
    return matched_meaning(active_before) != matched_meaning(after)


def repair_hidden_wrappers(source, translation):
    proposed = translation
    for token in ('{Female}', '{Male}'):
        pairs = (('(', ')'), ('（', '）'), ('[', ']'), ('【', '】'))
        if any(re.search(re.escape(a) + r'\s*' + re.escape(token) + r'\s*' + re.escape(b), source) for a, b in pairs):
            continue  # Source-owned wrappers are never guessed away.
        for a, b in pairs:
            proposed = re.sub(re.escape(a) + r'\s*(' + re.escape(token) + r')\s*' + re.escape(b),
                              lambda m: m[1], proposed)
    return proposed


class Renderer(w.Workflow):
    """Use the shared presentation with read-only source DB and chosen glossary."""
    def __init__(self, project, config, glossary):
        super().__init__(project)
        self.settings, self.analysis = config, glossary

    def config(self, db):
        return self.settings

    def glossary(self, db):
        return self.analysis


class Repair:
    def __init__(self, work=WORK, project=PROJECT):
        self.project, self.work = Path(project).resolve(), Path(work).resolve()
        if not self.work.is_relative_to(self.project / 'TranslateFiles'):
            raise ValueError('Repair artifacts must stay inside this project TranslateFiles')
        self.parent_db = self.project / 'TranslateFiles/state/workflow.sqlite3'
        self.lock = threading.RLock()

    def db(self):
        db = sqlite3.connect(self.parent_db.as_uri() + '?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        return closing(db)

    def snapshot(self):
        value = w.read_json(self.work / 'baseline.json')
        bindings = [(self.project / value[file_key], value[hash_key], error)
            for file_key, hash_key, error in (
                ('translation_file','translation_sha256','Formal translation changed; repair baseline is stale'),
                ('source_file','source_sha256','Original source changed; repair baseline is stale'),
                ('glossary_file','glossary_sha256','Parent frozen glossary changed'))]
        signature = []
        for path, expected, _ in bindings:
            stat = path.stat()
            signature.append((str(path), expected, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size))
        signature = tuple(signature)
        if getattr(self, '_verified_file_bindings', None) != signature:
            for path, expected, error in bindings:
                if sha(path) != expected: raise ValueError(error)
            self._verified_file_bindings = signature
        # Always read the live database revision, including writes in an open
        # WAL. Only unchanged files' repeated full hashes are cached.
        with self.db() as db:
            revision = json.loads(db.execute('SELECT value FROM meta WHERE key="revision"').fetchone()[0])
            if revision != value['parent_revision']:
                raise ValueError('Parent workflow revision changed')
        return value

    def prepare(self):
        if (self.work / 'baseline.json').exists():
            self.snapshot()
            return w.read_json(self.work / 'preparation.json')
        with self.db() as db:
            meta = {r['key']: json.loads(r['value']) for r in db.execute('SELECT key,value FROM meta')}
            if db.execute('SELECT 1 FROM api_calls WHERE status="reserved"').fetchone() or db.execute(
                    'SELECT 1 FROM tasks WHERE status IN ("running","pending","failed") AND revision=?', (meta['revision'],)).fetchone():
                raise ValueError('Finish parent tasks before preparing a fixed repair snapshot')
            if (self.project / 'TranslateFiles/state/api_round.lock').exists():
                raise ValueError('Parent API runner lock exists')
            rows = [dict(r) for r in db.execute('SELECT * FROM records ORDER BY ordinal')]
            baseline_requests = budget_requests(db)
        config = meta['config']; original = Path(meta['source_path'])
        translated = self.project / (self.project.name + '_text_translated.csv')
        glossary = self.project / 'TranslateFiles' / meta['glossary']['path']
        sources, targets = read_column(original), read_column(translated)
        if len(rows) != len(sources) or sources != [r['source'] for r in rows] or targets != [r['translation'] for r in rows]:
            raise ValueError('Database and formal source/translation CSV are not identical')
        self.work.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, self.work / 'source.csv')
        old = w.read_json(glossary); w.write_json(self.work / 'old_glossary.json', old)
        for row in rows:
            row['metadata'] = meta.get('contexts', {}).get(str(row['ordinal']), {})
        w.write_json(self.work / 'records.json', rows)
        baseline = {'source_file': str(original.relative_to(self.project)), 'translation_file': translated.name,
            'source_sha256': sha(original), 'translation_sha256': sha(translated),
            'glossary_file': str(glossary.relative_to(self.project)), 'glossary_sha256': sha(glossary),
            'parent_revision': meta['revision'], 'config': config, 'parent_budget_requests': baseline_requests}
        w.write_json(self.work / 'baseline.json', baseline)
        # This round reclassifies actual terms. Existing protected runtime entries
        # retain the exact already-reviewed parent snapshot; they are not re-approved.
        audit = self.audit_snapshot(old)
        audit['terminology_policy'] = 1
        evidence = attach_corpus_evidence(audit, rows)
        glossary_tool.refresh_stats(audit)
        wrapper = self.work / 'terms_input.json'
        w.write_json(wrapper, {'extra': {'analysis_v1': audit}})
        glossary_tool.audit(wrapper, self.work / 'source.csv', self.work / 'term_audit')
        structural = []
        for row in rows:
            if hidden_marker_wrapper_issues(row['source'], row['translation']):
                structural.append({'id': row['id'], 'ordinal': row['ordinal'], 'source': row['source'],
                    'before': row['translation'], 'proposal': repair_hidden_wrappers(row['source'], row['translation'])})
        singles = []
        for row in rows:
            if row['ordinal'] in CASE4:
                if not row['id'].endswith(CASE4[row['ordinal']]) or 'stubbled scalp' not in row['source']:
                    raise ValueError('Case 4 source binding changed')
                singles.append(row['id'])
        if self.project == PROJECT and len(singles) != 2:
            raise ValueError('Both known case-4 branches are required for this one-off project')
        w.write_json(self.work / 'structural_findings.json', structural)
        w.write_json(self.work / 'individual_cases.json', singles)
        result = {'term_entries': len(audit['characters']) + len(audit['terms']),
            'preserved_protected_entries': len(old['non_translate']), 'structural_candidates': len(structural),
            'individual_case_records': len(singles), 'source_records': len(rows), 'corpus_evidence': evidence,
            'production_changed': False}
        w.write_json(self.work / 'preparation.json', result)
        return result

    @staticmethod
    def audit_snapshot(old):
        audit = copy.deepcopy(old)
        audit['non_translate'] = []
        for table in ('characters', 'terms'):
            for row in audit[table]:
                # Those extraction votes were resolved before v1.3 was frozen.
                # This round reviews the current accepted term, not old proposals.
                # The complete original snapshot remains in old_glossary.json.
                for field in ('extraction_candidates', 'extraction_tasks', 'extraction_count', 'provisional_selection'):
                    row.pop(field, None)
        return audit

    def reprepare_unissued_terms(self):
        """Only locally prepared, never-issued work may change its input view."""
        self.snapshot()
        if (self.work / 'calls.json').exists() and w.read_json(self.work / 'calls.json'):
            raise ValueError('Do not rewrite issued term tasks or reset their attempts')
        if any((self.work / 'jobs').rglob('accepted.json')):
            raise ValueError('Accepted results must not be replaced')
        old_dir = self.work / 'term_audit'; backup = self.work / ('term_audit_unissued_' + uuid.uuid4().hex[:8])
        if not old_dir.resolve().is_relative_to(self.work) or not backup.resolve().is_relative_to(self.work):
            raise ValueError('Audit archive path leaves repair workspace')
        old_dir.rename(backup)
        audit = self.audit_snapshot(w.read_json(self.work / 'old_glossary.json'))
        audit['terminology_policy'] = 1
        attach_corpus_evidence(audit, w.read_json(self.work / 'records.json'))
        glossary_tool.refresh_stats(audit)
        w.write_json(self.work / 'terms_input.json', {'extra': {'analysis_v1': audit}})
        glossary_tool.audit(self.work / 'terms_input.json', self.work / 'source.csv', old_dir)
        return self.prepare_terms()

    def render(self, payload, glossary=None):
        scope = [r['id'] for r in payload['records']]
        transport = api_id_transport(payload, scope, payload['task_id'])
        if payload['stage'] == 'glossary_review':
            text = render_protocol_input(payload, self.work / 'unused.json', api=True)
        else:
            renderer = Renderer(self.project, self.snapshot()['config'], glossary)
            with self.db() as db:
                text = renderer.render_batch_input(db, payload, scope, self.work / 'unused.json',
                    payload['task_id'], api=True, id_transport=transport)
        return text, transport

    def queue(self, stage, units, build, glossary=None, cap=60, manifest=None):
        config = self.snapshot()['config']; output = []
        def partition(part):
            payload = build(part)
            payload['task_id'] = 'inc-' + stage + '-' + w.fingerprint(payload)[:20]
            payload['input_hash'] = w.fingerprint(payload)
            text, binding = self.render(payload, glossary)
            estimate = sum(Renderer(self.project, config, glossary).estimate_review_output(r, stage, config)
                           for r in payload['records']) if stage == 'review' else 0
            source_limit = config.get('review_batch_tokens' if stage == 'review' else 'batch_tokens', 1024)
            if stage in ('translate', 'review') and len(part) > 1 and sum(count_tokens(r['source']) for r in payload['records']) > source_limit:
                middle = len(part) // 2; partition(part[:middle]); partition(part[middle:]); return
            if count_tokens(text) > config.get('task_input_tokens', 16384) or estimate > config.get('review_output_tokens', 16384) * .8:
                if len(part) < 2:
                    raise ValueError('One full item exceeds input/output budget; no truncation allowed')
                middle = len(part) // 2; partition(part[:middle]); partition(part[middle:]); return
            folder = self.work / 'jobs' / stage / payload['task_id']; folder.mkdir(parents=True, exist_ok=True)
            if not (folder / 'payload.json').exists():
                w.write_json(folder / 'payload.json', payload)
                w.write_json(folder / 'binding.json', binding)
                w.atomic_write(folder / 'input.md', text)
            elif w.read_json(folder / 'payload.json') != payload:
                raise ValueError('Existing immutable job input changed')
            output.append(str(folder.relative_to(self.work)))
        for start in range(0, len(units), cap):
            partition(units[start:start + cap])
        w.write_json(self.work / (manifest or stage + '_jobs.json'), output)
        return {'stage': stage, 'jobs': len(output), 'records_or_terms': len(units)}

    def prepare_terms(self, names=None, manifest=None):
        baseline = self.snapshot(); rows = w.read_json(self.work / 'records.json')
        original = w.read_json(self.work / 'term_audit/glossary_original.json')
        audit = w.read_json(self.work / 'term_audit/glossary_audit.json')
        entries = [{'ref': f'{table}:{i}', 'table': table, 'index': i, 'row': row}
                   for table in TABLES for i, row in enumerate(original[table])]
        if names is not None:
            entries = [e for e in entries if e['row']['source'] in names]
        def build(group):
            refs = {e['ref'] for e in group}; ordinals = {n for e in group for n in review_evidence_rows(e['row'])}
            payload = self.base_payload('glossary_review', baseline)
            payload.update(snapshot_sha256=sha(self.work / 'term_audit/glossary_original.json'),
                terminology_policy=1, applicability_policy=original.get('applicability_policy', 0),
                revision_request='这是已发布译文的增量术语治理：普通词移出术语表，多义游戏词按出处确认范围和遵守等级；'
                    '确证词义不合适时修正译名。已有专名译名无明确错误就保留，不为音译或同义偏好改名，不扩充无关新术语。'
                    '本轮只审characters/terms，运行保护non_translate沿用原有通过记录，不新增或改动运行保护条目。',
                entries=group, related_entries=[], term_families=[],
                audit={**audit, 'findings': [f for f in audit['findings'] if refs.intersection(f['refs'])]},
                records=[{'id': r['id'], 'ordinal': r['ordinal'], 'source': r['source'],
                          'metadata': r['metadata']} for r in rows if r['ordinal'] in ordinals])
            return payload
        return self.queue('glossary_review', entries, build, cap=60, manifest=manifest)

    def base_payload(self, stage, baseline):
        c = baseline['config']
        return {'stage': stage, 'revision': baseline['parent_revision'], 'source_hash': baseline['source_sha256'],
            'language': {'source': c['source_language'], 'target': c['target_language']},
            'style': c['style'], 'game_background': c.get('game_background', ''), 'context': [],
            'layout_policy': c.get('layout_normalization', 'off')}

    def validate_result(self, payload, result, glossary):
        if payload['stage'] == 'glossary_review':
            decisions = result['decisions']; validate_glossary_reviews(decisions, payload)
            if decisions.get('review_complete') is not True or not str(decisions.get('review_summary', '')).strip():
                raise ValueError('Term review completion and real summary required')
            expected = {e['ref'] for e in payload['entries']}
            for action in ('edits', 'quarantine'):
                if any(f"{x['table']}:{x['index']}" not in expected for x in decisions.get(action, [])):
                    raise ValueError('Term decision changes unassigned entry')
            return result
        originals = {r['id']: r for r in payload['records']}
        if len(result['records']) != len(originals) or {r['id'] for r in result['records']} != set(originals):
            raise ValueError('Body result must cover exact scope once')
        config = self.snapshot()['config']; rules = bridge.patterns(config['protect_named_curly'] is not False,
            config['exclusions'], config.get('placeholder_family_overrides'))
        for item in result['records']:
            original = originals[item['id']]
            inherited = w.Workflow.inherit_exceptions(item, original)
            item.clear(); item.update(inherited)
            item['translation'] = bridge.restore(item['translation'], original.get('protection', []), allow_original=True)
            raw_source = bridge.restore(original['source'], original.get('protection', []), allow_original=True)
            policy = payload.get('layout_policy')
            if policy is None:
                policy = config.get('layout_normalization', w.DEFAULT['layout_normalization'])
            elif policy == 'off' and 'layout_normalization' not in config:
                # These legacy tasks were made by this project adapter, whose
                # fallback incorrectly used off rather than the shared default.
                # Preserve their identity and history; resolve the missing
                # configuration using the real shared default at collection.
                policy = w.DEFAULT['layout_normalization']
            normalized, audit = normalize_body_item(item, original,
                {'id': item['id'], 'source': raw_source, 'locked': bool(original.get('locked'))}, config,
                policy)
            item.clear(); item.update(normalized)
            if audit:
                audit['declared_policy'] = payload.get('layout_policy')
                audit['effective_policy'] = policy
                item['_layout_audit'] = audit
            issues = bridge.record_structural_issues({'id': item['id'], 'source': raw_source}, item['translation'], rules, config)
            if issues:
                raise ValueError(item['id'] + ': structural ' + repr(issues))
            # Restored comments may contain names (even in a malformed brace
            # block). Keep the exact protection spans used by this task hidden
            # from terminology enforcement, just as in the API input.
            term_rules = list(rules) + [
                ('task_protection_' + str(n), re.compile(re.escape(p['original'])))
                for n, p in enumerate(original.get('protection', [])) if p.get('original')]
            terms = bridge.matched_terms(glossary, [raw_source], config, rules=term_rules)
            exceptions = item.get('exceptions', [])
            exempt = {e['source'].casefold() for e in exceptions if isinstance(e, dict) and e.get('reason')}
            missing = [t['src'] for t in terms if bridge.term_required(t) and not bridge.helper().is_keep_original_translation(t['dst'])
                       and t['dst'] not in item['translation'] and t['src'].casefold() not in exempt]
            if missing:
                raise ValueError('Required term/exception missing: ' + repr(missing))
            if payload['stage'] == 'review':
                validate_review(item, raw_source, original['translation'], item['translation'])
                if item.get('issues'):
                    raise ValueError('Unresolved semantic issue needs attention')
        return result

    def term_payload(self, payload):
        path = self.work / 'term_source_supplements.json'
        if not path.exists(): return payload
        supplement = w.read_json(path)
        if supplement['source_sha256'] != self.snapshot()['source_sha256']:
            raise ValueError('Supplemental term sources changed')
        additions = supplement['jobs'].get(payload['task_id'])
        if not additions: return payload
        if additions['input_hash'] != payload['input_hash']:
            raise ValueError('Supplemental term job binding mismatch')
        value = copy.deepcopy(payload)
        texts = read_column(self.work / 'source.csv')
        existing = {row['ordinal'] for row in value['records']}
        for entry in value['entries']:
            for row in additions['entries'].get(entry['ref'], []):
                if texts[row['ordinal'] - 1] != row['source'] or entry['row']['source'] not in row['source']:
                    raise ValueError('Supplemental term citation differs from immutable source')
                entry['row'].setdefault('corpus_evidence_rows', []).append(row['ordinal'])
                if row['ordinal'] not in existing:
                    value['records'].append(row); existing.add(row['ordinal'])
        value['supplemental_evidence_sha256'] = sha(path)
        return value

    def run_jobs(self, stage, api_name=None, max_jobs=None, manifest=None):
        baseline = self.snapshot(); config = baseline['config']
        settings, key = w.load_api_settings(config, name=api_name)
        selected_api = w.local_api_name(name=api_name)
        if not settings['think_switch']:
            raise ValueError('Keep thinking enabled for this repair')
        job_manifest = manifest or stage + '_jobs.json'
        jobs = [self.work / p for p in w.read_json(self.work / job_manifest)]
        jobs = [p for p in jobs if not (p / 'accepted.json').exists()]
        if max_jobs is not None:
            jobs = jobs[:max_jobs]
        glossary = w.read_json(self.work / ('new_glossary.json' if (self.work / 'new_glossary.json').exists() else 'old_glossary.json'))
        if stage == 'glossary_review':
            term_snapshot = w.read_json(self.work / 'term_audit/glossary_original.json')
            corpus_rows = {r['ordinal']: r for r in w.read_json(self.work / 'records.json')}
        else:
            import scope_match
            scope_match.prepare(glossary, config, bridge.patterns(config['protect_named_curly'] is not False,
                config['exclusions'], config.get('placeholder_family_overrides')))
        stopped = threading.Event()
        ledger_path = self.work / 'calls.json'; ledger = w.read_json(ledger_path) if ledger_path.exists() else []
        grant_file = self.work / 'retry_grants.json'
        grants = w.read_json(grant_file) if grant_file.exists() else {}
        if any(c['status'] == 'reserved' for c in ledger):
            raise ValueError('Unknown previous in-flight requests; inspect before explicit recovery')
        if not jobs:
            return {'stage': stage, 'remaining': 0, 'errors': []}
        # Prepared jobs may run in a fresh process without queue() first. Seed
        # the filesystem-backed tokenizer before concurrent first use; its lazy
        # lru_cache initialization is not a single-flight lock.
        count_tokens('')
        pool = w.make_api_pool(config, self.work, stage, name=api_name)
        if any(not s['settings']['think_switch'] for s in pool.specs):
            raise ValueError('Keep thinking enabled on every priority API for this repair')
        def work(folder):
            payload = w.read_json(folder / 'payload.json'); binding = w.read_json(folder / 'binding.json')
            if w.fingerprint({k: v for k, v in payload.items() if k != 'input_hash'}) != payload['input_hash']:
                raise ValueError('Job payload hash mismatch')
            if stage == 'glossary_review': payload = self.term_payload(payload)
            scope = [r['id'] for r in payload['records']]; failures = 0; connection_retries = 0
            attempt_jobs = {folder.name, payload.get('attempt_parent_job', folder.name)}
            prior = [c for c in ledger if c['job'] in attempt_jobs and c['status'] != 'cancelled' and not service_failure(c['status'])]
            grant = grants.get(folder.name, {})
            extra = grant.get('extra_attempts', 0) if grant.get('api') == selected_api else 0
            if type(extra) is not int or extra < 0:
                raise ValueError('Invalid explicit retry grant')
            attempt_limit = config.get('max_attempts', 3) + extra
            if stage != 'glossary_review':
                attempt_limit = min(attempt_limit, len(prior) + config.get('agent_attempt_limit', 2))
            if grant.get('api') == selected_api and 'max_total_attempts' in grant:
                if type(grant['max_total_attempts']) is not int or grant['max_total_attempts'] < 1:
                    raise ValueError('Invalid absolute retry cap')
                attempt_limit = min(attempt_limit, grant['max_total_attempts'])
            # A received raw reply can survive a crash before collection. Recover
            # it first, keeping the original call identity and budget history.
            for old_call in prior:
                raw_file = folder / old_call['id'] / 'response.raw.txt'
                if old_call['status'] not in ('received', 'interrupted') or not raw_file.exists():
                    continue
                try:
                    parsed = bridge.parse_response(raw_file.read_text(encoding='utf-8'))
                    if stage != 'glossary_review':
                        prior_folder = raw_file.parent
                        prior_payload = w.read_json(prior_folder / 'payload.json') if (prior_folder / 'payload.json').exists() else payload
                        prior_binding = w.read_json(prior_folder / 'binding.json') if (prior_folder / 'binding.json').exists() else binding
                        prior_scope = [r['id'] for r in prior_payload['records']]
                        result = canonical_api_partial_result(parsed, prior_binding, payload['task_id'], payload['task_id'], payload['input_hash'], prior_scope)
                        self.save_body_parts(folder, payload, prior_payload, result, glossary, 'api:' + old_call['id'], sha(raw_file))
                        return folder.name
                    import term_parts
                    term_parts.save(self, folder, payload,
                        w.read_json(raw_file.parent / 'payload.json') if (raw_file.parent / 'payload.json').exists() else payload,
                        parsed, w.read_json(raw_file.parent / 'binding.json') if (raw_file.parent / 'binding.json').exists() else binding,
                        'api:' + old_call['id'], raw_file)
                except (ValueError, KeyError, TypeError):
                    continue
                return folder.name
            if stage == 'glossary_review':
                import term_parts
                if term_parts.finish(self, folder, payload):
                    return folder.name
            if stage != 'glossary_review' and len(self.partial_body_rows(folder, payload)) == len(scope):
                self.finish_partial_body(folder, payload, self.partial_body_rows(folder, payload))
                return folder.name
            while len(prior) + failures < attempt_limit and not stopped.is_set():
                request_payload = payload
                if stage != 'glossary_review':
                    saved_rows = self.partial_body_rows(folder, payload)
                    if len(saved_rows) == len(scope):
                        self.finish_partial_body(folder, payload, saved_rows)
                        return folder.name
                    request_payload = {**payload, 'records': [r for r in payload['records'] if r['id'] not in saved_rows]}
                else:
                    saved_terms = term_parts.rows(folder, payload)
                    if term_parts.finish(self, folder, payload):
                        return folder.name
                    unacked = {f['id'] for f in payload['audit']['findings']} - term_parts.acknowledgments(folder, payload)
                    ack_refs = {ref for f in payload['audit']['findings'] if f['id'] in unacked for ref in f['refs']}
                    remaining = [e for e in payload['entries'] if e['ref'] not in saved_terms or e['ref'] in ack_refs][:20]
                    refs = {e['ref'] for e in remaining}
                    findings = [f for f in payload['audit']['findings'] if refs.intersection(f['refs'])]
                    related = []
                    for ref in sorted({ref for f in findings for ref in f['refs']} - refs):
                        table, index = ref.split(':')
                        related.append({'ref': ref, 'table': table, 'index': int(index), 'row': term_snapshot[table][int(index)]})
                    ordinals = {n for e in remaining + related for n in review_evidence_rows(e['row'])}
                    request_payload = {**payload, 'entries': remaining,
                        'related_entries': related,
                        'records': [{'id': corpus_rows[n]['id'], 'ordinal': n, 'source': corpus_rows[n]['source'],
                                     'metadata': corpus_rows[n]['metadata']} for n in sorted(ordinals)],
                        'audit': {**payload['audit'], 'findings': findings}}
                text, request_binding = self.render(request_payload, glossary)
                previous = [c.get('error') for c in ledger if c['job'] == folder.name and c.get('error')]
                if previous:
                    text += '\n程序拒收诊断：' + previous[-1] + '\n按原文和真实证据补全本批，不能机械填通过。'
                    if 'physical_newlines' in previous[-1] or 'boundary_whitespace' in previous[-1]:
                        short_ids = {v: k for k, v in request_binding['short_to_canonical'].items()}
                        layout = [{'id': short_ids[r['id']],
                            'physical_newlines': re.findall(r'\r\n|\r|\n', r['source']),
                            'trailing_whitespace': r['source'][len(r['source'].rstrip()):]}
                            for r in request_payload['records']]
                        text += '\n排版补交：保留原文所有物理换行，包括连续空白行和句末空行、尾部空白；JSON字符串用转义表示。逐条原文排版：' + json.dumps(layout, ensure_ascii=False)
                if grant.get('diagnostic'):
                    text += '\n补交说明：' + grant['diagnostic']
                if count_tokens(text) > config.get('task_input_tokens', 16384):
                    raise ValueError('Retry input exceeds configured budget; no request issued')
                with self.lock:
                    if stopped.is_set():
                        raise ValueError('Stopped before issuing another request')
                    with self.db() as db:
                        parent_used = max(baseline['parent_budget_requests'], budget_requests(db))
                    spent = parent_used + sum(c['status'] != 'cancelled' and not service_failure(c['status']) for c in ledger)
                    if spent >= settings['max_requests']:
                        stopped.set(); raise ValueError('Configured cumulative request budget exhausted')
                    call = {'id': uuid.uuid4().hex, 'job': folder.name, 'stage': stage, 'status': 'reserved',
                            'api': selected_api, 'requested_model': settings['model_name'], 'issued_at': time.time()}
                    ledger.append(call); w.write_json(ledger_path, ledger)
                out = folder / call['id']; out.mkdir()
                route = None
                try:
                    route = pool.acquire(stopped.is_set)
                    with self.lock:
                        with self.db() as db:
                            current_parent = max(baseline['parent_budget_requests'], budget_requests(db))
                        used_now = current_parent + sum(c['status'] != 'cancelled' and not service_failure(c['status']) for c in ledger)
                        if used_now > min(settings['max_requests'], route.spec['settings']['max_requests']):
                            raise bridge.ApiFailure('APIStatusError:request_budget_exhausted', False,
                                {'usage_reported': False, 'request_issued': False})
                        call.update(api=route.spec['name'], requested_model=route.spec['settings']['model_name'])
                        w.write_json(ledger_path, ledger)
                    w.atomic_write(out / 'request.md', text)
                    w.write_json(out / 'binding.json', request_binding)
                    w.write_json(out / 'payload.json', request_payload)
                    raw, usage = pool.execute(route, '', text, call['id'], task_id=payload['task_id'], job=folder.name)
                    w.atomic_write(out / 'response.raw.txt', raw); w.write_json(out / 'usage.json', usage)
                    call.update(status='received', usage=usage)
                    parsed = bridge.parse_response(raw, out / 'normalization.json')
                    request_scope = [r['id'] for r in request_payload['records']]
                    if stage != 'glossary_review':
                        result = canonical_api_partial_result(parsed, request_binding, payload['task_id'], payload['task_id'], payload['input_hash'], request_scope)
                        self.save_body_parts(folder, payload, request_payload, result, glossary, 'api:' + call['id'], sha(out / 'response.raw.txt'))
                        pool.audit.outcome(call['id'], 'saved')
                        return folder.name
                    term_parts.save(self, folder, payload, request_payload, parsed, request_binding,
                        'api:' + call['id'], out / 'response.raw.txt')
                    w.write_json(out / 'result.json', w.read_json(folder / 'accepted.json')['result'])
                    pool.audit.outcome(call['id'], 'saved')
                    return folder.name
                except bridge.ApiFailure as exc:
                    not_issued = (exc.usage or {}).get('request_issued') is False
                    call.update(status='cancelled' if not_issued or str(exc) == 'validation_wire_limit' else str(exc), usage=exc.usage)
                    if not_issued: call['transport_status'] = str(exc)
                    if pool.should_retry(str(exc)):
                        continue
                    delay = connection_retry_delay(str(exc), connection_retries) if not pool.managed else None
                    if delay is None:
                        stopped.set(); raise
                    connection_retries += 1; time.sleep(delay)
                except Exception as exc:
                    call.update(status='rejected', error=str(exc)[:1500]); failures += 1
                    pool.audit.outcome(call['id'], 'rejected')
                    w.write_json(out / 'rejection.json', {'reason': str(exc)})
                    if (call.get('usage') or {}).get('finish_reason') == 'length':
                        stopped.set(); raise
                finally:
                    if route is not None: pool.release(route)
                    call['elapsed_seconds'] = round(time.time() - call['issued_at'], 3)
                    with self.lock:
                        w.write_json(ledger_path, ledger)
            if not (folder / 'accepted.json').exists():
                if stopped.is_set():
                    raise ValueError('Stage stopped before job completed: ' + folder.name)
                raise ValueError('Job retry limit reached: ' + folder.name)
        errors = []
        try:
            with ThreadPoolExecutor(max_workers=pool.max_workers) as executor:
                try:
                    futures = [executor.submit(work, p) for p in jobs]
                    for future in as_completed(futures):
                        try:
                            print(json.dumps({'accepted': future.result()}, ensure_ascii=False), flush=True)
                        except Exception as exc:
                            errors.append(str(exc))
                            # A bounded format/semantic retry exhaustion belongs to
                            # this job; independent queued jobs can still finish.
                            if not str(exc).startswith(('Job retry limit reached:', 'Stage stopped before job completed:')):
                                stopped.set()
                except BaseException:
                    stopped.set()
                    with pool.cv:
                        pool.closed = True; pool.cv.notify_all()
                    raise
        finally:
            pool.close()
        return {'stage': stage, 'remaining': sum(not (p / 'accepted.json').exists() for p in
            [self.work / s for s in w.read_json(self.work / job_manifest)]), 'errors': errors,
            'api_provider_report': str(pool.audit.report), 'api_provider_log': str(pool.audit.log)}

    def partial_body_rows(self, folder, payload):
        rows = {}
        for p in (folder / 'partial').glob('*.json'):
            saved = w.read_json(p)
            if saved['input_hash'] != payload['input_hash'] or saved['item']['id'] not in {r['id'] for r in payload['records']}:
                raise ValueError('Partial candidate is outside immutable input scope')
            rows[saved['item']['id']] = saved
        return rows

    def finish_partial_body(self, folder, payload, rows):
        ids = [r['id'] for r in payload['records']]
        if set(ids) != set(rows):
            raise ValueError('Partial body coverage incomplete')
        result = {'task_id': payload['task_id'], 'input_hash': payload['input_hash'], 'records': [rows[i]['item'] for i in ids]}
        w.write_json(folder / 'accepted.json', {'result': result, 'input_hash': payload['input_hash'],
            'record_instances': {i: rows[i]['instance'] for i in ids},
            'record_response_sha256': {i: rows[i]['response_sha256'] for i in ids}})

    def save_body_parts(self, folder, full_payload, request_payload, result, glossary, instance, response_sha256):
        received = {r['id']: r for r in result['records']}; errors = []
        existing = self.partial_body_rows(folder, full_payload)
        for original in request_payload['records']:
            rid = original['id']; item = received.get(rid)
            if rid in existing:
                continue
            try:
                if item is None or item.get('_format_error'):
                    raise ValueError(item.get('_format_error') if item else 'missing record')
                self.validate_result({**request_payload, 'records': [original]}, {'records': [item]}, glossary)
                w.write_json(folder / 'partial' / (rid + '.json'), {'item': item, 'input_hash': full_payload['input_hash'],
                    'instance': instance, 'response_sha256': response_sha256})
            except (ValueError, KeyError, TypeError) as exc:
                errors.append(str(exc))
        saved = self.partial_body_rows(folder, full_payload)
        if len(saved) != len(full_payload['records']):
            raise ValueError('Only failed/missing records need retry: ' + '; '.join(errors)[:1200])
        self.finish_partial_body(folder, full_payload, saved)

    def collect_terms(self):
        self.snapshot(); decisions = {'review_complete': True, 'review_summary': 'Incremental reclassification of existing terms; evidence from independent API requests.',
            'snapshot_sha256': sha(self.work / 'term_audit/glossary_original.json'), 'source_sha256': sha(self.work / 'source.csv')}
        for key in ('reviewed_refs', 'entry_reviews', 'acknowledged_findings', 'edits', 'quarantine', 'additions', 'allow_no_match'):
            decisions[key] = []
        instances = {}
        for relative in w.read_json(self.work / 'glossary_review_jobs.json'):
            folder = self.work / relative; saved = w.read_json(folder / 'accepted.json')
            payload = w.read_json(folder / 'payload.json')
            payload = self.term_payload(payload)
            if saved['input_hash'] != payload['input_hash']:
                raise ValueError('Accepted term result binding changed')
            d = saved['result']['decisions']
            if 'entry_instances' in saved:
                import term_parts
                payload = term_parts.validation_payload(self, folder, payload)
            validate_glossary_reviews(d, payload)
            for key in ('reviewed_refs', 'entry_reviews', 'acknowledged_findings', 'edits', 'quarantine', 'additions', 'allow_no_match'):
                decisions[key].extend(d.get(key, []))
            for entry in payload['entries']:
                instances[entry['ref']] = saved.get('entry_instances', {}).get(entry['ref']) or saved['instance']
        decisions['review_instances'] = instances
        decisions['acknowledged_findings'] = list(dict.fromkeys(decisions['acknowledged_findings']))
        snapshot = w.read_json(self.work / 'term_audit/glossary_original.json')
        expected = {f'{t}:{i}' for t in TABLES for i in range(len(snapshot[t]))}
        if len(decisions['entry_reviews']) != len(expected) or set(instances) != expected:
            raise ValueError('Full existing-term review not complete')
        w.write_json(self.work / 'term_decisions.json', decisions)
        build = self.work / 'term_build'
        if not (build / 'glossary_reviewed.json').exists():
            glossary_tool.build(self.work / 'term_audit/glossary_original.json', self.work / 'source.csv',
                                self.work / 'term_decisions.json', build)
        if w.read_json(build / 'glossary_manifest.json')['decisions_sha256'] != sha(self.work / 'term_decisions.json'):
            raise ValueError('Term build is bound to older decisions; preserve it and investigate')
        revised = w.read_json(build / 'glossary_reviewed.json'); old = w.read_json(self.work / 'old_glossary.json')
        if revised['non_translate']:
            raise ValueError('This term-only audit may not add protected entries')
        # Keep unchanged runtime protection under its original reviewed snapshot;
        # do not pretend it received new classification or semantic review.
        revised.pop('terminology_policy', None)
        revised['non_translate'] = copy.deepcopy(old['non_translate'])
        null_scopes = []
        for table in TABLES:
            for row in revised[table]:
                if 'applicability' in row and row['applicability'] is None:
                    # Shared scope validation treats null as absent/default;
                    # the matcher requires an omitted key rather than null.
                    row.pop('applicability'); null_scopes.append([table, row['source']])
        w.write_json(self.work / 'term_representation_normalizations.json',
            {'null_scope_to_absent_default': null_scopes})
        glossary_tool.refresh_stats(revised); glossary_tool.validate_shape(revised)
        w.write_json(self.work / 'new_glossary.json', revised)
        return self.plan()

    def plan(self):
        baseline = self.snapshot(); config = baseline['config']
        old = w.read_json(self.work / 'old_glossary.json'); new = w.read_json(self.work / 'new_glossary.json')
        changes, annotations = term_changes(old, new, config)
        old_probe = {t: [] for t in TABLES}; new_probe = {t: [] for t in TABLES}
        changed_keys = {(c['table'], c['source']) for c in changes}
        for t in TABLES:
            old_probe[t] = [r for r in old[t] if (t, r['source']) in changed_keys]
            new_probe[t] = [r for r in new[t] if (t, r['source']) in changed_keys]
        rules = bridge.patterns(config['protect_named_curly'] is not False, config['exclusions'], config.get('placeholder_family_overrides'))
        old_comparison, new_comparison = comparison_glossaries(old, new)
        import scope_match
        for view in (old_probe, new_probe, old_comparison, new_comparison):
            scope_match.prepare(view, config, rules)
        affected, preserved_exemptions = [], []
        rows = w.read_json(self.work / 'records.json')
        for number, row in enumerate(rows, 1):
            if number % 5000 == 0:
                print(json.dumps({'scope_scan': number, 'total': len(rows)}, ensure_ascii=False), flush=True)
            actual_rules = bridge.record_rules(row, config, rules)
            texts = [row['source'], row['metadata'].get('speaker', '')]
            if not bridge.matched_terms(old_probe, texts, config, rules=actual_rules) and not bridge.matched_terms(new_probe, texts, config, rules=actual_rules):
                continue
            before = bridge.matched_terms(old_comparison, texts, config, rules=actual_rules)
            after = bridge.matched_terms(new_comparison, texts, config, rules=actual_rules)
            if policy_change_affects_record(before, after, row.get('exceptions', [])):
                if row['locked']:
                    raise ValueError('Affected confirmed record is locked: ' + row['id'])
                affected.append(row['id'])
            elif matched_meaning(before) != matched_meaning(after):
                preserved_exemptions.append(row['id'])
        structural = w.read_json(self.work / 'structural_findings.json'); individual = w.read_json(self.work / 'individual_cases.json')
        union = sorted(set(affected) | {r['id'] for r in structural} | set(individual))
        if any(r['locked'] and r['id'] in union for r in rows):
            raise ValueError('An incremental-scope record is locked')
        plan = {'term_changes': changes, 'annotation_only': annotations, 'term_affected_ids': affected,
            'preserved_by_existing_exceptions': preserved_exemptions,
            'structural_ids': [r['id'] for r in structural], 'individual_ids': individual,
            'scope_ids': union, 'preserved_records': len(rows) - len(union),
            'baseline_translation_sha256': baseline['translation_sha256'], 'new_glossary_sha256': sha(self.work / 'new_glossary.json')}
        w.write_json(self.work / 'repair_plan.json', plan)
        return {'effective_term_changes': len(changes), 'annotation_only': len(annotations),
                'term_affected_records': len(affected), 'total_scope': len(union), 'preserved_records': plan['preserved_records']}

    def prepare_translation(self):
        baseline = self.snapshot(); plan = w.read_json(self.work / 'repair_plan.json')
        glossary = w.read_json(self.work / 'new_glossary.json'); config = baseline['config']
        rules = bridge.patterns(config['protect_named_curly'] is not False, config['exclusions'], config.get('placeholder_family_overrides'))
        import scope_match
        scope_match.prepare(glossary, config, rules)
        affected = set(plan['term_affected_ids'])
        rows = [r for r in w.read_json(self.work / 'records.json') if r['id'] in affected]
        def build(group):
            payload = self.base_payload('translate', baseline); payload['records'] = []
            payload['terms'] = bridge.matched_terms(glossary, [r['source'] for r in group], config, rules=rules)
            for r in group:
                source, protection = bridge.protect(r['source'], r['id'], bridge.record_rules(r, config, rules))
                payload['records'].append({'id': r['id'], 'ordinal': r['ordinal'], 'source': source,
                    'protection': protection, 'translation': None, 'metadata': r['metadata'], 'exceptions': [], 'locked': False})
            return payload
        # The existing translation is deliberately absent from these inputs.
        return self.queue('translate', rows, build, glossary, cap=20)

    def accepted_body(self, stage, glossary):
        results = {}
        for relative in w.read_json(self.work / (stage + '_jobs.json')):
            folder = self.work / relative
            saved = w.read_json(folder / 'accepted.json'); payload = w.read_json(folder / 'payload.json')
            if saved['input_hash'] != payload['input_hash']:
                raise ValueError('Body result binding changed')
            self.validate_result(payload, saved['result'], glossary)
            for item in saved['result']['records']:
                if item['id'] in results:
                    raise ValueError('Duplicate accepted record')
                results[item['id']] = {'item': item,
                    'instance': saved.get('record_instances', {}).get(item['id'], saved.get('instance')), 'job': folder.name}
        return results

    def prepare_review(self):
        baseline = self.snapshot(); plan = w.read_json(self.work / 'repair_plan.json'); config = baseline['config']
        glossary = w.read_json(self.work / 'new_glossary.json')
        translated = self.accepted_body('translate', glossary)
        if set(translated) != set(plan['term_affected_ids']):
            raise ValueError('Affected-ID translation coverage incomplete')
        structural = {r['id']: r for r in w.read_json(self.work / 'structural_findings.json')}
        rules = bridge.patterns(config['protect_named_curly'] is not False, config['exclusions'], config.get('placeholder_family_overrides'))
        import scope_match
        scope_match.prepare(glossary, config, rules)
        scope = set(plan['scope_ids']); rows = [r for r in w.read_json(self.work / 'records.json') if r['id'] in scope]
        def build(group):
            payload = self.base_payload('review', baseline); payload['records'] = []
            payload['terms'] = bridge.matched_terms(glossary, [r['source'] for r in group], config, rules=rules)
            for r in group:
                candidate = translated.get(r['id'], {}).get('item', {})
                target = candidate.get('translation', structural.get(r['id'], {}).get('proposal', r['translation']))
                row = {'id': r['id'], 'ordinal': r['ordinal'], 'source': r['source'], 'translation': target,
                       'protection': [], 'metadata': r['metadata'], 'exceptions': candidate.get('exceptions', []), 'locked': False}
                if r['id'] in plan['individual_ids']:
                    row['diagnostic'] = '本次已定位的词义错误：stubbled修饰scalp，核对头皮上的短发茬；只修明确错误，保留无关原译。'
                payload['records'].append(row)
            return payload
        return self.queue('review', rows, build, glossary, cap=40)

    def export_candidate(self):
        baseline = self.snapshot(); plan = w.read_json(self.work / 'repair_plan.json')
        glossary = w.read_json(self.work / 'new_glossary.json')
        if sha(self.work / 'new_glossary.json') != plan['new_glossary_sha256']:
            raise ValueError('Term policy changed after scope planning')
        translated = self.accepted_body('translate', glossary); reviewed = self.accepted_body('review', glossary)
        if set(reviewed) != set(plan['scope_ids']) or set(translated) != set(plan['term_affected_ids']):
            raise ValueError('Exact incremental scope not independently reviewed')
        for rid in translated:
            if translated[rid]['instance'] == reviewed[rid]['instance']:
                raise ValueError('Reviewer must be independent of translator')
        targets = read_column(self.project / baseline['translation_file']); records = w.read_json(self.work / 'records.json')
        changes = []
        for row in records:
            if row['id'] not in reviewed:
                continue
            after = reviewed[row['id']]['item']['translation']
            if after != row['translation']:
                changes.append({'id': row['id'], 'ordinal': row['ordinal'], 'source_sha256': hashlib.sha256(row['source'].encode()).hexdigest(),
                    'before': row['translation'], 'after': after, 'review_job': reviewed[row['id']]['job']})
            targets[row['ordinal'] - 1] = after
        # Full mechanical scan is local only. It is not another API review round.
        config = baseline['config']; rules = bridge.patterns(config['protect_named_curly'] is not False, config['exclusions'], config.get('placeholder_family_overrides'))
        findings, preexisting = [], []
        for row, target in zip(records, targets):
            issues = bridge.record_structural_issues(row, target, rules, config)
            if not issues:
                continue
            if row['id'] in reviewed or target != row['translation']:
                findings.append({'id': row['id'], 'issues': issues})
            else:
                preexisting.append({'id': row['id'], 'issues': issues})
        if findings:
            w.write_json(self.work / 'candidate_rejections.json', findings)
            raise ValueError('Incremental output has structural problems')
        if any(hidden_marker_wrapper_issues(r['source'], t) for r, t in zip(records, targets)):
            raise ValueError('Hidden marker wrapper problem still remains')
        import io
        stream = io.StringIO(newline=''); csv.writer(stream).writerows([[t] for t in targets])
        output = self.work / 'torment-tides-of-numenera_text_translated_candidate.csv'
        w.atomic_write(output, stream.getvalue())
        if read_column(output) != targets:
            raise ValueError('Candidate CSV round-trip mismatch')
        report = {'status': 'validation_candidate_only' if plan.get('validation_scope_only') else 'incremental_candidate_validated',
            'formal_translation_unchanged': True,
            'baseline_translation_sha256': baseline['translation_sha256'], 'candidate_sha256': sha(output),
            'new_glossary_sha256': plan['new_glossary_sha256'], 'scope_records': len(reviewed),
            'changed_records': len(changes), 'preserved_outside_scope': plan['preserved_records'],
            'changes': changes, 'unchanged_preexisting_structural_findings': preexisting,
            'not_done': ['formal workflow integration', 'engine repack', 'in-game verification', 'publication']}
        w.write_json(self.work / 'candidate_manifest.json', report)
        return {k: v for k, v in report.items() if k not in ('changes', 'unchanged_preexisting_structural_findings')}

    def recover_stopped(self):
        from run_api_round import pid_alive
        lockfile = self.work / 'runner.lock'
        if lockfile.exists():
            owner = w.read_json(lockfile)
            if pid_alive(owner.get('pid')):
                raise ValueError('Previous repair process is still alive')
            lockfile.unlink()
        ledger_file = self.work / 'calls.json'
        ledger = w.read_json(ledger_file) if ledger_file.exists() else []
        recovered = []
        for call in ledger:
            if call['status'] != 'reserved':
                continue
            folder = self.work / 'jobs' / call['stage'] / call['job'] / call['id']
            call['status'] = 'received' if (folder / 'response.raw.txt').exists() else 'interrupted'
            call['usage'] = w.read_json(folder / 'usage.json') if (folder / 'usage.json').exists() else {'usage_reported': False}
            call['recovery'] = 'Verified old process stopped; collect saved response first; unknown usage stays unknown.'
            recovered.append(call['id'])
        w.write_json(ledger_file, ledger)
        return {'recovered_calls': recovered, 'attempts_reset': False}

    def run_all(self, api_name=None):
        report = {'preparation': self.prepare()}
        self.prepare_terms()
        report['terms'] = self.run_jobs('glossary_review', api_name)
        if report['terms']['remaining']:
            return {**report, 'status': 'stopped_at_terms'}
        report['scope'] = self.collect_terms()
        self.prepare_translation()
        report['translation'] = self.run_jobs('translate', api_name)
        if report['translation']['remaining']:
            return {**report, 'status': 'stopped_at_translation'}
        self.prepare_review()
        report['review'] = self.run_jobs('review', api_name)
        if report['review']['remaining']:
            return {**report, 'status': 'stopped_at_review'}
        report['candidate'] = self.export_candidate()
        return report

    def status(self):
        if not (self.work / 'baseline.json').exists():
            return {'prepared': False}
        baseline = self.snapshot(); stages = {}
        for stage in ('glossary_review', 'translate', 'review'):
            path = self.work / (stage + '_jobs.json')
            if not path.exists():
                continue
            folders = [self.work / p for p in w.read_json(path)]
            done = sum((p / 'accepted.json').exists() for p in folders)
            stages[stage] = {'total': len(folders), 'accepted': done, 'remaining': len(folders) - done}
        ledger = w.read_json(self.work / 'calls.json') if (self.work / 'calls.json').exists() else []
        return {'prepared': True, 'stages': stages, 'ledger_entries': len(ledger),
            'new_model_requests': sum(c['status'] != 'cancelled' and not service_failure(c['status']) for c in ledger),
            'service_failures': sum(service_failure(c['status']) for c in ledger),
            'parent_model_requests_at_snapshot': baseline['parent_budget_requests'],
            'candidate_exists': (self.work / 'candidate_manifest.json').exists()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'prepare-terms', 'audit-terms', 'collect-terms', 'plan',
        'prepare-translation', 'translate', 'prepare-review', 'review', 'export-candidate', 'recover-stopped',
        'reprepare-unissued-terms', 'run', 'status'))
    parser.add_argument('--api'); parser.add_argument('--max-jobs', type=int)
    args = parser.parse_args(); repair = Repair()
    if args.max_jobs is not None and args.max_jobs < 1:
        parser.error('--max-jobs must be positive')
    commands = {'prepare': repair.prepare, 'prepare-terms': repair.prepare_terms,
                'audit-terms': lambda: repair.run_jobs('glossary_review', args.api, args.max_jobs),
                'collect-terms': repair.collect_terms, 'plan': repair.plan,
                'prepare-translation': repair.prepare_translation,
                'translate': lambda: repair.run_jobs('translate', args.api, args.max_jobs),
                'prepare-review': repair.prepare_review,
                'review': lambda: repair.run_jobs('review', args.api, args.max_jobs),
                'export-candidate': repair.export_candidate, 'run': lambda: repair.run_all(args.api),
                'reprepare-unissued-terms': repair.reprepare_unissued_terms}
    if args.command == 'status':
        print(json.dumps(repair.status(), ensure_ascii=False, indent=2)); return
    repair.work.mkdir(parents=True, exist_ok=True)
    if args.command == 'recover-stopped':
        print(json.dumps(repair.recover_stopped(), ensure_ascii=False, indent=2)); return
    lockfile = repair.work / 'runner.lock'
    try:
        with lockfile.open('x', encoding='utf-8') as f:
            json.dump({'pid': os.getpid(), 'command': args.command}, f)
    except FileExistsError:
        raise ValueError('Repair runner lock exists; verify its process stopped before recovery') from None
    try:
        print(json.dumps(commands[args.command](), ensure_ascii=False, indent=2))
    finally:
        lockfile.unlink()


if __name__ == '__main__':
    main()
