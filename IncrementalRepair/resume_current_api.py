"""One logged pass over pending jobs, preserving all historical attempts."""
import json
import time
import os
import argparse
from contextlib import contextmanager
import repair
from retry_current_api import POLICY_DIAGNOSTIC


@contextmanager
def run_lock(r):
    path = r.work / 'runner.lock'
    with path.open('x', encoding='utf8') as f:
        json.dump({'pid': os.getpid(), 'command': 'resume_current_api_one_pass'}, f)
    try:
        yield
    finally:
        path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempts-per-job', type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args()
    r = repair.Repair(); b = r.snapshot()
    with run_lock(r):
        ledger = repair.w.read_json(r.work / 'calls.json')
        if any(c['status'] == 'reserved' for c in ledger):
            raise ValueError('Unknown in-flight request')
        api = repair.w.local_api_name()
        folders = [r.work / p for p in repair.w.read_json(r.work / 'glossary_review_jobs.json')]
        folders = [p for p in folders if not (p / 'accepted.json').exists()]
        path = r.work / 'retry_grants.json'
        grants = repair.w.read_json(path) if path.exists() else {}
        batch = str(time.time_ns())
        repair.w.write_json(r.work / ('retry_grants_before_' + batch + '.json'), grants)
        for folder in folders:
            used = sum(c['job'] == folder.name and c['status'] != 'cancelled'
                       and not repair.service_failure(c['status']) for c in ledger)
            limit = min(used + args.attempts_per_job, b['config'].get('max_attempts', 3))
            if limit <= used:
                raise ValueError('Original job attempt budget exhausted; explicit new authorization required')
            grant = {'extra_attempts': 0,
                'max_total_attempts': limit, 'api': api, 'granted_at': time.time(),
                'reason': '2026-10-25 user selected a more stable API and requested resumption; one pass after successful live probe.',
                'diagnostic': POLICY_DIAGNOSTIC + ' evidence_rows只能引用本条提供的真实原文行号，不用ref序号代替；source_excerpt连续复制原文，不能改写或串接。'
                    'related_entries仅供实际核对同译名/别名，不修改它们。acknowledged_findings用本批f编号字符串数组，逐项实际核对，不输出输入回显。',
                'batch': batch}
            grants[folder.name] = grant
        repair.w.write_json(r.work / ('retry_grants_' + batch + '.json'), grants)
        repair.w.write_json(path, grants)
        repair.w.write_json(r.work / 'current_api_resume_jobs.json', [str(p.relative_to(r.work)) for p in folders])
        result = r.run_jobs('glossary_review', manifest='current_api_resume_jobs.json')
        repair.w.write_json(r.work / 'current_api_resume_result.json', result)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
