import json
import os
import sqlite3
import unittest
from unittest.mock import patch
import ainiee_bridge as bridge
import translation_workflow as workflow
import test_translation_workflow as fixtures
from workflow_api_budget import service_failure, budget_requests, effective_attempts


class BudgetTests(unittest.TestCase):
    def test_service_and_model_failures_are_distinct(self):
        for status in ['RateLimitError:429', 'InternalServerError:502', 'APITimeoutError:transport',
                       'PermissionDeniedError:403', 'empty_response', 'stream_interrupted']:
            self.assertTrue(service_failure(status), status)
        for status in ['received', 'invalid_model_result', 'reasoning_budget_exhausted',
                       'rejected_length_terminated_response']:
            self.assertFalse(service_failure(status), status)

    def test_raw_calls_remain_and_shared_attempt_with_model_response_is_charged(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('create table api_calls(id integer,task_id text,status text,session_id text,task_attempt integer)')
        db.execute('create table batch_runs(id text,token text,round integer)')
        for i, status, attempt, round_ in [(1,'RateLimitError:429',1,0),
                (2,'invalid_model_result',2,0), (3,'InternalServerError:502',3,1),
                (4,'received',3,1), (5,'reserved',4,0), (6,'InternalServerError:500',None,0)]:
            db.execute('insert into api_calls values (?,?,?,?,?)',(i,'t',status,str(i),attempt))
            db.execute('insert into batch_runs values (?,?,?)',(str(i),'lease',round_))
        raw = list(db.execute('select * from api_calls'))
        self.assertEqual(budget_requests(db),3)  # received, model rejection, reserved
        self.assertEqual(effective_attempts(db, {'id':'t','backend':'api','attempt':5}),3)
        self.assertEqual(effective_attempts(db, {'id':'t','backend':'codex','attempt':5}),5)
        self.assertEqual(raw,list(db.execute('select * from api_calls')))

    def test_service_error_stops_once_and_does_not_exhaust_task_or_project_budget(self):
        f = fixtures.WorkflowTests();f.setUp();self.addCleanup(f.tearDown)
        flow = f.flow;flow.pause(True)
        flow.configure({'backend':'api','max_attempts':1,'api':{
            'api_url':'https://example.invalid/v1','model_name':'fixture',
            'concurrency':1,'max_requests':1}},'Service budget test',impact='none')
        flow.pause(False);calls=[]
        class Client:
            def request(self, system, user):
                calls.append(user)
                raise bridge.ApiFailure('InternalServerError:502', retryable=True)
            def close(self): pass
        with patch.dict(os.environ,{'SHH_TRANSLATION_API_KEY':'fixture'}):
            result=workflow.run_api(flow,'extract',lambda *_:Client())
        self.assertEqual(len(calls),1)
        self.assertTrue(result['paused'])
        with flow.db() as db:
            task=dict(db.execute('select * from tasks where status="running"').fetchone())
            self.assertEqual(task['attempt'],1)
            self.assertEqual(effective_attempts(db,task),0)
            self.assertEqual(budget_requests(db),0)
            self.assertEqual(db.execute('select count(*) from api_calls where status="InternalServerError:502"').fetchone()[0],1)
        flow.recover(task['id'],worker_stopped=True)
        flow.pause(False)
        claimed=flow.claim('extract','new-worker',backend='api')
        self.assertIsNotNone(claimed)


if __name__=='__main__':unittest.main()
