"""Source-bound targeted term recheck after the official body probe failed."""
import copy
import json
import time
import repair
from resume_current_api import run_lock
from retry_current_api import POLICY_DIAGNOSTIC


def main():
    r = repair.Repair(); baseline = r.snapshot()
    with run_lock(r):
        original = repair.w.read_json(r.work / 'term_audit/glossary_original.json')
        row = original['terms'][2862]
        if row['source'] != 'Hardened': raise ValueError('Unexpected term identity')
        parent = None
        for path in repair.w.read_json(r.work / 'glossary_review_jobs.json'):
            p = repair.w.read_json(r.work / path / 'payload.json')
            if any(e['ref'] == 'terms:2862' for e in p['entries']): parent = p['task_id']; break
        if parent is None: raise ValueError('No original term task')
        rows = repair.w.read_json(r.work / 'records.json')
        def build(entries):
            payload = r.base_payload('glossary_review', baseline)
            payload.update(snapshot_sha256=repair.sha(r.work/'term_audit/glossary_original.json'),
                terminology_policy=1, applicability_policy=1, entries=entries,
                related_entries=[], term_families=[], audit={'findings': []},
                records=[{k: rows[n-1][k] for k in ('id','ordinal','source','metadata')}
                         for n in sorted(set(repair.review_evidence_rows(row)) | {57207,57530,67743})],
                attempt_parent_job=parent,
                revision_request='已发布译文增量修复。正文独立翻译实测仍沿用“硬化”，只降为reference没有解决人物特质标签的中文搭配问题。'
                    '本词57530明确为Descriptor，67743说明Descriptor是角色起始属性/技能的修正来源。'
                    '请基于这些实际原文重新判断Hardened在此处修饰的对象、词义、自然中文标签和适用范围。'
                    '这是人物特质标签，不要把材料或过程的通常译法直接当作结论；不得只改执行等级而跳过对旧译词义的审查。'
                    '不指定目标译名，由你据原文给出判断。每条真实四维证据与分类字段完整。' + POLICY_DIAGNOSTIC)
            return payload
        r.queue('glossary_review', [{'ref':'terms:2862','table':'terms','index':2862,'row':copy.deepcopy(row)}],
                build, cap=1, manifest='descriptor_review_jobs.json')
        manifest = repair.w.read_json(r.work/'descriptor_review_jobs.json')
        ledger = repair.w.read_json(r.work/'calls.json'); grants = repair.w.read_json(r.work/'retry_grants.json')
        for relative in manifest:
            folder = r.work/relative
            used = sum(c['job'] in (folder.name,parent) and c['status']!='cancelled'
                       and not repair.service_failure(c['status']) for c in ledger)
            if used >= baseline['config']['max_attempts']: raise ValueError('Inherited term budget exhausted')
            grants[folder.name] = {'api':repair.w.local_api_name(),'extra_attempts':0,'max_total_attempts':used+1,
                'granted_at':time.time(),'reason':'One source-based semantic recheck of the original reported descriptor; inherited parent attempts retained.'}
        repair.w.write_json(r.work/'retry_grants.json',grants)
        result=r.run_jobs('glossary_review',manifest='descriptor_review_jobs.json')
        repair.w.write_json(r.work/'descriptor_review_result.json',result)
        print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__': main()
