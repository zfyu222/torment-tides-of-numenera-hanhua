"""Headless adapters for the pinned, locally patched AINiee checkout.

No global AINiee configuration is read or written. Run with its Python venv.
Imported AINiee code retains its own AGPL-3.0 license (Tools/AINiee/LICENSE).
"""
from collections import Counter, OrderedDict
import copy
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import regex
import subprocess
import sys
import threading
from workflow_profile import profiled, increment

ROOT = Path(__file__).resolve().parents[2]
AINIEE = ROOT / 'Tools' / 'AINiee'
BASELINE = 'c50570c1dee7df7bd51316a253f0b42d10a8ca4c'
if str(AINIEE) not in sys.path:
    sys.path.insert(0, str(AINIEE))


def load_script(name):
    path = ROOT / '.agents/skills/game-translate/scripts' / (name + '.py')
    spec = importlib.util.spec_from_file_location('shh_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def helper():
    from ModuleFolders.Domain.PromptBuilder.GlossaryHelper import GlossaryHelper
    return GlossaryHelper


def provenance():
    paths = ['Domain/PromptBuilder/GlossaryHelper.py', 'Domain/TextProcessor/TextProcessor.py',
             'Infrastructure/LLMRequester/LLMClientFactory.py', 'Infrastructure/LLMRequester/OpenaiRequester.py']
    gitdir = AINIEE / '.git'
    if gitdir.is_file():
        gitdir = (AINIEE / gitdir.read_text(encoding='utf-8').strip().split(':', 1)[1].strip()).resolve()
    head = gitdir / 'HEAD'
    ref = head.read_text(encoding='utf-8').strip()
    files = [AINIEE / 'ModuleFolders' / p for p in paths] + [head, gitdir / 'packed-refs']
    if ref.startswith('ref: '):
        files.append(gitdir / ref[5:])
    signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_ctime_ns, p.stat().st_size)
                      if p.exists() else (str(p), None) for p in files)
    return copy.deepcopy(_provenance(signature))


@lru_cache(maxsize=4)
def _provenance(signature):
    result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=AINIEE,
                            capture_output=True, text=True, check=True)
    paths = ['Domain/PromptBuilder/GlossaryHelper.py', 'Domain/TextProcessor/TextProcessor.py',
             'Infrastructure/LLMRequester/LLMClientFactory.py', 'Infrastructure/LLMRequester/OpenaiRequester.py']
    return {'expected_commit': BASELINE, 'actual_commit': result.stdout.strip(),
            'modules': {p: hashlib.sha256((AINIEE / 'ModuleFolders' / p).read_bytes()).hexdigest()
                        for p in paths}, 'license': 'AGPL-3.0; Tools/AINiee/LICENSE'}


def glossary_rows(analysis):
    rows = []
    for table in ('characters', 'terms', 'non_translate'):
        for index, row in enumerate(analysis.get(table, [])):
            rows.append({**row, 'ref': f'{table}:{index}', 'src': row['source'],
                         'dst': row.get('recommended_translation', '保留原文'),
                         'src_state': row.get('src_state', 'valid')})
    return rows


_FROZEN_MATCHERS = {}
_MATCH_CONTEXTS = OrderedDict()
_MATCH_LOCK = threading.RLock()
TERM_MATCH_VERSION = 3


def _visible_term_match(start, end, protected_spans):
    # A whole protected marker may itself be an explicit glossary entry. Only
    # reject partial/internal matches, before longest-span overlap resolution.
    return all(end <= a or start >= b or (start <= a and end >= b)
               for a, b in protected_spans)


@lru_cache(maxsize=32)
def _default_term_rules(named_curly, exclusions_json, overrides_json):
    return tuple(patterns(named_curly, json.loads(exclusions_json), json.loads(overrides_json)))


class _PreparedRows(list):
    """Normalized frozen rows, shared read-only by the matching helper."""


