"""Adopt the actual one-term follow-up, archive history, reuse unrelated drafts."""
import copy
import json
import shutil
import repair
import term_parts
import scope_match
from resume_current_api import run_lock


def main():
    r = repair.Repair(); baseline = r.snapshot()
    with run_lock(r):
        follow = r.work / repair.w.read_json(r.work/'descriptor_review_jobs.json')[0]
        saved = repair.w.read_json(follow/'accepted.json')
        review_payload = repair.w.read_json(follow/'payload.json')
        r.validate_result(review_payload, saved['result'], None)
        if saved['result']['decisions']['reviewed_refs'] != ['terms:2862']:
            raise ValueError('Unexpected semantic follow-up coverage')
        parent = r.work/'jobs/glossary_review'/review_payload['attempt_parent_job']
        payload = r.term_payload(repair.w.read_json(parent/'payload.json'))
        history = r.work / ('before_descriptor_' + repair.sha(follow/'accepted.json')[:12])
        if history.exists():
            raise ValueError('Adoption history already exists; inspect rather than overwrite')
        history.mkdir()
        for name in ('term_decisions.json','new_glossary.json','repair_plan.json','translate_jobs.json'):
            shutil.copy2(r.work/name,history/name)
        shutil.copy2(parent/'accepted.json',history/'parent_accepted.json')
        partfile = parent/'term_parts/terms_2862.json'
        shutil.copy2(partfile,history/'old_term_part.json')
        before_glossary = repair.w.read_json(r.work/'new_glossary.json')
        old_drafts = {}
        for relative in repair.w.read_json(r.work/'translate_jobs.json'):
            folder=r.work/relative
            if not (folder/'accepted.json').exists():continue
            accepted=repair.w.read_json(folder/'accepted.json'); oldpayload=repair.w.read_json(folder/'payload.json')
            by_id={x['id']:x for x in oldpayload['records']}
            for item in accepted['result']['records']:
                rid=item['id'];old_drafts[rid]={'item':item,'record':by_id[rid],
                    'instance':accepted['record_instances'][rid],
                    'sha':accepted['record_response_sha256'][rid],
                    'job':folder.name,'input_hash':oldpayload['input_hash']}
        part=repair.w.read_json(follow/'term_parts/terms_2862.json')
        part['origin_input_hash']=part['input_hash'];part['origin_job']=follow.name
        part['input_hash']=payload['input_hash']
        repair.w.write_json(partfile,part)
        if not term_parts.finish(r,parent,payload):raise ValueError('Parent term assembly incomplete')
        # Both resolved absolute paths must remain within this repair workspace.
        build=(r.work/'term_build').resolve(); archived=(history/'term_build').resolve()
        if not build.is_relative_to(r.work) or not archived.is_relative_to(r.work):
            raise ValueError('Unsafe build archive path')
        build.rename(archived)
        repair.w.write_json(r.work/'descriptor_adoption_started.json',
            {'followup':follow.name,'history':str(history.relative_to(r.work)),
             'followup_response':saved,'parent_attempts_preserved':True})
        result=r.collect_terms()
        print(json.dumps({'updated_scope':result}),flush=True)
        prepared=r.prepare_translation()
        glossary=repair.w.read_json(r.work/'new_glossary.json');config=baseline['config']
        rules=repair.bridge.patterns(config['protect_named_curly'] is not False,config['exclusions'],config.get('placeholder_family_overrides'))
        ga,gb=repair.comparison_glossaries(before_glossary,glossary)
        for g in (ga,gb):scope_match.prepare(g,config,rules)
        imported=[];changed=[]
        for relative in repair.w.read_json(r.work/'translate_jobs.json'):
            folder=r.work/relative
            if (folder/'accepted.json').exists():continue
            p=repair.w.read_json(folder/'payload.json')
            for record in p['records']:
                rid=record['id'];old=old_drafts.get(rid)
                if not old:continue
                if record!=old['record']:raise ValueError('Draft source/protection/metadata changed')
                source=repair.bridge.restore(record['source'],record.get('protection',[]),allow_original=True)
                before=repair.bridge.matched_terms(ga,[source],config,rules=rules)
                after=repair.bridge.matched_terms(gb,[source],config,rules=rules)
                if repair.matched_meaning(before)!=repair.matched_meaning(after):
                    changed.append(rid);continue
                try:
                    r.save_body_parts(folder,p,{**p,'records':[record]},
                        {'records':[copy.deepcopy(old['item'])]},glossary,old['instance'],old['sha'])
                except ValueError as exc:
                    if not str(exc).startswith('Only failed/missing records need retry:'):raise
                path=folder/'partial'/(rid+'.json')
                if not path.exists():raise ValueError('Previously valid unrelated draft failed import')
                imported_part=repair.w.read_json(path)
                imported_part.update(origin_job=old['job'],origin_input_hash=old['input_hash'])
                repair.w.write_json(path,imported_part);imported.append(rid)
        report={'scope':result,'prepared':prepared,'previous_drafts':len(old_drafts),
            'reused_in_new_jobs':imported,'changed_term_drafts_requiring_retranslation':changed,
            'formal_csv_unchanged':repair.sha(r.project/baseline['translation_file'])==baseline['translation_sha256']}
        repair.w.write_json(r.work/'descriptor_adoption_result.json',report)
        print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
