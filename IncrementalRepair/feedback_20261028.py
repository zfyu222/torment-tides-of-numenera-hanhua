"""Six screenshot reports: scoped terminology and independent API repairs."""
import argparse
import copy
import json
import re
import shutil

import repair
from resume_current_api import run_lock

WORK = repair.PROJECT / 'TranslateFiles/feedback_20261028'
BRANCH = re.compile(r'\|[^|\r\n]+\|[^|\r\n]+\|')
CREATURE = re.compile(r'\bstich(?:us|a)\b', re.I)
STATUS = re.compile(r'\b(?:success|failure)\b', re.I)


def grammatical_branch(pair):
    left, right = pair.split('|')[1:3]
    left, right = left.casefold(), right.casefold()
    return (right in (left + 's', left + 'es') or
        (left.endswith('y') and right == left[:-1] + 'ies') or
        {left, right} in ({'are', 'is'}, {'have', 'has'}, {'do', 'does'}, {'was', 'were'}))


def selected_term(table, row):
    source = row['source']
    if table == 'non_translate':
        return bool(BRANCH.fullmatch(source)) or source.casefold().strip('[]') in {
            'success', 'failure', 'critical success', 'critical failure'}
    return bool(CREATURE.search(source)) or 'doppelganger' in source.casefold()


