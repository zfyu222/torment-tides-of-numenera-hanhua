import unittest

import test_translation_workflow as fixtures


class DirectQualityTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkflowTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        self.f.freeze(True); self.f.translate()
        self.flow = self.f.flow
        self.flow.prepare('review')
        while claim := self.flow.claim('review', self.f.fresh_worker('review')):
            rows = []
            for r in claim['payload']['records']:
                item = {'id': r['id'], 'translation': r['translation'], 'reviewed': True,
                        'reason': 'Actual synthetic review', **self.f.review_evidence(r)}
                if r['source'] == 'text':
                    item['issues'] = [{'severity': 'warning', 'reason': 'Synthetic label context warning'}]
                rows.append(item)
            self.flow.submit(claim['task_id'], claim['lease_token'], {**self.f.envelope(claim), 'records': rows})
        self.assertTrue(self.flow.review_scan()['clean'])
        r = self.flow.quality_report('final')
        from translation_workflow import read_json
        report = read_json(r['report_file'])
        self.decisions = {'report_hash': report['report_hash'], 'reviewer': 'main:user-authorized',
                          'user_authorization': 'User explicitly requested direct resolution of few remaining checks.',
                          'summary': 'Read the one synthetic warning and its source.',
                          'decisions': [{'id': i, 'disposition': 'contextual', 'reason': 'The source is a label; no extra context is asserted.'}
                                        for i in report['required_decisions']]}

    def test_direct_round_records_real_identity_and_closes_normally(self):
        saved = self.flow.record_direct_quality_round(self.decisions)
        self.assertEqual(saved['remaining_checks'], 0)
        self.assertEqual(self.flow.finish_sol_round()['status'], 'approved')
        with self.flow.db() as db:
            approved = self.flow.require_final_approval(db, self.flow.config(db))
            self.assertEqual(approved['reviewer'], 'main:user-authorized')

    def test_direct_without_authorization_and_legacy_impersonation_rejected(self):
        missing = dict(self.decisions); missing.pop('user_authorization')
        with self.assertRaisesRegex(ValueError, 'authorization'):
            self.flow.record_direct_quality_round(missing)
        with self.assertRaisesRegex(ValueError, 'Sol checks'):
            self.flow.record_sol_round(self.decisions)

    def test_stale_report_rejected(self):
        stale = dict(self.decisions, report_hash='stale')
        with self.assertRaisesRegex(ValueError, 'current round'):
            self.flow.record_direct_quality_round(stale)


if __name__ == '__main__':
    unittest.main()
