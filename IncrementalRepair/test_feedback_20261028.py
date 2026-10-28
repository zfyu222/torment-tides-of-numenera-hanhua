import unittest
from unittest.mock import patch

import feedback_20261028 as feedback
import repair


class FeedbackRegression(unittest.TestCase):
    def test_scoped_protection_does_not_capture_literal_names_or_separator(self):
        for source in ('|', 'Si|ver', '(|Hope & Sorrow|)', '[Actor Name]', 'Success nodes'):
            self.assertFalse(feedback.selected_term('non_translate', {'source': source}))
        for source in ('|you|[Actor Name]|', '|need|needs|', 'success', '[Critical Success]', '[Failure]'):
            self.assertTrue(feedback.selected_term('non_translate', {'source': source}))

    def test_species_word_boundary(self):
        self.assertTrue(feedback.selected_term('terms', {'source': 'Stichus Fluid'}))
        self.assertFalse(feedback.selected_term('terms', {'source': 'a_sticha_internal'}))
        self.assertFalse(feedback.selected_term('terms', {'source': 'reflection'}))

    def validate(self, source, translated):
        r = feedback.FeedbackRepair()
        payload = {'stage': 'review', 'records': [{'id': 'a', 'source': source}]}
        result = {'records': [{'id': 'a', 'translation': translated}]}
        with patch.object(repair.Repair, 'validate_result', lambda self, p, r, g: r):
            return r.validate_result(payload, result, {})

    def test_identical_chinese_branches_remain_executable(self):
        target = '|你|[Actor Name]| |打开|打开|腔洞。'
        self.validate('|you|[Actor Name]| |open|opens| the cavity.', target)
        # The game's exact two-alternative selection operation, applied both ways.
        def select(text, player):
            return feedback.BRANCH.sub(lambda m: m.group().split('|')[1 if player else 2], text)
        self.assertEqual(select(target, True), '你 打开腔洞。')
        self.assertEqual(select(target, False), '[Actor Name] 打开腔洞。')

    def test_branch_removal_or_english_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'branch count'):
            self.validate('|you|he| |open|opens|', '你打开')
        with self.assertRaisesRegex(ValueError, 'untranslated'):
            self.validate('|you|he|', '|you|he|')

    def test_grammatical_inflection_can_become_invariant_chinese(self):
        self.validate('|you|he| |open|opens| the cavity.', '|你|他|打开腔洞。')
        self.validate('smells |seep|seeps| into |your|his| nose.', '气味渗入|你|他|的鼻腔。')

    def test_bare_actor_name_is_not_a_runtime_variable(self):
        with self.assertRaisesRegex(ValueError, 'bare Actor Name'):
            self.validate('|You|Actor Name|', '|你|Actor Name|')
        self.validate('|You|Actor Name|', '|你|他|')
        self.validate('|you|[Actor Name]|', '|你|[Actor Name]|')


if __name__ == '__main__':
    unittest.main()
