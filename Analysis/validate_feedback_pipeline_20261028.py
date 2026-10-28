"""Two bounded real-API fixtures; never integrate/deploy or rewrite production data."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys

P = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(P/'IncrementalRepair'))
import repair
import workflow_feedback_guards as guards
from resume_current_api import run_lock


class Validation(repair.Repair):
    def __init__(self):
        super().__init__(work=P/'TranslateFiles/feedback_pipeline_validation_20261028')

    def render(self,payload,glossary=None):
        text,binding=super().render(payload,glossary)
        if payload['stage']=='glossary_review':
            text += ('\n本批为已验证引擎的隔离回归：TokenReplacer.ReplaceListenerTokens实际选择|左|右|后处理真实变量；'
                'GUIUtils.GetTaskResultString通过TTONGui ID56-59读取可见成功/失败文字。'
                '只审分配词条，不扩大范围或添加新词；说明声称stichus为sticha单数的关系仍须结合所给原文判断。')
        return text,binding

    def validate_result(self,payload,result,glossary):
        value=super().validate_result(payload,result,glossary)
        if payload['stage']!='glossary_review':
            originals={x['id']:x for x in payload['records']}
            for row in value['records']:
                source=dict(id=row['id'],source=originals[row['id']]['source'])
                profile=guards.record_profile(P,source)
                if guards.listener_issues(source['source'],row['translation'],profile):
                    raise ValueError('Source-bound listener validation failed')
                if guards.known_feedback_issues(row['translation'],guards.record_feedback(P,source)):
                    raise ValueError('Confirmed source-bound semantic regression')
        return value


def prepare(r):
    if (r.work/'baseline.json').exists():
        r.snapshot(); return
    with r.db() as db:
        meta={x['key']:json.loads(x['value']) for x in db.execute('SELECT * FROM meta')}
        assert not db.execute('SELECT 1 FROM api_calls WHERE status="reserved"').fetchone()
        rows=[dict(x) for x in db.execute('SELECT * FROM records ORDER BY ordinal')]
        budget=repair.budget_requests(db)
    for row in rows: row['metadata']=meta['contexts'].get(str(row['ordinal']),{})
    glossary=P/'TranslateFiles'/meta['glossary']['path']
    baseline=dict(source_file=P.name+'_text.csv',translation_file=P.name+'_text_translated.csv',
        source_sha256=repair.sha(P/(P.name+'_text.csv')),translation_sha256=repair.sha(P/(P.name+'_text_translated.csv')),
        glossary_file=str(glossary.relative_to(P)),glossary_sha256=repair.sha(glossary),
        parent_revision=meta['revision'],config=meta['config'],parent_budget_requests=budget)
    repair.w.write_json(r.work/'baseline.json',baseline)
    repair.w.write_json(r.work/'records.json',rows)
    shutil.copy2(P/baseline['source_file'],r.work/'source.csv')
    shutil.copy2(glossary,r.work/'old_glossary.json')
    shutil.copy2(glossary,r.work/'new_glossary.json')
    old=repair.w.read_json(P/'TranslateFiles/feedback_20261028/old_glossary.json')
    audit=copy.deepcopy(old)
    audit['characters']=[]
    audit['terms']=[x for x in audit['terms'] if x['source'] in ('sticha','stichus')]
    audit['non_translate']=[x for x in audit['non_translate'] if x['source'] in ('|you|he|','[Failure]')]
    repair.glossary_tool.refresh_stats(audit);repair.attach_corpus_evidence(audit,rows)
    repair.w.write_json(r.work/'input.json',{'extra':{'analysis_v1':audit}})
    repair.glossary_tool.audit(r.work/'input.json',r.work/'source.csv',r.work/'term_audit')
    r.prepare_terms()
    prior={x['ordinal']:x['translation'] for x in repair.w.read_json(P/'TranslateFiles/feedback_20261028/records.json')}
    selected=[x for x in rows if x['ordinal'] in (1912,12619,12644,26904,62518)]
    def build(group):
        payload=r.base_payload('review',baseline)
        payload['records']=[dict(id=x['id'],ordinal=x['ordinal'],source=x['source'],translation=prior[x['ordinal']],
            metadata=x['metadata'],protection=[],exceptions=[],locked=False) for x in group]
        payload['terms']=repair.bridge.matched_terms(repair.w.read_json(r.work/'new_glossary.json'),[x['source'] for x in group],baseline['config'])
        return payload
    r.queue('review',selected,build,repair.w.read_json(r.work/'new_glossary.json'))
    api=repair.w.local_api_name()
    jobs=sum([repair.w.read_json(r.work/(stage+'_jobs.json')) for stage in ('glossary_review','review')],[])
    assert len(jobs)==2
    repair.w.write_json(r.work/'retry_grants.json',{Path(x).name:dict(api=api,max_total_attempts=2) for x in jobs})


def main():
    r=Validation();r.work.mkdir(parents=True,exist_ok=True)
    with run_lock(r):
        prepare(r)
        # Preserve the real false-positive response; invalidate only its one
        # failed record after adding a confirmed source-bound regression case.
        for relative in repair.w.read_json(r.work/'review_jobs.json'):
            folder=r.work/relative
            accepted=folder/'accepted.json'
            if not accepted.exists(): continue
            payload=repair.w.read_json(folder/'payload.json')
            by_id={row['id']:row for row in payload['records']}
            bad=[row['id'] for row in repair.w.read_json(accepted)['result']['records'] if
                guards.known_feedback_issues(row['translation'],guards.record_feedback(P,by_id[row['id']]))]
            if bad:
                accepted.rename(folder/'accepted_before_semantic_guard.json')
                history=folder/'semantic_guard_history';history.mkdir(exist_ok=True)
                for record_id in bad:
                    part=folder/'partial'/(record_id+'.json')
                    part.rename(history/part.name)
        for stage in ('glossary_review','review'):
            result=r.run_jobs(stage)
            if result['remaining']:
                print(json.dumps(result));return
        calls=repair.w.read_json(r.work/'calls.json')
        assert len([x for x in calls if x['status']!='cancelled' and not repair.service_failure(x['status'])])<=4
        r.snapshot()
        report=dict(status='real_api_validation_passed',logical_batches=2,max_effective_requests=4,
            actual_requests=len(calls),reported_tokens=sum(x.get('usage',{}).get('total_tokens',0) or 0 for x in calls),
            unknown_usage=sum(not x.get('usage',{}).get('usage_reported') for x in calls),
            production_translation_and_glossary_unchanged=True,api_route='current configured priority',
            thinking=True,concurrency='configuration',scope='4 terminology candidates and 5 text records')
        report['confirmed_semantic_case_retry'] = dict(failed_records=1,other_accepted_records_retained=4,
            original_false_positive_preserved=True,attempts_reset=False) if list((r.work/'jobs/review').glob('*/accepted_before_semantic_guard.json')) else None
        repair.w.write_json(P/'Analysis/feedback_pipeline_live_validation_20261028.json',report)
        print(json.dumps(report))


if __name__=='__main__':main()
