"""Project-only literal prefilter; shared matcher still resolves every candidate."""
from functools import lru_cache
import re
import repair


@lru_cache(maxsize=256)
def ascii_text(text):
    return text.lower() if text.isascii() else None


class LiteralGuard:
    def __init__(self, pattern, keyword):
        self.wrapped = pattern; self.keyword = keyword

    def finditer(self, text):
        lower = ascii_text(text)
        if lower is not None and self.keyword not in lower:
            return iter(())
        return self.wrapped.finditer(text)


def prepare(analysis, config, rules):
    repair.bridge.matched_terms(analysis, [''], config, rules=rules)
    h = repair.bridge.helper()
    _, _, _, results, plans = repair.bridge._term_context(analysis, h)
    key = (config['case_sensitive'], config['whole_word'])
    normal, kept = plans[key]
    def guard(row, pattern):
        if isinstance(pattern, LiteralGuard) or row.get(h.VALID_KEY) != h.STATE_VALID:
            return pattern
        # For an explicitly literal ASCII source, these letters must occur in
        # every ASCII match. Regex sources and all non-ASCII input use the full
        # original matcher; no word-boundary, scope or protection inference.
        source = row['src']
        if not source.isascii(): return pattern
        words = re.findall(r'[A-Za-z0-9]+', source)
        if not words: return pattern
        return LiteralGuard(pattern, max(words, key=len).lower())
    plans[key] = ([(i, row, guard(row, p)) for i, row, p in normal],
                  [(row, guard(row, p)) for row, p in kept])
    results.clear()
