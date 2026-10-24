"""Offline replay only: same-bound paragraph layout, no requests or quota reset."""
import json
import repair
import scope_match
from resume_current_api import run_lock


def main():
    r=repair.Repair();b=r.snapshot()
    with run_lock(r):
        calls=repair.w.read_json(r.work/'calls.json')
        if any(c['status']=='reserved' for c in calls):raise ValueError('Unknown in-flight request')
        g=repair.w.read_json(r.work/'new_glossary.json');c=b['config']
        scope_match.prepare(g,c,repair.bridge.patterns(c['protect_named_curly'] is not False,c['exclusions'],c.get('placeholder_family_overrides')))
        folders=[r.work/p for p in repair.w.read_json(r.work/'translate_jobs.json')]
        before=sum((p/'accepted.json').exists()for p in folders); errors=[]
        for folder in folders:
            if (folder/'accepted.json').exists():continue
            payload=repair.w.read_json(folder/'payload.json')
            for call in calls:
                if call['job']!=folder.name or call['status']not in ('received','rejected','interrupted'):continue
                out=folder/call['id'];raw=out/'response.raw.txt'
                if not raw.exists():continue
                try:
                    request=repair.w.read_json(out/'payload.json');binding=repair.w.read_json(out/'binding.json')
                    result=repair.canonical_api_partial_result(repair.bridge.parse_response(raw.read_text(encoding='utf8')),
                        binding,payload['task_id'],payload['task_id'],payload['input_hash'],[row['id']for row in request['records']])
                    r.save_body_parts(folder,payload,request,result,g,'api:'+call['id'],repair.sha(raw))
                except (ValueError,KeyError,TypeError) as exc:
                    errors.append({'job':folder.name,'call':call['id'],'error':str(exc)[:1500]});continue
                break
        after=sum((p/'accepted.json').exists()for p in folders)
        report={'api_requests_issued':0,'accepted_jobs_before':before,'accepted_jobs_after':after,
            'recovered_jobs':after-before,'remaining_jobs':len(folders)-after,
            'saved_draft_records':sum(len(list((p/'partial').glob('*.json')))for p in folders),
            'historical_statuses_or_attempts_reset':False,'replay_errors':errors}
        repair.w.write_json(r.work/'body_offline_recovery.json',report)
        print(json.dumps({k:v for k,v in report.items()if k!='replay_errors'},ensure_ascii=False))


if __name__=='__main__':main()
