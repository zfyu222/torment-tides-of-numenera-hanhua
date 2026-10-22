import time
import unittest
import test_translation_workflow as fixtures
from translation_workflow import resume_api_tasks


class PartialLeaseResumeTests(unittest.TestCase):
    def test_expired_partial_handoff_is_renewed_without_reissuing_or_erasing(self):
        f = fixtures.WorkflowTests(); f.setUp(); self.addCleanup(f.tearDown)
        f.freeze(True); flow = f.flow
        flow.pause(True)
        flow.configure({'backend': 'api'}, 'API lease fixture', impact='none')
        flow.pause(False)
        session = flow.batch_open('translate', 'partial-fixture', backend='api')
        with flow.db() as db:
            run = db.execute('select * from batch_runs where id=?', (session['session_id'],)).fetchone()
            task_id, token = run['task_id'], run['token']
            db.execute('update batch_runs set status="repair_required" where id=?', (run['id'],))
            db.execute('update tasks set lease_until=0 where id=?', (task_id,))
            before = tuple(db.execute('select status,attempt,lease_token from tasks where id=?', (task_id,)).fetchone())
        self.assertEqual(resume_api_tasks(flow, 'translate'), 0)
        with flow.db() as db:
            task = flow.valid_task(db, task_id, token)
            self.assertGreater(task['lease_until'], time.time())
            self.assertEqual(before, tuple(task[k] for k in ('status', 'attempt', 'lease_token')))
            self.assertEqual(db.execute('select status from batch_runs where id=?', (session['session_id'],)).fetchone()[0], 'repair_required')


if __name__ == '__main__':
    unittest.main()
