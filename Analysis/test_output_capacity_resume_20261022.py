"""Output capacity increases retain all pre-existing task and request state."""
import unittest

import test_translation_workflow as fixtures


class OutputCapacityTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkflowTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.flow = self.f.flow
        self.flow.pause(True)
        self.flow.configure({'backend': 'api'}, 'API fixture', impact='none')
        self.flow.pause(False)
        self.flow.prepare('extract')
        self.session = self.flow.batch_open('extract', 'api-writer', backend='api', prepared=True)
        self.flow.pause(True)

    def test_increase_preserves_tasks_handoffs_attempts_and_revision(self):
        with self.flow.db() as db:
            revision = self.flow.meta(db, 'revision')
            before = {table: [tuple(r) for r in db.execute('SELECT * FROM ' + table)]
                      for table in ('tasks', 'batch_runs', 'quality_attempts', 'api_calls')}
        result = self.flow.configure({'review_output_tokens': 32768}, 'User increased output capacity', impact='none')
        self.assertTrue(result['output_capacity_only'])
        with self.flow.db() as db:
            self.assertEqual(revision, self.flow.meta(db, 'revision'))
            self.assertEqual(32768, self.flow.config(db)['review_output_tokens'])
            for table, rows in before.items():
                self.assertEqual(rows, [tuple(r) for r in db.execute('SELECT * FROM ' + table)])

    def test_reserved_request_blocks_capacity_change(self):
        with self.flow.db() as db:
            db.execute('INSERT INTO api_calls(task_id,time,status,usage) VALUES (?,?,?,?)',
                       ('test', 1, 'reserved', '{}'))
        with self.assertRaisesRegex(ValueError, 'no reserved requests'):
            self.flow.configure({'review_output_tokens': 32768}, 'Increase', impact='none')
        with self.flow.db() as db:
            self.assertEqual(16384, self.flow.config(db)['review_output_tokens'])

    def test_decrease_does_not_bypass_running_task_guard(self):
        with self.assertRaisesRegex(ValueError, 'Finish/recover'):
            self.flow.configure({'review_output_tokens': 8192}, 'Decrease', impact='none')


if __name__ == '__main__':
    unittest.main()
