"""Use public workflow operations for the explicitly authorized 54-batch recovery."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, 'D:/StaticHanHua/Tools/localization')
from translation_workflow import Workflow, resume_api_tasks, read_json, write_json
from workflow_task_contract import canonical_api_partial_result

PROJECT = Path(__file__).resolve().parent.parent
MANIFEST = PROJECT / 'TranslateFiles/reports/extract_sol_recovery_20261021.json'

def prepare():
    flow = Workflow(PROJECT)
    if MANIFEST.exists():
        return {'status':'already_prepared','manifest':str(MANIFEST)}
    with flow.db() as db:
        config = flow.config(db)
        waiting = [dict(r) for r in db.execute('SELECT b.*,t.attempt FROM batch_runs b JOIN tasks t ON t.id=b.task_id WHERE b.status="waiting" AND t.status="running" AND t.stage="extract"')]
        assert len(waiting) == 54, len(waiting)
        assert not db.execute('SELECT 1 FROM api_calls WHERE status="reserved"').fetchone()
    assert not (flow.root/'state/api_round.lock').exists()
    flow.pause(True)
    # One new execution by Sol for each failed task, preserving every historical
    # attempt; no automatic loop or original API-model replay is authorized here.
    flow.configure({'max_attempts':5}, '用户明确要求处理54个失败批次；改用独立Sol实例定向修复出处与截断，增加一次有记录的执行机会，不重置历史、不重跑1231个成功批次。', impact='none')
    collected = resume_api_tasks(flow,'extract')
    flow.pause(False)
    manifest = {'stage':'extract','method':'Sol targeted recovery; existing API stages unchanged','old_handoffs':waiting,'assignments':[], 'collected_saved_replies':collected}
    write_json(MANIFEST,manifest)
    return {'status':'ready','failed_handoffs':len(waiting),'saved_replies_collected':collected}

def claim(worker):
    flow=Workflow(PROJECT)
    packet=flow.batch_open('extract',worker,backend='api',prepared=True)
    if packet['status']!='ready':return packet
    manifest=read_json(MANIFEST)
    prior=next(x for x in manifest['old_handoffs'] if x['task_id']==packet['task_id'])
    old_folder=Path(prior['input_file']).parent
    candidate=next((old_folder/n for n in ('response.parsed.json','result.json') if (old_folder/n).exists()),None)
    packet['candidate_file']=str(candidate) if candidate else None
    packet['model_result_file']=str(Path(packet['result_file']).with_name('sol.analysis.json'))
    packet['worker']=worker
    manifest['assignments'].append(packet);write_json(MANIFEST,manifest)
    return packet

def collect(session):
    flow=Workflow(PROJECT);manifest=read_json(MANIFEST)
    assignment=next(x for x in manifest['assignments'] if x['session_id']==session)
    with flow.db() as db:
        run=dict(flow._batch_run(db,session))
        task=dict(flow.valid_task(db,run['task_id'],run['token']))
    result=read_json(Path(assignment['model_result_file']))
    transport=read_json(Path(run['result_file']).with_name('api_id_transport.v2.json'))
    canonical=canonical_api_partial_result(result,transport,session,task['id'],task['input_hash'],json.loads(run['scope']))
    write_json(Path(run['result_file']),canonical)
    receipt=flow.batch_finish(session)
    assignment['receipt']=receipt;write_json(MANIFEST,manifest)
    return receipt

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','claim','collect']);parser.add_argument('--worker');parser.add_argument('--session')
    args=parser.parse_args()
    result=prepare() if args.action=='prepare' else claim(args.worker) if args.action=='claim' else collect(args.session)
    print(json.dumps(result,ensure_ascii=False))
