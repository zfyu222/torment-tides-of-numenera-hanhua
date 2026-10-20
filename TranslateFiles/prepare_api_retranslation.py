"""Prepare a fresh custom run without importing the previous AINiee decisions."""
import csv
import hashlib
import json
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def main():
    folder = PROJECT / 'TranslateFiles'
    assert not (folder / 'state/workflow.sqlite3').exists(), 'Already initialized'
    source_path = PROJECT / 'torment-tides-of-numenera_text.csv'
    with source_path.open(encoding='utf-8-sig', newline='') as f:
        source = [row[0] for row in csv.reader(f)]
    index = {text.replace('\r\n','\n').replace('\r','\n'): n for n,text in enumerate(source,1)}
    locations = defaultdict(list)
    with zipfile.ZipFile(PROJECT / 'backups/localized_en_original_20260819_085840.zip') as z:
        for name in sorted(z.namelist()):
            if not name.endswith('.stringtable'): continue
            root = ET.fromstring(z.read(name))
            for entry in root.findall('.//Entry'):
                for field in ('DefaultText','FemaleText'):
                    value = (entry.findtext(field) or '').replace('\r\n','\n').replace('\r','\n')
                    if value.strip():
                        assert value in index, name
                        locations[index[value]].append((name, entry.findtext('ID'), field))
    assert len(locations) == len(source) == 70163
    contexts = {}
    for ordinal, refs in locations.items():
        name, entry_id, field = refs[0]
        parts = Path(name).parts
        category = parts[2]
        group = '/'.join(parts[2:4]) if category == 'conversations' else category
        note = '资源定位仅表示存储位置，不证明说话者身份或剧情先后。'
        if len(refs)>1: note += f'同一原文共有{len(refs)}处引用。'
        if category == 'game': note += '界面文本，注意长度、按钮用途和中文阅读。'
        if name.endswith('ttongui.stringtable') and entry_id in ('1399','1423','1425'):
            note += '已实测此教程中文长行会触发自动缩字，请在自然语义边界分为三行；保留控制图标。'
        contexts[str(ordinal)] = {'group':group,'resource':f'{name}#ID={entry_id}/{field}',
            'scene':'/'.join(parts[3:]) if category=='conversations' else '',
            'text_type':{'conversations':'对白或叙述（具体类型以本句为准）','quests':'任务文本','game':'系统或界面文本'}.get(category,category),
            'note':note}
    # Exact runtime markers are attested by the game's existing managed sources.
    code_root = PROJECT / 'Analysis/decompiled/Assembly-CSharp'
    literals = set()
    for path in code_root.rglob('*.cs'):
        code = path.read_text(encoding='utf-8-sig')
        literals.update(re.findall(r'\.Replace\("(\[[A-Za-z][A-Za-z0-9 _]*\])"', code))
        if 'StringTokenReplacement' in path.parts:
            literals.update(re.findall(r'"(\[[A-Za-z][A-Za-z0-9 _]*\])"', code))
    literal_pattern = '|'.join(re.escape(v) for v in sorted(literals, key=lambda v:(-len(v),v)))
    square = r'\[(?:Global|GLOBAL|Color|DamageIcon|FettleIcon|DefenseIcon|Control|Skill):[^\]\r\n]+\]|\[/Color\]|\[[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?\]'
    if literal_pattern: square += '|' + literal_pattern
    config = {'workflow':'custom','backend':'api','source_language':'英语','target_language':'简体中文',
        'protect_named_curly':True,'polish':False,'context_records':0,
        'style':'忠实原意，使用自然、成熟、可读的简体中文。保留第九世界的陌生感、哲学意味、黑色幽默及人物各自口吻，避免生硬直译、网络梗、过度文言和无依据解释。叙述中you通常译为“你”。术语冻结后保持一致，普通词的语境例外在协议字段说明，绝不把翻译分析、术语争论、道歉或输出说明混入正文。<...>中的自然语言是心灵对白，保留尖括号并翻译其内容；普通[...]中的动作、判定、对白也需翻译。只有实际运行时标记和渲染标签保留。开发占位与虚构语言须按出处判断，不因含括号或英文就整体禁翻；测试/开发说明保持可辨识，不杜撰成正式剧情。界面文字简洁清楚；有明确排版元数据时按要求分行。',
        'placeholder_family_overrides':{'square_bracket':square,'angle_tag':r'(?:<quad\s+class="[A-Za-z0-9_-]+">|</?a(?:\s+name="[^"]+")?>)','rpgmaker_code':None},
        'exclusions':[{'markers':'','regex':r'\{[^{}]*\}','info':'本游戏花括号内容由GUIUtils.StripDebugText作为开发注释移除；保留原样，不将说明混入正文'}]}
    save(folder/'config/api_retranslation_selection.json',config)
    save(folder/'source/prepared_context.json',contexts)
    save(folder/'config/runtime_marker_evidence.json',{'source':'既有TokenReplacer及DynamicObjectDataTokens托管代码','literal_markers':sorted(literals),'square_regex':square})
    backup=folder/'backups/ainiee_before_custom_20261020'
    backup.mkdir(parents=True,exist_ok=True)
    translated=PROJECT/'torment-tides-of-numenera_text_translated.csv'
    target=backup/translated.name
    if target.exists(): assert target.read_bytes()==translated.read_bytes()
    else: shutil.copy2(translated,target)
    save(folder/'reports/api_retranslation_baseline.json',{'records':len(source),'resource_fields':sum(map(len,locations.values())),
        'old_translation_sha256':hashlib.sha256(translated.read_bytes()).hexdigest(),
        'source_sha256':hashlib.sha256(source_path.read_bytes()).hexdigest(),
        'old_translation_backup':str(target.relative_to(PROJECT)),
        'policy':'旧正式译稿与游戏文件保留；新译经试译校准、全量翻译、独立审校和程序验收后才导出。'})
    print(json.dumps({'records':len(source),'groups':len({v['group'] for v in contexts.values()}),'runtime_literal_markers':len(literals)},ensure_ascii=False))

if __name__=='__main__':main()