def _frozen_matcher(helper_class):
    matcher = _FROZEN_MATCHERS.get(helper_class)
    if matcher is None:
        # Keep one subclass per helper class so its cached compiled search patterns
        # are reused across records during full-project validation.
        class FrozenMatcher(helper_class):
            @classmethod
            def normalize_row(cls, row):
                normalized = super().normalize_row(row)
                # Frozen source strings are literal unless their author explicitly
                # marked a regex. Punctuation in game text is not regex syntax.
                stored = row.get(cls.VALID_KEY) if isinstance(row, dict) else None
                if stored in (cls.STATE_VALID, cls.STATE_REGEX, cls.STATE_INVALID):
                    normalized[cls.VALID_KEY] = stored
                return normalized

            @classmethod
            def normalize_rows(cls, rows):
                return rows if isinstance(rows, _PreparedRows) else super().normalize_rows(rows)

            @classmethod
            def get_source_state(cls, source_text):
                # Game identifiers and named/alternative markers are literal text.
                # Exclude regex class syntax (ranges, escapes, negation); let the
                # pinned helper retain its existing inference for everything else.
                source_text = cls._normalize_text(source_text)
                if re.fullmatch(r'\[[A-Za-z][A-Za-z0-9]*(?:(?::|/)[A-Za-z][A-Za-z0-9 /:]*)?\]',
                                source_text):
                    return cls.STATE_VALID
                return super().get_source_state(source_text)

            @classmethod
            def unify_term_family_translations(cls, rows, *args, **kwargs):
                return [dict(row) for row in rows or []]

            @classmethod
            @lru_cache(maxsize=8192)
            def build_search_pattern(cls, source_text, source_state=None, case_sensitive=False, whole_word=False):
                source_text = cls._normalize_text(source_text)
                state = source_state if source_state is not None else cls.get_source_state(source_text)
                pattern = super().build_search_pattern(source_text, state, case_sensitive, whole_word)
                if pattern is None or not whole_word or state == cls.STATE_REGEX:
                    return pattern
                # An apostrophe inside a contraction is not a word boundary.
                # Preserve ordinary quotes and the possessive Don's / Don’s.
                left = r"(?<![A-Za-z]['’])" if re.match(r'[A-Za-z]', source_text) else ''
                right = r"(?!['’](?![sS](?!\w))[A-Za-z])" if re.search(r'[A-Za-z]$', source_text) else ''
                return regex.compile(left + '(?:' + pattern.pattern + ')' + right, pattern.flags)

            @classmethod
            def collect_matched_rows(cls, rows, input_dict, include_invalid=False,
                                     case_sensitive=False, whole_word=False, *, protected_spans=()):
                text = '\n'.join(input_dict.values()) if isinstance(input_dict, dict) else ''
                candidates = []
                for priority, row in enumerate(cls.normalize_rows(rows)):
                    if cls.is_keep_original_translation(row.get('dst', '')):
                        continue
                    state = row.get(cls.VALID_KEY, cls.STATE_VALID)
                    if state == cls.STATE_INVALID:
                        if not include_invalid:
                            continue
                        state = cls.STATE_VALID
                    pattern = cls.build_search_pattern(row.get('src', ''), state, case_sensitive, whole_word)
                    for match in pattern.finditer(text) if pattern is not None else ():
                        if match.start() != match.end() and _visible_term_match(match.start(), match.end(), protected_spans):
                            candidates.append({'start': match.start(), 'end': match.end(),
                                               'priority': priority, 'match_text': match.group(0), 'row': row})
                matched, seen = [], set()
                for candidate in cls.resolve_overlapping_matches(candidates):
                    row = dict(candidate['row'], src=candidate['match_text'])
                    row['dst'] = cls.normalize_translation(row.get('dst', ''))
                    key = (row['src'] if case_sensitive else row['src'].casefold(), row['dst'])
                    if key not in seen:
                        seen.add(key)
                        matched.append(row)
                return matched

        matcher = FrozenMatcher
        _FROZEN_MATCHERS[helper_class] = matcher
    return matcher


