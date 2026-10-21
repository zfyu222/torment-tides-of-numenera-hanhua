import hashlib
import unittest
import ainiee_bridge as bridge
from workflow_review_rounds import ReviewRoundMixin
import test_translation_workflow as fixtures


class RecordConstraintTests(unittest.TestCase):
    def config(self, row, **rules):
        return {'record_constraints': {row['id']: {
            'source_sha256': hashlib.sha256(row['source'].encode()).hexdigest(),
            'reason': 'Verified game-specific constraint', **rules}}}

    def test_newlines_are_explicit_and_source_bound(self):
        row = {'id': 'test', 'source': 'One two three.'}
        config = self.config(row, physical_newlines=['\r\n', '\r\n'])
        self.assertEqual(bridge.record_structural_issues(row, '一\r\n二\r\n三', [], config), [])
        for wrong in ('一二三', '一\n二\n三', '一\r\n二'):
            self.assertIn('physical_newlines', bridge.record_structural_issues(row, wrong, [], config))
        other = dict(row, id='other')
        self.assertIn('physical_newlines', bridge.record_structural_issues(other, '一\r\n二\r\n三', [], config))
        with self.assertRaisesRegex(ValueError, 'source changed'):
            bridge.record_structural_issues(dict(row, source='different'), '译文', [], config)

    def test_malformed_comment_is_protected_exactly_without_repairing_source(self):
        suffix = '{NATHAN: player action without closing brace.'
        row = {'id': 'test', 'source': 'Narrative.\r\n' + suffix}
        config = self.config(row, literal_suffix=suffix)
        rules = bridge.record_rules(row, config, [])
        text, mapping = bridge.protect(row['source'], row['id'], rules)
        self.assertEqual(text, 'Narrative.\r\n[P1]')
        self.assertEqual(bridge.restore(text, mapping), row['source'])
        good = '叙述。\r\n' + suffix
        self.assertEqual(bridge.record_structural_issues(row, good, [], config), [])
        self.assertIn('record_literal_suffix', bridge.record_structural_issues(row, good + '}', [], config))
        analysis = {'terms': [{'source': 'player', 'recommended_translation': '玩家'}]}
        self.assertEqual(bridge.matched_terms(analysis, [row['source']],
            {'case_sensitive': False, 'whole_word': True}, rules=rules), [])

    def test_api_escalation_preserves_tier_and_limits(self):
        route = ReviewRoundMixin.repair_routing({'escalation_backend': 'api'}, 'sol')
        self.assertEqual(route['repair_tier'], 'sol')
        self.assertEqual(route['escalation_backend'], 'api')
        self.assertIsNone(route['required_model'])
        self.assertEqual(route['repair_round_limit'], 6)
        self.assertTrue(route['automatic_escalation'])
        self.assertEqual(ReviewRoundMixin.repair_routing({}, 'sol')['required_model'], 'gpt-6-sol')

    def test_configure_retains_drafts_and_rejects_wrong_source_hash(self):
        f = fixtures.WorkflowTests(); f.setUp(); self.addCleanup(f.tearDown)
        f.freeze(True); f.translate(); flow = f.flow
        with flow.db() as db:
            before = [tuple(r) for r in db.execute('select id,stage,translation from records order by ordinal')]
            row = dict(db.execute('select id,source from records order by ordinal limit 1').fetchone())
        flow.pause(True)
        patch = self.config(row, physical_newlines=[])
        patch['escalation_backend'] = 'api'
        flow.configure(patch, 'Verified layout rule and explicit API executor', impact='none')
        with flow.db() as db:
            self.assertEqual(before, [tuple(r) for r in db.execute('select id,stage,translation from records order by ordinal')])
        patch['record_constraints'][row['id']]['source_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'source changed'):
            flow.configure(patch, 'Reject mismatched constraint', impact='none')


if __name__ == '__main__':
    unittest.main()
