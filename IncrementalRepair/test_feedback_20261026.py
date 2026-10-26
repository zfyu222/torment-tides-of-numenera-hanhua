"""Offline protection/scope regression using the actual reviewed feedback data."""
import unittest
import repair
from feedback_20261026 import WORK


class FeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = repair.w.read_json(WORK / 'baseline.json')['config']
        cls.old = repair.w.read_json(WORK / 'old_glossary.json')
        cls.new = repair.w.read_json(WORK / 'new_glossary.json')
        cls.rules = repair.bridge.patterns(cls.config['protect_named_curly'] is not False, cls.config['exclusions'], cls.config.get('placeholder_family_overrides'))

    def terms(self, glossary, text):
        return repair.bridge.matched_terms(glossary, [text], self.config, rules=self.rules)

    def test_test_protection_stays_for_command_but_not_ordinary_prose(self):
        self.assertTrue(any(t['src'].casefold() == 'test' for t in self.terms(self.new, 'test')))
        self.assertTrue(any(t['src'].casefold() == 'test' for t in self.terms(self.old, 'It is a test, nothing more.')))
        self.assertFalse(any(t['src'].casefold() == 'test' for t in self.terms(self.new, 'It is a test, nothing more.')))

    def test_visible_truth_tag_is_translatable_while_real_comment_is_unchanged(self):
        self.assertTrue(any(t['src'] == '(Truth)' for t in self.terms(self.old, '(Truth) "Yes."')))
        self.assertFalse(any(t['src'] == '(Truth)' for t in self.terms(self.new, '(Truth) "Yes."')))
        source = '{SCRIPT: test this node}'
        protected, mapping = repair.bridge.protect(source, 'test-record', self.rules)
        self.assertEqual(repair.bridge.restore(protected, mapping), source)

    def test_candidate_contains_only_the_reviewed_21_record_changes(self):
        plan = repair.w.read_json(WORK / 'repair_plan.json')
        self.assertEqual(len(plan['scope_ids']), 21)
        original = repair.w.read_json(WORK / 'records.json')
        candidate = repair.read_column(WORK / 'torment-tides-of-numenera_text_translated_candidate.csv')
        self.assertEqual(len(original), len(candidate))
        changed = {r['id'] for r, t in zip(original, candidate) if r['translation'] != t}
        self.assertEqual(changed, set(plan['scope_ids']))
        self.assertFalse(any('努曼内拉' in t or '(Truth)' in t for t in candidate))


if __name__ == '__main__': unittest.main()