@profiled('term_match')
def matched_terms(analysis, texts, options, *, rules=None):
    h = helper()
    # Frozen analysis objects are immutable. Keep a bounded context per snapshot;
    # callers changing a glossary must load a new snapshot object.
    key = (id(analysis), h)
    with _MATCH_LOCK:
        context = _MATCH_CONTEXTS.get(key)
        if context is None:
            matcher = _frozen_matcher(h)
            raw_rows = glossary_rows(analysis)
            rows = _PreparedRows(matcher.normalize_rows(raw_rows))
            context = (analysis, raw_rows, rows, OrderedDict(), {})
            _MATCH_CONTEXTS[key] = context
            if len(_MATCH_CONTEXTS) > 4:
                _MATCH_CONTEXTS.popitem(last=False)
    _, raw_rows, rows, results, plans = context
    texts = tuple(texts)
    if rules is None:
        # Workflow callers pass their actual rules (including corpus-level curly
        # choice detection). Standalone callers must explicitly enable ambiguous
        # named-curly protection rather than hide player choices by default.
        rules = _default_term_rules(options.get('protect_named_curly') is True,
            json.dumps(options.get('exclusions', []), sort_keys=True),
            json.dumps(options.get('placeholder_family_overrides', {}), sort_keys=True))
    rules = tuple(rules)
    match_key = (texts, options['case_sensitive'], options['whole_word'], rules)
    with _MATCH_LOCK:
        if match_key in results:
            increment('term_cache_hits')
            results.move_to_end(match_key)
            return copy.deepcopy(results[match_key])
    increment('term_cache_misses')
    # Reuse literal/quote/boundary/overlap matching, but frozen rows are authoritative.
    # AINiee's automatic family unification can merge different meanings (Guards/Guard).
    FrozenMatcher = _frozen_matcher(h)
    plan_key = (options['case_sensitive'], options['whole_word'])
    with _MATCH_LOCK:
        plan = plans.get(plan_key)
        if plan is None:
            # Classification previously called regex-based keep-original checks
            # twice for every row of every sentence. Prepare once per snapshot.
            normal, kept = [], []
            for priority, row in enumerate(rows):
                if not row.get('src') or h.is_keep_original_translation(row.get('dst', '')):
                    continue
                state = row.get(h.VALID_KEY, h.STATE_VALID)
                if state == h.STATE_INVALID:
                    continue
                pattern = FrozenMatcher.build_search_pattern(row['src'], state, *plan_key)
                if pattern is not None:
                    normal.append((priority, row, pattern))
            for row in raw_rows:
                if h.is_keep_original_translation(row['dst']):
                    pattern = FrozenMatcher.build_search_pattern(row['src'], row['src_state'], *plan_key)
                    if pattern is not None:
                        kept.append((row, pattern))
            plan = plans[plan_key] = (normal, kept)
            increment('term_plans_built')
    full_text = '\n'.join(texts)
    protected_spans = tuple({match.span() for _, pattern in rules for match in pattern.finditer(full_text)
                             if match.start() != match.end()})
    candidates = []
    for priority, row, pattern in plan[0]:
        for match in pattern.finditer(full_text):
            if match.start() != match.end() and _visible_term_match(match.start(), match.end(), protected_spans):
                candidates.append({'start': match.start(), 'end': match.end(), 'priority': priority,
                                   'match_text': match.group(0), 'row': row})
    matched, seen = [], set()
    for candidate in FrozenMatcher.resolve_overlapping_matches(candidates):
        row = dict(candidate['row'], src=candidate['match_text'])
        row['dst'] = FrozenMatcher.normalize_translation(row.get('dst', ''))
        key = (row['src'] if options['case_sensitive'] else row['src'].casefold(), row['dst'])
        if key not in seen:
            seen.add(key)
            matched.append(row)
    # Keep-original entries still convey useful instructions, but are not term-check errors.
    for row, pattern in plan[1]:
        if any(_visible_term_match(m.start(), m.end(), protected_spans)
               for m in pattern.finditer(full_text) if m.start() != m.end()):
            matched.append(copy.deepcopy(row))
    with _MATCH_LOCK:
        results[match_key] = copy.deepcopy(matched)
        if len(results) > 32768:
            results.popitem(last=False)
    return matched


def record_matched_terms(analysis, row, config, rules, cache):
    """Share record-bound protection with final export, including its cache key."""
    actual_rules = tuple(record_rules(row, config, rules))
    key = (row['source'], actual_rules)
    if key not in cache:
        cache[key] = matched_terms(analysis, [row['source']], config, rules=actual_rules)
    return cache[key]


def patterns(named_curly=True, exclusions=(), family_overrides=None):
    module = load_script('analyze_placeholders')
    overrides = family_overrides or {}
    names = {name for name, _, _ in module.FAMILIES}
    if not isinstance(overrides, dict) or any(name not in names for name in overrides):
        raise ValueError('Unknown placeholder family override')
    result = []
    for name, pattern, _ in module.FAMILIES:
        if name == 'curly_named' and not named_curly:
            continue
        if name in overrides:
            expression = overrides[name]
            if expression is None:
                continue
            if not isinstance(expression, str) or not expression:
                raise ValueError('Placeholder family override must be a non-empty regex or null')
            pattern = re.compile(expression)
        result.append((name, pattern))
    for index, item in enumerate(exclusions):
        expression = item.get('regex') or re.escape(item['markers'])
        result.append((f'exclusion_{index}', re.compile(expression)))
    return result


