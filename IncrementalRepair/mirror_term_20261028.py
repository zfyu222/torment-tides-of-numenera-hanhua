"""Audit user-provided mirror-term candidates, then recheck only affected batches."""
import argparse
import copy
import json
import shutil

import feedback_20261028 as feedback
import repair
from resume_current_api import run_lock

MAIN = feedback.WORK


class MirrorTermRepair(feedback.FeedbackRepair):
    def __init__(self):
        repair.Repair.__init__(self, work=MAIN / 'mirror_terms')

    def prepare(self):
        if (self.work / 'baseline.json').exists():
            self.snapshot()
            return {'existing_snapshot_preserved': True}
        self.work.mkdir(parents=True, exist_ok=True)
        for name in ('baseline.json', 'records.json', 'source.csv'):
            shutil.copy2(MAIN / name, self.work / name)
        baseline = repair.w.read_json(self.work / 'baseline.json')
        prior_calls = repair.w.read_json(MAIN / 'calls.json')
        if any(c['status'] == 'reserved' for c in prior_calls):
            raise ValueError('Main requests still in flight')
        baseline['parent_budget_requests'] += sum(c['status'] != 'cancelled' and not repair.service_failure(c['status']) for c in prior_calls)
        repair.w.write_json(self.work / 'baseline.json', baseline)
        shutil.copy2(MAIN / 'new_glossary.json', self.work / 'old_glossary.json')
        rows = repair.w.read_json(self.work / 'records.json')
        original = repair.w.read_json(self.work / 'old_glossary.json')
        audit = copy.deepcopy(original)
        for table in repair.TABLES:
            audit[table] = []
        audit['terms'] = [dict(source='doppelganger', recommended_translation='二重身',
            category_path='其他', term_kind='game_term', enforcement='required',
            term_reason='待API裁决的候选，来自玩家反馈和既有译文；另一个既有候选为“分身”。不是已确认术语。',
            evidence_rows=[53017, 53018, 53019, 53020, 53021, 53023, 53025, 53027, 53028])]
        repair.glossary_tool.refresh_stats(audit)
        repair.attach_corpus_evidence(audit, rows)
        repair.w.write_json(self.work / 'terms_input.json', {'extra': {'analysis_v1': audit}})
        repair.glossary_tool.audit(self.work / 'terms_input.json', self.work / 'source.csv', self.work / 'term_audit')
        return {'provisional_candidates': ['二重身', '分身'], 'paid_requests': 0}

    def render(self, payload, glossary=None):
        text, binding = super().render(payload, glossary)
        text += ('\n本批只裁决doppelganger这一项候选。二重身/分身均来自原有译文和用户反馈，'
            'recommended_translation只是待审候选，不能当成先前已通过。请结合镜子、平行自我、'
            '同一镜前选项的全部语境确定统一译名，必要时修正候选；提供真实四维判断。'
            '不要把同一源场景的同一原词因选项人物外貌不同而拆成两个中文术语。'
            '可以限定适用语境，普通reflection/copy/duplicate不随之强制改名。只审此条，不添加其他术语。')
        return text, binding

    def plan(self):
        return {'mirror_term_audit_built': True}


def requeue():
    r = feedback.FeedbackRepair()
    r.snapshot()
    if (MAIN / 'mirror_recheck_plan.json').exists():
        return {'existing_recheck_plan_preserved': True, 'paid_requests': 0}
    mirror = MirrorTermRepair()
    mirror.snapshot()
    reviewed = repair.w.read_json(mirror.work / 'new_glossary.json')
    term = [x for x in reviewed['terms'] if x['source'] == 'doppelganger']
    if len(term) != 1:
        raise ValueError('API has not established a mirror term; inspect actual decision')
    original = repair.w.read_json(MAIN / 'old_glossary.json')
    changes, annotations = repair.term_changes(original, reviewed, r.snapshot()['config'])
    repair.w.write_json(MAIN / 'new_glossary.json', reviewed)
    repair.w.write_json(MAIN / 'mirror_term_provenance.json', dict(
        candidate_origin='Existing user-reported published translations; provisional only.',
        audit_directory=str(mirror.work), term_decisions_sha256=repair.sha(mirror.work / 'term_decisions.json'),
        actual_api_review_jobs=repair.w.read_json(mirror.work / 'glossary_review_jobs.json')))
    repair.w.write_json(MAIN / 'additional_term_audits.json', ['mirror_terms'])
    repair.w.write_json(MAIN / 'term_changes.json', {'changes': changes, 'annotation_only': annotations})
    plan = repair.w.read_json(MAIN / 'repair_plan.json')
    plan.update(term_changes=changes, annotation_only=annotations, new_glossary_sha256=repair.sha(MAIN/'new_glossary.json'))
    repair.w.write_json(MAIN / 'repair_plan.json', plan)
    paths = repair.w.read_json(MAIN / 'review_jobs.json')
    import scope_match
    config = r.snapshot()['config']
    scope_match.prepare(reviewed, config, repair.bridge.patterns(config['protect_named_curly'] is not False,
        config['exclusions'], config.get('placeholder_family_overrides')))
    kept, replaced, created = [], [], []
    for relative in paths:
        folder = MAIN / relative
        payload = repair.w.read_json(folder / 'payload.json')
        if not any('doppelganger' in row['source'].casefold() for row in payload['records']):
            kept.append(relative)
            continue
        def build(group):
            next_payload = copy.deepcopy(payload)
            next_payload.pop('task_id', None)
            next_payload.pop('input_hash', None)
            next_payload['records'] = group
            next_payload['attempt_parent_job'] = payload['task_id']
            next_payload['terms'] = repair.bridge.matched_terms(reviewed,
                [row['source'] for row in group], r.snapshot()['config'])
            next_payload['diagnostic'] = '镜像术语已由独立API四维审校确认；按本批术语统一同一场景译名，保留其他正确内容。'
            return next_payload
        r.queue('review', payload['records'], build, reviewed, manifest='mirror_recheck_jobs.json')
        created.extend(repair.w.read_json(MAIN / 'mirror_recheck_jobs.json'))
        replaced.append(relative)
    if not replaced:
        raise ValueError('No affected mirror batches')
    repair.w.write_json(MAIN / 'review_jobs_before_mirror.json', paths)
    repair.w.write_json(MAIN / 'review_jobs.json', kept + created)
    repair.w.write_json(MAIN / 'mirror_recheck_plan.json', dict(
        preserved_jobs=kept, replaced_jobs=replaced, new_jobs=created, attempts_reset=False,
        term_decisions_sha256=repair.sha(mirror.work / 'term_decisions.json')))
    # Import the real additional term calls with their original identity and usage.
    calls = repair.w.read_json(MAIN / 'calls.json')
    extra = repair.w.read_json(mirror.work / 'calls.json')
    existing = {x['id'] for x in calls}
    calls.extend(x for x in extra if x['id'] not in existing)
    repair.w.write_json(MAIN / 'calls.json', calls)
    return {'preserved_jobs': len(kept), 'mirror_recheck_jobs': len(created), 'paid_requests': 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'prepare-terms', 'terms', 'collect-terms', 'requeue'])
    args = parser.parse_args()
    r = MirrorTermRepair()
    r.work.mkdir(parents=True, exist_ok=True)
    with run_lock(r):
        if args.command == 'prepare': result = r.prepare()
        elif args.command == 'prepare-terms': result = r.prepare_terms()
        elif args.command == 'terms': result = r.run_jobs('glossary_review')
        elif args.command == 'collect-terms': result = r.collect_terms()
        else: result = requeue()
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