class FeedbackRepair(repair.Repair):
    def __init__(self):
        super().__init__(work=WORK)

    def prepare(self):
        if (self.work / 'baseline.json').exists():
            self.snapshot()
            return {'status': 'existing_snapshot_preserved'}
        with self.db() as db:
            meta = {x['key']: json.loads(x['value']) for x in db.execute('SELECT * FROM meta')}
            if db.execute('SELECT 1 FROM api_calls WHERE status="reserved"').fetchone() or db.execute(
                'SELECT 1 FROM tasks WHERE status="running" OR (revision=? AND status IN ("pending","failed"))',
                (meta['revision'],)).fetchone():
                raise ValueError('Parent workflow has unfinished work')
            rows = [dict(x) for x in db.execute('SELECT * FROM records ORDER BY ordinal')]
            budget = repair.budget_requests(db)
        source = self.project / (self.project.name + '_text.csv')
        translated = self.project / (self.project.name + '_text_translated.csv')
        glossary_path = self.project / 'TranslateFiles' / meta['glossary']['path']
        if repair.read_column(source) != [x['source'] for x in rows] or repair.read_column(translated) != [x['translation'] for x in rows]:
            raise ValueError('Formal CSV/database alignment changed')
        self.work.mkdir(parents=True)
        for row in rows:
            row['metadata'] = meta['contexts'].get(str(row['ordinal']), {})
        baseline = dict(source_file=source.name, translation_file=translated.name,
            source_sha256=repair.sha(source), translation_sha256=repair.sha(translated),
            glossary_file=str(glossary_path.relative_to(self.project)), glossary_sha256=repair.sha(glossary_path),
            parent_revision=meta['revision'], config=meta['config'], parent_budget_requests=budget)
        repair.w.write_json(self.work / 'baseline.json', baseline)
        repair.w.write_json(self.work / 'records.json', rows)
        shutil.copy2(source, self.work / 'source.csv')
        original = repair.w.read_json(glossary_path)
        repair.w.write_json(self.work / 'old_glossary.json', original)
        audit = copy.deepcopy(original)
        for table in repair.TABLES:
            audit[table] = [copy.deepcopy(x) for x in original[table] if selected_term(table, x)]
            for row in audit[table]:
                for field in ('extraction_candidates', 'extraction_tasks', 'extraction_count', 'provisional_selection'):
                    row.pop(field, None)
        repair.glossary_tool.refresh_stats(audit)
        repair.attach_corpus_evidence(audit, rows)
        repair.w.write_json(self.work / 'terms_input.json', {'extra': {'analysis_v1': audit}})
        repair.glossary_tool.audit(self.work / 'terms_input.json', self.work / 'source.csv', self.work / 'term_audit')
        return {'scoped_terms': {t: len(audit[t]) for t in repair.TABLES}, 'paid_requests': 0}

    def render(self, payload, glossary=None):
        # Existing ID transport, API routing, retry budgets and evidence validators.
        payload = copy.deepcopy(payload)
        if payload['stage'] == 'glossary_review':
            payload['revision_request'] = (
                '本轮仅审截图反馈命中的现有词条。游戏原文明确stichus是sticha的单数，中文应采用同一生物名称，'
                '相同对象的复合词也一致；请依据出处确定统一译名，不能因单复数另造物种。'
                '引擎TokenReplacer.ReplaceListenerTokens用 |左分支|右分支| 选择玩家或同伴表达，分支里的自然语言应翻译，'
                '只保留竖线语法及[Actor Name]等真实变量，不能整段禁翻。GUIUtils.GetTaskResultString将gui ID56/57/58/59显示给玩家，'
                'Success/Failure及其方括号提示是可译结果，不是内部枚举。请据此审校non_translate的适用性并隔离错误禁翻。'
                '本次相关镜像场景原文均用doppelganger；必要时可基于提供的原文增加该概念的术语及明确适用范围，'
                '不要混同普通reflection、copy、duplicate或其他怪物的替身。保留全部逐项四维证据，未涉及词条不改。')
        text, transport = super().render(payload, glossary)
        if payload['stage'] != 'glossary_review':
            text += ('\n本轮为2026-10-28截图定向修复，只改确定错误、保留无关措辞。'
                '竖线表达式是运行时选择语法，其两侧自然语言都需翻译；不能保留Your/your/you/open等英文。'
                '可以两侧都使用相同中文动词，但必须保留两侧非空的分支及[Actor Name]变量。'
                '成功/失败提示是玩家可见内容；保留方括号。'
                '同一镜中自我形象的doppelganger用统一术语；其他语境依原句指代判断。'
                'He wasn\'t quite as handsome - or alive - after that是在说光束穿眼后不再英俊、也丢了性命的黑色幽默，'
                '应自然传达含义，避免“没那么活着”一类生硬搭配。不得删除原有开发注释和换行/尾空白。'
                '修改举证必须逐字引用该条原文中的连续片段，doppelganger单词本身也可以作为对应术语修改的摘录；'
                '不能在摘录前自行补the等原文没有的词。每条evidence内引用编号只能定义一次。')
        return text, transport

    def prepare_terms(self):
        return super().prepare_terms()

    def validate_result(self, payload, result, glossary):
        result = super().validate_result(payload, result, glossary)
        if payload['stage'] == 'glossary_review':
            return result
        originals = {x['id']: x for x in payload['records']}
        for row in result['records']:
            source = repair.bridge.restore(originals[row['id']]['source'],
                originals[row['id']].get('protection', []), allow_original=True)
            expected = BRANCH.findall(source)
            actual = BRANCH.findall(row['translation'])
            if re.search(r'(?<!\[)Actor Name(?!\])', source) and re.search(r'(?<!\[)Actor Name(?!\])', row['translation']):
                raise ValueError(row['id'] + ': source bare Actor Name is literal text, not a bracketed runtime variable')
            # English subject/verb inflection may become one invariant Chinese
            # verb. Actor/pronoun alternatives must still select the right referent.
            required = sum(not grammatical_branch(pair) for pair in expected)
            if not required <= len(actual) <= len(expected):
                raise ValueError(row['id'] + ': runtime branch count changed; retain actor/pronoun alternatives')
            for pair in actual:
                visible = re.sub(r'\[[^\]]+\]', '', pair)
                if re.search(r'\b(?:you|your|he|his|she|her|open|opens|need|needs|are|is|come|comes|swing|swings|smash|smashes)\b', visible, re.I):
                    raise ValueError(row['id'] + ': untranslated natural language inside runtime branch')
        return result

    def collect_terms(self):
        self.snapshot()
        snapshot = repair.w.read_json(self.work / 'term_audit/glossary_original.json')
        decisions = dict(review_complete=True, review_summary='Scoped screenshot terminology review; actual API evidence retained.',
            snapshot_sha256=repair.sha(self.work / 'term_audit/glossary_original.json'),
            source_sha256=repair.sha(self.work / 'source.csv'))
        fields = ('reviewed_refs','entry_reviews','acknowledged_findings','edits','quarantine','additions','allow_no_match')
        for key in fields:
            decisions[key] = []
        instances = {}
        for relative in repair.w.read_json(self.work / 'glossary_review_jobs.json'):
            folder = self.work / relative
            saved = repair.w.read_json(folder / 'accepted.json')
            payload = self.term_payload(repair.w.read_json(folder / 'payload.json'))
            if saved['input_hash'] != payload['input_hash']:
                raise ValueError('Term evidence binding changed')
            repair.validate_glossary_reviews(saved['result']['decisions'], payload)
            for key in fields:
                decisions[key].extend(saved['result']['decisions'].get(key, []))
            for entry in payload['entries']:
                instances[entry['ref']] = saved.get('entry_instances', {}).get(entry['ref']) or saved['instance']
        expected = {f'{t}:{i}' for t in repair.TABLES for i in range(len(snapshot[t]))}
        if set(instances) != expected or len(decisions['entry_reviews']) != len(expected):
            raise ValueError('Scoped term review incomplete')
        decisions['review_instances'] = instances
        decisions['acknowledged_findings'] = list(dict.fromkeys(decisions['acknowledged_findings']))
        repair.w.write_json(self.work / 'term_decisions.json', decisions)
        build = self.work / 'term_build'
        if not (build / 'glossary_reviewed.json').exists():
            repair.glossary_tool.build(self.work / 'term_audit/glossary_original.json', self.work / 'source.csv',
                self.work / 'term_decisions.json', build)
        reviewed = repair.w.read_json(build / 'glossary_reviewed.json')
        original = repair.w.read_json(self.work / 'old_glossary.json')
        revised = copy.deepcopy(original)
        for table in repair.TABLES:
            selected = {x['source'] for x in snapshot[table]}
            revised[table] = [x for x in revised[table] if x['source'] not in selected] + reviewed[table]
            if len({x['source'] for x in revised[table]}) != len(revised[table]):
                raise ValueError('Scoped term review added a duplicate source')
        repair.glossary_tool.refresh_stats(revised)
        repair.glossary_tool.validate_shape(revised)
        repair.w.write_json(self.work / 'new_glossary.json', revised)
        return self.plan()

    def plan(self):
        baseline = self.snapshot()
        old = repair.w.read_json(self.work / 'old_glossary.json')
        new = repair.w.read_json(self.work / 'new_glossary.json')
        changes, annotations = repair.term_changes(old, new, baseline['config'])
        rows = repair.w.read_json(self.work / 'records.json')
        protected = repair.bridge.patterns(baseline['config']['protect_named_curly'], baseline['config']['exclusions'],
            baseline['config'].get('placeholder_family_overrides'))
        changed = {x['source'] for x in changes}
        affected = []
        for row in rows:
            visible = row['source']
            target = row['translation']
            for _, pattern in protected:
                visible = pattern.sub('', visible)
                target = pattern.sub('', target)
            needs = (bool(CREATURE.search(visible)) or 'doppelganger' in visible.casefold()
                or bool(BRANCH.search(visible)) or bool(STATUS.search(target)) or row['ordinal'] == 1912)
            if needs:
                if row['locked']:
                    raise ValueError('Feedback target is locked')
                affected.append(row['id'])
        plan = dict(term_changes=changes, annotation_only=annotations, term_affected_ids=[],
            scope_ids=affected, structural_ids=[], individual_ids=[], preserved_records=len(rows)-len(affected),
            baseline_translation_sha256=baseline['translation_sha256'], new_glossary_sha256=repair.sha(self.work/'new_glossary.json'))
        repair.w.write_json(self.work / 'repair_plan.json', plan)
        repair.w.write_json(self.work / 'translate_jobs.json', [])
        repair.w.write_json(self.work / 'structural_findings.json', [])
        repair.w.write_json(self.work / 'individual_cases.json', [])
        return {'review_scope': len(affected), 'term_changes': len(changes), 'paid_requests': 0}

    def recheck_alive(self, actor=False):
        self.snapshot()
        ordinal = 12621 if actor else 1912
        label = 'actor' if actor else 'alive'
        receipt = self.work / (label + '_recheck_plan.json')
        if receipt.exists():
            return {'existing_recheck_preserved': True}
        paths = repair.w.read_json(self.work / 'review_jobs.json')
        candidates = []
        for relative in paths:
            folder = self.work / relative
            payload = repair.w.read_json(folder / 'payload.json')
            if any(row['ordinal'] == ordinal for row in payload['records']):
                candidates.append((relative, folder, payload))
        if len(candidates) != 1:
            raise ValueError('Expected exactly one source-bound alive case')
        relative, folder, payload = candidates[0]
        accepted = repair.w.read_json(folder / 'accepted.json')
        current = {row['id']: row['translation'] for row in accepted['result']['records']}
        glossary = repair.w.read_json(self.work / 'new_glossary.json')
        def build(group):
            value = copy.deepcopy(payload)
            value.pop('task_id', None)
            value.pop('input_hash', None)
            value['attempt_parent_job'] = payload['task_id']
            value['records'] = copy.deepcopy(group)
            for row in value['records']:
                row['translation'] = current[row['id']]
                if row['ordinal'] == ordinal:
                    row['diagnostic'] = ('原文|You|Actor Name|中的Actor Name没有方括号，因此引擎不会把它替换成人名，'
                        '它是原文自身的裸文字缺陷，不能误当成真的[Actor Name]运行变量。'
                        '请按同段his/he的人称语境将这处裸字串自然中文化，别留下Actor Name英文；'
                        '不要新增原文没有的方括号变量，也不要改动其他真正带方括号的变量。') if actor else (
                        '最新候选把or alive表达成“不那么像个活人”，容易读成外貌病态而不是死亡。'
                        '原文光束贯穿眼睛后，alive是生命状态；请自然、明确地传达丢了性命的黑色幽默，'
                        '不要把死亡弱化成外貌变化，也不要沿用“没那么活着”的生硬搭配。')
            return value
        self.queue('review', payload['records'], build, glossary, manifest=label + '_recheck_jobs.json')
        replacements = repair.w.read_json(self.work / (label + '_recheck_jobs.json'))
        repair.w.write_json(self.work / ('review_jobs_before_' + label + '.json'), paths)
        repair.w.write_json(self.work / 'review_jobs.json', [p for p in paths if p != relative] + replacements)
        repair.w.write_json(receipt, {'replaced_job': relative, 'new_jobs': replacements,
            'attempts_reset': False, 'reason': 'Source-bound accuracy/tone concern; actual prior result retained.'})
        return {'quality_recheck_jobs': len(replacements), 'records': len(payload['records']), 'paid_requests': 0}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['prepare','prepare-terms','terms','collect-terms','prepare-review','review','recheck-alive','recheck-actor','export','integrate-prepare','integrate-apply'])
    args = p.parse_args()
    r = FeedbackRepair()
    with run_lock(r):
        if args.command == 'prepare': result = r.prepare()
        elif args.command == 'prepare-terms': result = r.prepare_terms()
        elif args.command == 'terms': result = r.run_jobs('glossary_review')
        elif args.command == 'collect-terms': result = r.collect_terms()
        elif args.command == 'prepare-review': result = r.prepare_review()
        elif args.command == 'review': result = r.run_jobs('review')
        elif args.command == 'recheck-alive': result = r.recheck_alive()
        elif args.command == 'recheck-actor': result = r.recheck_alive(actor=True)
        elif args.command == 'export': result = r.export_candidate()
        else:
            import integrate
            result = integrate.prepare(r) if args.command == 'integrate-prepare' else integrate.apply(r)
    if args.command.startswith('integrate-'):
        result = {k: v for k, v in result.items() if k in ('status', 'revision', 'stage_project',
            'changed_records', 'scope_records', 'preserved_outside_scope', 'formal_translation_sha256',
            'model_request_budget_before', 'model_request_budget_after', 'incremental_model_requests_added')}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
