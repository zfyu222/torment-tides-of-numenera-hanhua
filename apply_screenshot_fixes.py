"""Apply reviewed AINiee corrections by logical CSV record, with a change ledger."""
import csv
import hashlib
import json
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'torment-tides-of-numenera_text.csv'
TARGET = ROOT / 'torment-tides-of-numenera_text_translated.csv'
CONFIG = ROOT / 'TranslateFiles/config/screenshot_fixes_20261020.json'
REPORT = ROOT / 'TranslateFiles/reports/screenshot_fixes_20261020.json'

def column(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    assert all(len(r) == 1 for r in rows)
    return [r[0] for r in rows]

def main():
    source, translated = column(SOURCE), column(TARGET)
    assert len(source) == len(translated) == 70163
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    changes = {int(k): v for k, v in config['translations'].items()}
    with zipfile.ZipFile(ROOT / 'backups/localized_en_original_20260819_085840.zip') as z:
        name = next(n for n in z.namelist() if n.endswith('/text/game/ttongui.stringtable'))
        gui = ET.fromstring(z.read(name))
        for entry in gui.findall('.//Entry'):
            key = entry.findtext('ID')
            if key in config['tutorial_layouts']:
                index = source.index(entry.findtext('DefaultText').replace('\r\n', '\n')) + 1
                changes[index] = config['tutorial_layouts'][key]
    if all(translated[k-1] == v for k,v in changes.items()):
        print('Corrections already applied.')
        return
    backup = ROOT / 'backups/screenshot_fixes_20261020'
    backup.mkdir(parents=True, exist_ok=True)
    if (backup / TARGET.name).exists():
        assert (backup / TARGET.name).read_bytes() == TARGET.read_bytes(), 'Existing backup differs'
    else:
        shutil.copy2(TARGET, backup / TARGET.name)
    ledger = []
    for ordinal, replacement in sorted(changes.items()):
        before = translated[ordinal-1]
        if ordinal in map(int, config['translations']):
            assert before == source[ordinal-1], (ordinal, 'source changed since review')
        else:
            assert re.sub(r'\s','',before) == re.sub(r'\s','',replacement), ordinal
        # Runtime variables and real rendering tags must remain byte-for-byte intact.
        tokens = r'\[(?:/?Color|Control|Global|Skill|FettleIcon|DamageIcon)[^\]]*\]|\{[^{}]*\}|</?a(?:\s[^>]*)?>|<quad\s[^>]*>'
        assert re.findall(tokens,before) == re.findall(tokens,replacement), ordinal
        ledger.append({'record': ordinal, 'source': source[ordinal-1], 'before': before,
                       'after': replacement, 'kind': 'translation' if str(ordinal) in config['translations'] else 'tutorial_line_breaks',
                       'review': '人工核对原意、现有专名、语气、标记与换行；教程仅调整显示换行。'})
        translated[ordinal-1] = replacement
    with TARGET.open('w',encoding='utf-8',newline='') as f:
        csv.writer(f,lineterminator='\r\n').writerows([v] for v in translated)
    assert len(column(TARGET)) == 70163 and all(translated)
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps({'records':len(source),'changed_records':len(ledger),
        'translation_fixes':len(config['translations']),'sha256':hashlib.sha256(TARGET.read_bytes()).hexdigest(),
        'changes':ledger},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Applied',len(ledger),'reviewed corrections.')

if __name__ == '__main__': main()
