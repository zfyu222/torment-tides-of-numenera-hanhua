"""Bounded first body batches, reused by the actual affected-scope stage."""
import json
import repair
from resume_current_api import run_lock


def main():
    r = repair.Repair(); r.snapshot()
    with run_lock(r):
        selected = []
        for path in repair.w.read_json(r.work / 'translate_jobs.json'):
            payload = repair.w.read_json(r.work / path / 'payload.json')
            if any(x['ordinal'] in (57207, 62257, 63811) for x in payload['records']):
                selected.append(path)
        if not 1 <= len(selected) <= 3:
            raise ValueError('Unexpected representative body batch coverage')
        repair.w.write_json(r.work / 'current_body_probe_jobs.json', selected)
        result = r.run_jobs('translate', manifest='current_body_probe_jobs.json')
        repair.w.write_json(r.work / 'current_body_probe_result.json', result)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