def protect(text, record_id, rules):
    # The upstream protector has a batch-wide 50-marker cap and fixed [P<n>] names.
    # Reuse its patterns/restorer, with unbounded, non-colliding task-local identities.
    candidates = sorted({(m.start(), m.end()) for _, p in rules for m in p.finditer(text)
                         if m.start() != m.end()}, key=lambda s: (-(s[1] - s[0]), s[0]))
    selected = []
    for start, end in candidates:
        if not any(start < b and end > a for a, b in selected):
            selected.append((start, end))
    selected.sort()
    namespace = 'P'
    while re.search(r'\[' + re.escape(namespace) + r'\d+\]', text):
        namespace += 'P'
    parts, mapping, pos = [], [], 0
    for index, (start, end) in enumerate(selected):
        token = f'[{namespace}{index + 1}]'
        parts.extend([text[pos:start], token])
        mapping.append({'placeholder': token, 'original': text[start:end]})
        pos = end
    parts.append(text[pos:])
    return ''.join(parts), mapping


def restore(text, mapping, *, allow_original=False):
    # Repair candidates are shown with their original tags/variables restored.
    # A model may preserve those exact literals instead of re-encoding them as
    # transport markers. Accept that already-restored representation only when
    # every mapped literal has its exact expected multiplicity, no known marker
    # remains, and no fabricated transport marker is present. Structural checks
    # still run against the original source after this function.
    if allow_original and mapping and all(item['placeholder'] not in text for item in mapping):
        expected = Counter(item['original'] for item in mapping)
        marker = re.fullmatch(r'\[(P+)\d+\]', mapping[0]['placeholder'])
        fabricated = (re.search(r'⟪SHH_[^⟫]*⟫', text) or
                      (marker and re.search(r'\[' + marker[1] + r'\d+\]', text)))
        if not fabricated and all(text.count(original) == count for original, count in expected.items()):
            return text
    for item in mapping:
        if text.count(item['placeholder']) != 1:
            raise ValueError('Protected token missing or repeated: ' + item['placeholder'])
    from ModuleFolders.Domain.TextProcessor.TextProcessor import TextProcessor
    # This method is stateless; no config/resource initialization is needed.
    processor = TextProcessor.__new__(TextProcessor)
    restored = processor._restore_special_placeholders({'0': text}, {'0': mapping})['0']
    if re.search(r'⟪SHH_[^⟫]*⟫', restored):
        raise ValueError('Unrestored or fabricated protected token')
    if mapping:
        marker = re.fullmatch(r'\[(P+)\d+\]', mapping[0]['placeholder'])
        if marker and re.search(r'\[' + marker[1] + r'\d+\]', restored):
            raise ValueError('Unrestored or fabricated protected token')
    return restored


def normalize_exception_sources(exceptions, terms, case_sensitive):
    """Normalize syntax only; ordinary meaning remains the model's explicit claim."""
    if isinstance(exceptions, dict):
        exceptions = [exceptions]
    if not isinstance(exceptions, list):
        raise ValueError('Context exceptions must be a list or a single object')
    known = {t['src'] for t in terms}
    normalized = []
    for item in exceptions:
        if not isinstance(item, dict):
            raise ValueError('Context exception must be an object')
        entry = dict(item)
        source = entry.get('source', entry.get('src'))
        reason = entry.get('reason')
        if not isinstance(source, str) or not source.strip() or not isinstance(reason, str) or not reason.strip():
            raise ValueError('Context exceptions need source and reason')
        source = source.strip()
        entry['source'], entry['reason'] = source, reason.strip()
        entry.pop('src', None)
        if not case_sensitive and source not in known and source.isascii():
            matches = [s for s in known if s.isascii() and s.casefold() == source.casefold()]
            if len(matches) == 1:
                entry['source'] = matches[0]
        # Unknown/ambiguous keys stay unchanged so existing relatedness checks reject them.
        normalized.append(entry)
    return normalized


