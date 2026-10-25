"""Two isolated source-bound real requests, with one deliberately injected cooldown.

The API outage is NOT real: the first provider is locally marked disabled to
test the real 60-second timer, lower-priority dispatch and one recovery probe.
No production translation state is modified. At most four SDK requests.
"""
import copy
import json
import shutil
import threading
import time
from unittest.mock import patch
import repair
from resume_current_api import run_lock


def main():
    main=repair.Repair();baseline=main.snapshot()
    r=repair.Repair(main.project/'TranslateFiles/api_cooldown_live_validation_20261025')
    report_path=r.work/'validation_report.json'
    if report_path.exists():
        print(json.dumps(repair.w.read_json(report_path),ensure_ascii=False));return
    if r.work.exists():raise ValueError('Incomplete validation workspace exists; inspect without resetting requests')
    r.work.mkdir()
    baseline=copy.deepcopy(baseline)
    baseline['parent_budget_requests']+=sum(c['status']!='cancelled'and not repair.service_failure(c['status'])
        for c in repair.w.read_json(main.work/'calls.json'))
    repair.w.write_json(r.work/'baseline.json',baseline)
    shutil.copy2(main.work/'new_glossary.json',r.work/'new_glossary.json')
    rows=repair.w.read_json(main.work/'records.json');g=repair.w.read_json(r.work/'new_glossary.json');config=baseline['config']
    rules=repair.bridge.patterns(config['protect_named_curly']is not False,config['exclusions'],config.get('placeholder_family_overrides'))
    selected=[rows[n-1]for n in (57207,62257)]
    def payload(group):
        value=r.base_payload('translate',baseline);value['records']=[]
        value['terms']=repair.bridge.matched_terms(g,[row['source']for row in group],config,rules=rules)
        for row in group:
            source,protection=repair.bridge.protect(row['source'],row['id'],repair.bridge.record_rules(row,config,rules))
            value['records'].append({'id':row['id'],'ordinal':row['ordinal'],'source':source,'protection':protection,
                'translation':None,'metadata':row['metadata'],'exceptions':[],'locked':False})
        return value
    r.queue('translate',selected,payload,g,cap=1)
    jobs=repair.w.read_json(r.work/'translate_jobs.json')
    original=repair.bridge.AINieeAPI;wire=[];gate=threading.Lock()
    class Guarded:
        def __init__(self,s,key):self.client=original(s,key)
        def close(self):self.client.close()
        def request(self,system,user):
            with gate:
                if len(wire)>=4:
                    raise repair.bridge.ApiFailure('validation_wire_limit',False,{'usage_reported':False,'request_issued':False})
                wire.append(1)
            return self.client.request(system,user)
    pool=repair.w.make_api_pool(config,r.work,'cooldown_live_validation',Guarded)
    if not pool.managed or [s['name']for s in pool.specs]!=['yjapi','vortex','acy7','deepseek']:
        pool.close();raise ValueError('Unexpected selected priority policy')
    pool.audit.event('validation_injection', api='yjapi', state='disabled', simulated_outage=True,
        real_clock=True, cooldown_seconds=60, max_sdk_calls=4, production_state_modified=False)
    with pool.cv:
        pool.states[0].generation+=1;pool.states[0].retry_at=pool.clock()+60
        pool.change_state(0,'disabled','validation_injected_cooldown_not_real_api_failure')
    deadline=time.monotonic()+240
    class Borrowed:
        def __getattr__(self,name):return getattr(pool,name)
        def close(self):pool.audit.save()  # validation owns one pool across two mini-rounds
        def acquire(self,cancelled=lambda:False):
            return pool.acquire(lambda:cancelled()or time.monotonic()>=deadline)
    results=[];next_index=None
    try:
        with run_lock(r),patch.object(repair.w,'make_api_pool',lambda *a,**kw:Borrowed()):
            repair.w.write_json(r.work/'first_jobs.json',[jobs[0]])
            results.append(r.run_jobs('translate',manifest='first_jobs.json'))
            if results[0]['remaining']==0:
                while pool.clock()<pool.states[0].retry_at:
                    time.sleep(max(0,min(.25,pool.states[0].retry_at-pool.clock())))
                repair.w.write_json(r.work/'second_jobs.json',[jobs[1]])
                results.append(r.run_jobs('translate',manifest='second_jobs.json'))
                if results[-1]['remaining']==0:
                    lease=pool.acquire(lambda:time.monotonic()>=deadline)
                    next_index=lease.index;pool.release(lease)
        changes=list(pool.audit.state_changes)
        recovered=any(x['api']=='yjapi'and x['to_state']=='normal'and x['reason']=='probe_succeeded'for x in changes)
        calls=repair.w.read_json(r.work/'calls.json')
        report={'simulated_initial_outage':True,'real_cooldown_timer_seconds':60,'actual_sdk_calls':len(wire),
            'results':results,'recovery_probe_success_observed':recovered,
            'next_dispatch_is_primary':next_index==0,'provider_states':pool.state_snapshot(),
            'api_attempts':[{'api':c['api'],'status':c['status'],'usage':c.get('usage')}for c in calls],
            'production_csv_unchanged':repair.sha(r.project/baseline['translation_file'])==baseline['translation_sha256'],
            'production_state_modified':False,'api_report':str(pool.audit.report),'api_log':str(pool.audit.log)}
        repair.w.write_json(report_path,report)
        print(json.dumps({k:v for k,v in report.items()if k not in ('results','api_attempts')},ensure_ascii=False))
    finally:pool.close()


if __name__=='__main__':main()
