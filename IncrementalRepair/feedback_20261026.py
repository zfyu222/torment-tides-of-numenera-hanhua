"""Source-bound repair of four screenshot reports, using configured API routing."""
import argparse
import copy
import json
import re
import shutil
import zipfile

import repair
from resume_current_api import run_lock

WORK = repair.PROJECT / 'TranslateFiles/feedback_20261026'


class FeedbackRepair(repair.Repair):
    def __init__(self):
        super().__init__(work=WORK)

    def render(self, payload, glossary=None):
        text, binding = super().render(payload, glossary)
        text += '\n本批仅修2026-10-26反馈的确定问题，保留无关措辞与所有原始换行/尾部空白。'
        text += '\nNumenera遵守用户已指定的“扭蒙拉”，复合词同样统一；(Truth)是玩家可见的“说实话”选项提示，应译成中文，保留括号，不是程序变量；test在完整叙述中是考验/试验，不是独立测试命令。'
        text += '\n本批Leave the shade alone的shade不是人物Shade/谢德：同一源资源x1511_reflection_seria ID1明确说“A woman-shaped hole in the air stands before you ... this woman-shade knows she does not belong here in your mind.”；ID3为“You turn back to the woman-shaped void. She continues to face you, hands held out imploringly, ignoring the Specter completely.”。据此修正，并用本句术语例外说明不要套用同形人名；不要修改其他人物Shade的姓名。'
        return text, binding


