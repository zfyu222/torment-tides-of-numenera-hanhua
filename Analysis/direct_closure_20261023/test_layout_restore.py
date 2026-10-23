import copy
import json
import unittest

import test_translation_workflow as fixtures
import translation_workflow as workflow
from workflow_layout_restore import restore_exact_layout, restore_review_layout, text_hash


class LayoutRestoreTests(unittest.TestCase):
    def test_only_line_endings_and_edges_change(self):
        source = 'English.\r\n\r\nSecond.  '
        candidate = '中文。\n\n第二段。'
        self.assertEqual(restore_exact_layout(source, candidate), '中文。\r\n\r\n第二段。  ')
        self.assertEqual(restore_exact_layout('x\n', '中\r\n'), '中\n')
        with self.assertRaisesRegex(ValueError, 'Paragraph count'):
            restore_exact_layout(source, '中文。第二段。')

    def fixture(self):
        f = fixtures.WorkflowTests(); f.setUp(); self.addCleanup(f.tearDown)
        f.freeze(True); f.translate(); f.review()
        flow = f.flow
        with flow.db() as db:
            row = db.execute('SELECT * FROM records WHERE source="text"').fetchone()
            c = db.execute('SELECT * FROM review_candidates WHERE record_id=?', (row['id'],)).fetchone()
            item = json.loads(c['item']); prior = item['translation']
            item['translation'] += ' '
            item['changes'] = [{'before': prior, 'after': item['translation'], 'category': 'placeholders',
                               'severity': 'minor', 'reason': 'Synthetic incorrect layout edit', 'source_excerpt': 'text'}]
            task = db.execute('SELECT * FROM tasks WHERE id=?', (c['task_id'],)).fetchone()
            result = json.loads(task['result'])
            result['records'] = [item if x['id'] == row['id'] else x for x in result['records']]
            db.execute('UPDATE tasks SET result=? WHERE id=?', (workflow.encoded(result), task['id']))
            raw = workflow.encoded(item)
            db.execute('UPDATE review_candidates SET item=?,status="failed",diagnostic=? WHERE record_id=?',
                       (raw, 'structural mismatch boundary_whitespace', row['id']))
            db.execute('UPDATE records SET stage="translate" WHERE id=?', (row['id'],))
            request = {'reviewer': 'user-authorized-direct-layout', 'reason': 'Fix remaining mechanical layout only',
                       'records': [{'id': row['id'], 'source_sha256': text_hash(row['source']), 'candidate_sha256': text_hash(raw)}]}
        flow.pause(True)
        return flow, request, prior

    def test_restore_rechecks_gates_keeps_attempts_and_records_attribution(self):
        flow, request, prior = self.fixture()
        with flow.db() as db:
            attempts = [tuple(r) for r in db.execute('SELECT id,attempt FROM tasks ORDER BY id')]
        restored = restore_review_layout(flow, request)
        self.assertEqual(restored['status'], 'pending_revalidation')
        with flow.db() as db:
            self.assertEqual(attempts, [tuple(r) for r in db.execute('SELECT id,attempt FROM tasks ORDER BY id')])
            self.assertEqual(db.execute('SELECT stage FROM records WHERE id=?', (request['records'][0]['id'],)).fetchone()[0], 'translate')
        self.assertTrue(flow.review_scan()['clean'])
        with flow.db() as db:
            value = db.execute('SELECT translation FROM records WHERE id=?', (request['records'][0]['id'],)).fetchone()[0]
            self.assertEqual(value, prior)
            review = flow.latest_reviews(db, 'final')[request['records'][0]['id']]
            self.assertEqual(review['translation'], prior)
            self.assertEqual(review['layout_restoration']['reviewer'], request['reviewer'])

    def test_stale_binding_is_rejected_without_overwriting_result(self):
        flow, request, _ = self.fixture()
        stale = copy.deepcopy(request); stale['records'][0]['candidate_sha256'] = '0' * 64
        with flow.db() as db:
            before = [tuple(r) for r in db.execute('SELECT * FROM review_candidates')]
        with self.assertRaisesRegex(ValueError, 'Stale'):
            restore_review_layout(flow, stale)
        with flow.db() as db:
            self.assertEqual(before, [tuple(r) for r in db.execute('SELECT * FROM review_candidates')])


if __name__ == '__main__':
    unittest.main()