def record_constraint(row, config):
    constraint = config.get('record_constraints', {}).get(row['id'], {})
    if constraint and hashlib.sha256(row['source'].encode('utf-8')).hexdigest() != constraint['source_sha256']:
        raise ValueError('Record constraint source changed: ' + row['id'])
    return constraint


def record_rules(row, config, rules):
    constraint = record_constraint(row, config)
    suffix = constraint.get('literal_suffix')
    if suffix is None:
        return rules
    if not suffix or not row['source'].endswith(suffix):
        raise ValueError('Protected suffix does not match source: ' + row['id'])
    return [*rules, ('record_literal_suffix', re.compile(re.escape(suffix) + r'\Z'))]


def record_structural_issues(row, translation, rules, config):
    return structural_issues(row['source'], translation, record_rules(row, config, rules),
                             record_constraint(row, config).get('physical_newlines'))


def structural_issues(source, translation, rules, expected_newlines=None):
    issues = []
    if source.strip() and not translation.strip():
        issues.append('empty_translation')
    if not source.strip() and translation.strip():
        issues.append('invented_translation_for_blank_source')
    source_edges = (len(source) - len(source.lstrip(' \t')),
                    len(source) - len(source.rstrip(' \t')))
    translation_edges = (len(translation) - len(translation.lstrip(' \t')),
                         len(translation) - len(translation.rstrip(' \t')))
    if source_edges != translation_edges:
        issues.append('boundary_whitespace')
    for name, pattern in rules:
        # finditer.group(0), not findall: captures in format patterns are not the full tag.
        originals = Counter(m.group(0) for m in pattern.finditer(source))
        destination_pattern = pattern
        # Identifier boundaries describe Latin variable keys, not translated prose.
        # Unicode \b otherwise loses intact XX/RationsLost when Chinese touches it.
        # Keep source discovery and non-identifier/Unicode exclusion rules unchanged.
        if (name.startswith('exclusion_') and '\\b' in pattern.pattern and pattern.pattern.isascii()
                and '(?u' not in pattern.pattern
                and all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', token) for token in originals)):
            destination_pattern = re.compile(pattern.pattern, (pattern.flags & ~re.UNICODE) | re.ASCII)
        if originals != Counter(m.group(0) for m in destination_pattern.finditer(translation)):
            issues.append(name)
    expected = re.findall(r'\r\n|\r|\n', source) if expected_newlines is None else expected_newlines
    if expected != re.findall(r'\r\n|\r|\n', translation):
        issues.append('physical_newlines')
    return issues


class ApiFailure(Exception):
    def __init__(self, code, retryable=False, usage=None):
        super().__init__(code)
        self.retryable = retryable
        self.usage = usage


def collect_api_stream(response):
    """Join final-answer deltas only; require a real terminal chunk.

    Usage is cumulative provider data, not a sum of chunk-level snapshots.
    Reasoning deltas remain separate and never enter the translation JSON.
    """
    content, finish, model, usage = [], None, None, None
    def metadata():
        value = {'usage_reported': usage is not None, 'finish_reason': finish,
                 'response_model': model, 'response_transport': 'stream'}
        if usage is not None:
            for key in ('prompt_tokens', 'completion_tokens', 'total_tokens',
                        'prompt_tokens_details', 'completion_tokens_details'):
                item = getattr(usage, key, None)
                if item is not None:
                    value[key] = item.model_dump() if hasattr(item, 'model_dump') else item
        return value
    try:
        for chunk in response:
            model = getattr(chunk, 'model', None) or model
            usage = getattr(chunk, 'usage', None) or usage
            for choice in chunk.choices:
                if getattr(choice, 'index', 0) != 0:
                    raise ValueError('Unexpected additional stream choice')
                part = getattr(choice.delta, 'content', None)
                if part is not None:
                    if not isinstance(part, str):
                        raise ValueError('Stream content must be text')
                    content.append(part)
                finish = getattr(choice, 'finish_reason', None) or finish
        if finish is None:
            raise ApiFailure('incomplete_stream', True, usage=metadata())
        return ''.join(content), metadata()
    except ApiFailure:
        raise
    except Exception:
        raise ApiFailure('stream_interrupted', True, usage=metadata()) from None
    finally:
        response.close()


class AINieeAPI:
    """Reuse patched client factory, provider parameters and SSE parsing.

    First supported transport: OpenAI-compatible Chat Completions (including
    DeepSeek/custom gateways). Native provider adapters can be added separately.
    SDK retries disabled: the workflow owns bounded retries and request accounting.
    """
    def __init__(self, settings, key):
        from ModuleFolders.Infrastructure.LLMRequester.LLMClientFactory import LLMClientFactory
        from ModuleFolders.Infrastructure.LLMRequester.OpenaiRequester import OpenaiRequester
        self.settings = {**settings, 'api_key': key}
        self.factory = LLMClientFactory()
        self.client = self.factory.get_openai_client(self.settings).with_options(max_retries=0)
        self.parser = OpenaiRequester()

    def request(self, system, user):
        settings = self.settings
        params = {'model': settings['model_name'], 'messages': [
            {'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
            'stream': settings.get('stream', False), 'timeout': settings.get('request_timeout', 120),
            'extra_body': settings.get('extra_body', {})}
        if settings.get('temperature', 1) != 1:
            params['temperature'] = settings['temperature']
        if settings.get('max_completion_tokens'):
            params['max_completion_tokens'] = settings['max_completion_tokens']
        params = self.parser.apply_platform_thinking_params(params, settings)
        if params['stream']:
            params['stream_options'] = {'include_usage': True}
        try:
            raw = self.client.chat.completions.with_raw_response.create(**params)
            content_type = raw.headers.get('content-type', '')
            if isinstance(content_type, str) and 'text/html' in content_type.lower():
                # Some gateway homepages return HTTP 200 for an incorrect API
                # route. This is not a model's empty reply or a transient SSE
                # failure; retrying the same address cannot repair the route.
                raise ApiFailure('unexpected_html_response', False, usage={'usage_reported': False})
            try:
                response = raw.parse()
                if params['stream']:
                    content, token_usage = collect_api_stream(response)
                    if not content:
                        detail = token_usage.get('completion_tokens_details') or {}
                        code = ('reasoning_budget_exhausted' if token_usage.get('finish_reason') == 'length'
                                and detail.get('reasoning_tokens', 0) else 'empty_response')
                        raise ApiFailure(code, code == 'empty_response', usage=token_usage)
                    return content, token_usage
                content = response.choices[0].message.content
                usage = response.usage
                token_usage = ({'prompt_tokens': usage.prompt_tokens, 'completion_tokens': usage.completion_tokens,
                                'usage_reported': True} if usage else {'usage_reported': False})
                token_usage['finish_reason'] = getattr(response.choices[0], 'finish_reason', None)
                token_usage['response_model'] = getattr(response, 'model', None)
                if usage:
                    total = getattr(usage, 'total_tokens', None)
                    if total is not None:
                        token_usage['total_tokens'] = total
                    for key in ('prompt_tokens_details', 'completion_tokens_details'):
                        detail = getattr(usage, key, None)
                        if detail is not None:
                            token_usage[key] = detail.model_dump() if hasattr(detail, 'model_dump') else detail
            except (ValueError, AttributeError, IndexError, TypeError):
                _, content, prompt, completion = self.parser._parse_sse_response(raw.text)
                token_usage = {'prompt_tokens': prompt, 'completion_tokens': completion,
                               'usage_reported': bool(prompt or completion), 'finish_reason': None,
                               'response_transport': 'sse_fallback'}
            if not content:
                detail = token_usage.get('completion_tokens_details') or {}
                if token_usage.get('finish_reason') == 'length' and detail.get('reasoning_tokens', 0):
                    # Retrying the same reasoning-only exhaustion blindly can
                    # repeatedly spend the full completion budget for no result.
                    raise ApiFailure('reasoning_budget_exhausted', False, usage=token_usage)
                raise ApiFailure('empty_response', True, usage=token_usage)
            return content, token_usage
        except ApiFailure:
            raise
        except Exception as error:
            # Do not retain messages, URLs, headers or exception strings containing secrets.
            status = getattr(error, 'status_code', None)
            retryable = status in (408, 409, 429) or (isinstance(status, int) and status >= 500)
            retryable = retryable or type(error).__name__ in ('APITimeoutError', 'APIConnectionError')
            raise ApiFailure(f'{type(error).__name__}:{status or "transport"}', retryable) from None

    def close(self):
        self.factory.close_all_clients()


def parse_response(content, audit_file=None):
    # Strict ID-based JSON protocol; never infer IDs from numbered prose.
    from workflow_api_reliability import parse_json_reply
    return parse_json_reply(content, audit_file)