def prepare(r):
    if (r.work / 'review_jobs.json').exists():
        r.snapshot(); return {'status': 'existing_preparation_preserved'}
    with r.db() as db:
        meta = {x['key']: json.loads(x['value']) for x in db.execute('SELECT * FROM meta')}
        if db.execute('SELECT 1 FROM api_calls WHERE status="reserved"').fetchone() or db.execute('SELECT 1 FROM tasks WHERE status="running"').fetchone():
            raise ValueError('Parent has in-flight work')
        records = [dict(x) for x in db.execute('SELECT * FROM records ORDER BY ordinal')]
        budget = repair.budget_requests(db)
    r.work.mkdir(parents=True, exist_ok=True)
    for row in records: row['metadata'] = meta.get('contexts', {}).get(str(row['ordinal']), {})
    csv = r.project / (r.project.name + '_text_translated.csv')
    old_path = r.project / 'TranslateFiles' / meta['glossary']['path']
    baseline = {'source_file': r.project.name + '_text.csv', 'translation_file': csv.name,
        'source_sha256': repair.sha(r.project / (r.project.name + '_text.csv')),
        'translation_sha256': repair.sha(csv), 'glossary_file': str(old_path.relative_to(r.project)),
        'glossary_sha256': repair.sha(old_path), 'parent_revision': meta['revision'],
        'config': meta['config'], 'parent_budget_requests': budget}
    repair.w.write_json(r.work / 'baseline.json', baseline)
    repair.w.write_json(r.work / 'records.json', records)
    shutil.copy2(r.project / baseline['source_file'], r.work / 'source.csv')
    old = repair.w.read_json(old_path); new = copy.deepcopy(old)
    changes = []
    for table in ('characters', 'terms'):
        for row in new[table]:
            if '努曼内拉' in row.get('recommended_translation', ''):
                before = copy.deepcopy(row)
                row['recommended_translation'] = row['recommended_translation'].replace('努曼内拉', '扭蒙拉')
                row['term_reason'] = row.get('term_reason', '').replace('努曼内拉', '扭蒙拉')
                changes.append({'source': row['source'], 'before': before, 'after': copy.deepcopy(row),
                    'authority': 'User previously fixed Numenera as 扭蒙拉; spelling normalization, not a new semantic review.'})
    for row in new['non_translate']:
        if row['source'].casefold() == 'test':
            before = copy.deepcopy(row)
            row['applicability'] = {'mode': 'whole_record', 'case_sensitive': False, 'reason': 'Only a standalone test label is protected; embedded ordinary prose requires contextual translation.'}
            changes.append({'source': row['source'], 'before': before, 'after': copy.deepcopy(row), 'authority': 'Source/context and user feedback: prose test is translatable.'})
    removed = [x for x in new['non_translate'] if x['source'] == '(Truth)']
    new['non_translate'] = [x for x in new['non_translate'] if x['source'] != '(Truth)']
    if len(removed) != 1: raise ValueError('Unexpected Truth protection entries')
    changes.append({'source': '(Truth)', 'before': removed[0], 'after': None,
                    'authority': 'Visible source dialogue tag confirmed in screenshot, not an engine placeholder.'})
    repair.w.write_json(r.work / 'old_glossary.json', old)
    repair.w.write_json(r.work / 'new_glossary.json', new)
    repair.w.write_json(r.work / 'term_changes.json', changes)
    # Preserve the actual old semantic review verbatim. New changes above are
    # explicitly attributed policy/spelling corrections, not invented API votes.
    shutil.copy2(old_path.parent / 'term_decisions.json', r.work / 'term_decisions.json')
    selected = []
    for row in records:
        source, target = row['source'], row['translation']
        test_body = row['ordinal'] in (9238, 30960)
        if '努曼内拉' in target or '(Truth)' in target or row['ordinal'] == 54030 or test_body:
            if row['locked']: raise ValueError('Feedback scope contains a locked record')
            selected.append(row)
    ids = [x['id'] for x in selected]
    plan = {'term_changes': changes, 'term_affected_ids': [], 'scope_ids': ids,
        'preserved_records': len(records) - len(ids), 'structural_ids': [], 'individual_ids': [],
        'baseline_translation_sha256': baseline['translation_sha256'], 'new_glossary_sha256': repair.sha(r.work / 'new_glossary.json')}
    repair.w.write_json(r.work / 'repair_plan.json', plan)
    repair.w.write_json(r.work / 'translate_jobs.json', [])
    # Compare the exact shipped XML entries, not screenshot version guesses.
    with zipfile.ZipFile(r.project / 'Dispatch/torment-tides-of-numenera_子非鱼汉化1.4.zip') as archive:
        import xml.etree.ElementTree as ET
        matches = []
        for row in selected:
            loc = row['metadata']['resource']; path, key = loc.split('#ID='); number, field = key.split('/')
            rel = 'WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/' + path
            for origin, data in [('v1.4', archive.read(rel)), ('installed', (r.project / 'Game' / rel).read_bytes())]:
                entry = next(e for e in ET.fromstring(data).findall('.//Entry') if e.findtext('ID') == number)
                actual = entry.findtext(field) or ''
                if actual != row['translation'].replace('\r\n', '\n').replace('\r', '\n'):
                    raise ValueError('Current installed/published text differs from formal baseline')
                matches.append({'id': row['id'], 'origin': origin, 'resource': loc, 'matches_formal': True})
    repair.w.write_json(r.work / 'published_diagnosis.json', {'records': selected, 'file_checks': matches, 'all_four_feedback_types_still_present_in_v1.4': True})
    def build(group):
        payload = r.base_payload('review', baseline)
        payload['records'] = [{'id': x['id'], 'ordinal': x['ordinal'], 'source': x['source'],
            'translation': x['translation'], 'protection': [], 'metadata': x['metadata'],
            'exceptions': json.loads(x['exceptions']), 'locked': False} for x in group]
        payload['terms'] = repair.bridge.matched_terms(new, [x['source'] for x in group], baseline['config'])
        return payload
    queued = r.queue('review', selected, build, new, cap=40)
    return {'scope_records': len(ids), 'queued': queued, 'api_requests_issued': 0}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('command', choices=('prepare', 'review', 'export', 'integrate-prepare', 'integrate-apply'))
    args = parser.parse_args(); r = FeedbackRepair()
    r.work.mkdir(parents=True, exist_ok=True)
    with run_lock(r):
        if args.command == 'prepare': result = prepare(r)
        elif args.command == 'review': result = r.run_jobs('review')
        elif args.command == 'export': result = r.export_candidate()
        else:
            import integrate
            result = integrate.prepare(r) if args.command == 'integrate-prepare' else integrate.apply(r)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__': main()
