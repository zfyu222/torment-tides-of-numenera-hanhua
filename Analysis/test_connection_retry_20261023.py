"""Bounded transport recovery with real workflow handoffs and retained ledgers."""
import json
import os
import unittest
from unittest.mock import patch

import ainiee_bridge as bridge
import translation_workflow as workflow
import test_translation_workflow as fixtures
from workflow_api_budget import connection_retry_delay, budget_requests, effective_attempts


class ConnectionRetryTests(unittest.TestCase):
    def test_policy_is_bounded_and_does_not_retry_http_faults(self):
        for code in ('APIConnectionError:transport', 'APITimeoutError:transport', 'stream_interrupted', 'incomplete_stream'):
            self.assertEqual([connection_retry_delay(code, n) for n in range(4)], [2, 4, 8, None])
        for code in ('PermissionDeniedError:403', 'AuthenticationError:401', 'RateLimitError:429',
                     'InternalServerError:500', 'NotFoundError:404', 'invalid_model_result', 'empty_response'):
            self.assertIsNone(connection_retry_delay(code, 0))

    def run_fixture(self, failures, success=False, pause_on_error=False):
        f = fixtures.WorkflowTests(); f.setUp(); self.addCleanup(f.tearDown)
        flow = f.flow; flow.pause(True)
        flow.configure({'backend': 'api', 'max_attempts': 1, 'api': {
            'api_url': 'https://example.invalid/v1', 'model_name': 'fixture',
            'concurrency': 1, 'max_requests': 1}}, 'Connection retry fixture', impact='none')
        flow.pause(False)
        calls = []
        class Client:
            def request(self, system, user):
                calls.append(user)
                if len(calls) <= failures:
                    if pause_on_error:
                        flow.pause(True)
                    raise bridge.ApiFailure('APIConnectionError:transport', retryable=True)
                return json.dumps({'analysis': {'characters': [], 'terms': [], 'non_translate': []}}), {
                    'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}
            def close(self): pass
        # Keep the retry count unchanged while eliminating backoff in fixtures.
        with patch.dict(os.environ, {'SHH_TRANSLATION_API_KEY': 'fixture'}), \
                patch('workflow_api_budget.CONNECTION_RETRY_BASE_SECONDS', 0.001):
            result = workflow.run_api(flow, 'extract', lambda *_: Client())
        return flow, calls, result

    def test_three_faults_then_success_preserves_budget_and_task(self):
        flow, calls, result = self.run_fixture(3)
        self.assertEqual(len(calls), 4)
        self.assertEqual(result['accepted'], 1)
        with flow.db() as db:
            self.assertEqual(budget_requests(db), 1)
            task = dict(db.execute('SELECT * FROM tasks WHERE status="done"').fetchone())
            self.assertEqual(task['attempt'], 4)
            self.assertEqual(effective_attempts(db, task), 1)
            self.assertEqual(db.execute('SELECT count(*) FROM api_calls WHERE status="APIConnectionError:transport"').fetchone()[0], 3)

    def test_four_faults_stop_without_spending_model_budget(self):
        flow, calls, result = self.run_fixture(4)
        self.assertEqual(len(calls), 4)
        self.assertTrue(result['paused'])
        self.assertEqual(result['accepted'], 0)
        with flow.db() as db:
            self.assertEqual(budget_requests(db), 0)
            task = dict(db.execute('SELECT * FROM tasks WHERE status="running"').fetchone())
            self.assertEqual(task['attempt'], 4)
            self.assertEqual(effective_attempts(db, task), 0)

    def test_user_pause_interrupts_backoff_without_new_request(self):
        flow, calls, result = self.run_fixture(1, pause_on_error=True)
        self.assertEqual(len(calls), 1)
        self.assertTrue(result['paused'])


if __name__ == '__main__':
    unittest.main()
