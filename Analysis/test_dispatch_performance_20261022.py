"""Dispatch query equivalence and eligibility gates; synthetic state only."""
import unittest
from unittest.mock import patch

import test_translation_workflow as fixtures
from workflow_dispatch_indexes import ensure_dispatch_indexes


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkflowTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.flow = self.f.flow
        self.flow.prepare('extract')

    def test_indexes_preserve_tasks_and_are_idempotent(self):
        with self.flow.db() as db:
            self.flow.batch_tables(db)
            before = [tuple(r) for r in db.execute('SELECT * FROM tasks ORDER BY id')]
            ensure_dispatch_indexes(db)
            ensure_dispatch_indexes(db)
            self.assertEqual(before, [tuple(r) for r in db.execute('SELECT * FROM tasks ORDER BY id')])
            plan = ' '.join(r[3] for r in db.execute(
                'EXPLAIN QUERY PLAN SELECT 1 FROM batch_runs WHERE task_id=? AND token=? AND round>?',
                ('task', 'token', 0)))
            self.assertIn('dispatch_batch_task', plan)

    def test_claim_skips_exhausted_then_checks_independence(self):
        with self.flow.db() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM tasks ORDER BY id')]
            limit = self.flow.config(db)['max_attempts']
            db.execute('UPDATE tasks SET attempt=? WHERE id=?', (limit, ids[0]))
        with patch.object(self.flow, 'effective_attempts', return_value=limit), \
                patch.object(self.flow, 'independent_worker', return_value=True) as independent:
            claimed = self.flow.claim('extract', 'worker')
        self.assertEqual(claimed['task_id'], ids[1])
        self.assertEqual(independent.call_count, 1)

    def test_no_independent_candidate_is_still_rejected(self):
        with patch.object(self.flow, 'independent_worker', return_value=False):
            with self.assertRaisesRegex(ValueError, 'Independent reviewer'):
                self.flow.claim('extract', 'same-author')


if __name__ == '__main__':
    unittest.main()
