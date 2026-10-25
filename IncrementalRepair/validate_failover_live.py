"""One real, unissued affected-scope job; at most twenty actual wire calls."""
import json
import threading
from unittest.mock import patch
import repair
from resume_current_api import run_lock


def main():
    r=repair.Repair();baseline=r.snapshot()
    with run_lock(r):
        calls=repair.w.read_json(r.work/'calls.json')
        if any(c['status']=='reserved'for c in calls):raise ValueError('Unknown in-flight request')
        issued={c['job']for c in calls if c['status']!='cancelled'}
        candidates=[]
        for relative in repair.w.read_json(r.work/'translate_jobs.json'):
            folder=r.work/relative
            if folder.name in issued or (folder/'accepted.json').exists():continue
            payload=repair.w.read_json(folder/'payload.json')
            candidates.append((sum(len(x['source'])for x in payload['records']),relative,len(payload['records'])))
        if not candidates:raise ValueError('No unissued job for bounded validation')
        _,relative,count=min(candidates)
        repair.w.write_json(r.work/'live_failover_jobs.json',[relative])
        original=repair.bridge.AINieeAPI;gate=threading.Lock();wire=[]
        class Guarded:
            def __init__(self,settings,key):self.client=original(settings,key)
            def close(self):self.client.close()
            def request(self,system,user):
                with gate:
                    if len(wire)>=20:
                        raise repair.bridge.ApiFailure('validation_wire_limit',False,
                            {'usage_reported':False,'request_issued':False})
                    wire.append(1)
                return self.client.request(system,user)
        start=len(calls)
        repair.w.write_json(r.work/'live_failover_limits.json',{'jobs':1,'records':count,'max_actual_wire_calls':20,
            'source_sha256':baseline['source_sha256'],'new_glossary_sha256':repair.sha(r.work/'new_glossary.json')})
        with patch.object(repair.bridge,'AINieeAPI',Guarded):
            result=r.run_jobs('translate',manifest='live_failover_jobs.json')
        newcalls=repair.w.read_json(r.work/'calls.json')[start:]
        report={'result':result,'actual_wire_calls':len(wire),'job':relative,'records':count,
            'api_attempts':[{'api':c['api'],'status':c['status'],'usage':c.get('usage')}for c in newcalls],
            'formal_csv_unchanged':repair.sha(r.project/baseline['translation_file'])==baseline['translation_sha256']}
        repair.w.write_json(r.work/'live_failover_validation.json',report)
        print(json.dumps({'remaining':result['remaining'],'actual_wire_calls':len(wire),
                          'api_provider_report':result.get('api_provider_report')},ensure_ascii=False))


if __name__=='__main__':main()
