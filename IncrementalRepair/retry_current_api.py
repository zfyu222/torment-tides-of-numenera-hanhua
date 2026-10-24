"""One explicitly authorized extra attempt on one failed existing term job."""
import json
import time
import repair

POLICY_DIAGNOSTIC = ('本轮复核对象是旧冻结表，保留条目原本没有term_kind/enforcement/term_reason。'
    '每个保留条目都必须通过edits.patch明确补齐这三个字段，不能只给entry_reviews四维结论而漏掉分类。'
    '例如某条经核对确为专名，其实际ref对应patch应包含term_kind=proper_name、enforcement=required、'
    'term_reason=本条真实原文依据，并给evidence_rows；这只是结构说明，不预判任何条目的分类。'
    '普通词用quarantine，游戏词game_term才可依语境选required/reference；proper_name不能reference。'
    '仍须完整逐条四维证据和连续原文引用，全部结果放在顶层decisions中；不返回placeholder、输入回显或省略号。')


def main():
    r = repair.Repair(); r.snapshot()
    if (r.work / 'runner.lock').exists():
        raise ValueError('Finish the previous repair runner first')
    ledger = repair.w.read_json(r.work / 'calls.json')
    if any(c['status'] == 'reserved' for c in ledger):
        raise ValueError('Unknown in-flight request')
    folders = [r.work / p for p in repair.w.read_json(r.work / 'glossary_review_jobs.json')]
    folder = next(p for p in folders if not (p / 'accepted.json').exists())
    api = repair.w.local_api_name()
    grants_file = r.work / 'retry_grants.json'
    grants = repair.w.read_json(grants_file) if grants_file.exists() else {}
    if folder.name not in grants:
        used = sum(c['job'] == folder.name and c['status'] != 'cancelled' and not repair.service_failure(c['status']) for c in ledger)
        grants[folder.name] = {'extra_attempts': max(0, used + 1 - r.snapshot()['config'].get('max_attempts', 3)),
            'max_total_attempts': used + 1, 'api': api, 'granted_at': time.time(),
            'reason': '2026-10-25 user selected a more stable API and explicitly requested another try; first one existing failed batch only.',
            'diagnostic': POLICY_DIAGNOSTIC}
        repair.w.write_json(grants_file, grants)
    repair.w.write_json(r.work / 'current_api_probe_jobs.json', [str(folder.relative_to(r.work))])
    result = r.run_jobs('glossary_review', manifest='current_api_probe_jobs.json')
    repair.w.write_json(r.work / 'current_api_probe_result.json', result)
    print(json.dumps({'job': folder.name, 'api': api, **result}, ensure_ascii=False))


if __name__ == '__main__':
    main()
