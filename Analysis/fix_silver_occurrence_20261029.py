"""Reuse the approved Silver character term at its exact resource field.

No API translation, database revision change, game launch or release. The existing
formal CSV remains the tide translation; a source-bound resource resolution is
the authoritative additional input to all future stringtable builds.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

P=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(P.parents[1]/'Tools/localization'))
from workflow_resource_occurrences import column, locator, sha, text_sha

WORK=P/'repack/silver_occurrence_20261029'
PAYLOAD=WORK/'localized/en'
MANIFEST=P/'TranslateFiles/config/resource_translation_resolutions.json'
REPORT=P/'Analysis/silver_occurrence_20261029.json'
CHAR='en/text/game/characters.stringtable#ID=661/DefaultText'
TIDE='en/text/game/ttongui.stringtable#ID=72/DefaultText'
TEST='en/text/conversations/test/jeremy_tidal_surge_test.stringtable#ID=56/DefaultText'


def prepare():
    source=P/(P.name+'_text.csv');target=P/(P.name+'_text_translated.csv')
    assert column(source)[49318]=='Silver' and column(target)[49318]=='银潮'
    glossary=P/'TranslateFiles/glossary/incremental_revision_11/glossary_reviewed.json'
    approved=json.loads(glossary.read_text(encoding='utf-8'))
    assert any(x['source']=='Silver' and x.get('recommended_translation')=='西尔弗' for x in approved['terms'])
    refs=[]
    with zipfile.ZipFile(P/'backups/localized_en_original_20260819_085840.zip') as z:
        for name in sorted(z.namelist()):
            if not name.endswith('.stringtable'):continue
            for entry in ET.fromstring(z.read(name)).findall('.//Entry'):
                for field in ('DefaultText','FemaleText'):
                    if entry.findtext(field)=='Silver':refs.append(locator(name,entry.findtext('ID'),field))
    assert set(refs)=={CHAR,TIDE,TEST}
    evidence=dict(path=glossary.relative_to(P).as_posix(),sha256=sha(glossary))
    data=dict(schema_version=1,source_sha256=sha(source),records=[dict(ordinal=49319,
        source_sha256=text_sha('Silver'),default_translation='银潮',
        policy='existing approved character term reused at its character-name field; tide uses retained',
        occurrences=[dict(resource=key,translation='西尔弗' if key==CHAR else '银潮',
            reason=('角色名字段；正文I am Silver及既有冻结角色术语均为西尔弗。' if key==CHAR else
                    '潮汐UI/测试字段；保留既有潮汐义银潮，与角色名分开。'),
            **({'approved_term':evidence} if key==CHAR else {})) for key in refs])])
    if MANIFEST.exists():
        assert json.loads(MANIFEST.read_text(encoding='utf-8'))==data,'Existing resolution changed'
    else: MANIFEST.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return source,target


def main(install):
    source,target=prepare()
    old=json.loads((P/'TranslateFiles/reports/deployment_feedback_20261028.json').read_text(encoding='utf-8'))
    if not PAYLOAD.exists():
        original=P/'repack/feedback_20261028/original/en'
        assert original.is_dir()
        run=subprocess.run([sys.executable,str(P/'repack_stringtables.py'),str(source),str(target),str(original),str(PAYLOAD)],
            capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        if run.returncode:raise RuntimeError(run.stdout.decode(errors='replace')+run.stderr.decode(errors='replace'))
    files={f.relative_to(PAYLOAD).as_posix():sha(f) for f in PAYLOAD.rglob('*') if f.is_file()}
    assert set(files)==set(old['file_sha256']) and len(files)==2251
    changed=[key for key in files if files[key]!=old['file_sha256'][key]]
    assert changed==['text/game/characters.stringtable'],changed
    def field(relative,entry_id):
        entries=ET.parse(PAYLOAD/relative).getroot().findall('.//Entry')
        return next(e.findtext('DefaultText') for e in entries if e.findtext('ID')==entry_id)
    assert field('text/game/characters.stringtable','661')=='西尔弗'
    assert field('text/game/ttongui.stringtable','72')=='银潮'
    assert field('text/conversations/test/jeremy_tidal_surge_test.stringtable','56')=='银潮'
    # Compare the complete parsed character table: only the requested field changes.
    oldtree=ET.parse(P/'repack/feedback_20261028/localized/en/text/game/characters.stringtable').getroot()
    newtree=ET.parse(PAYLOAD/'text/game/characters.stringtable').getroot()
    oldvalues={(e.findtext('ID'),f):e.findtext(f) for e in oldtree.findall('.//Entry') for f in ('DefaultText','FemaleText')}
    newvalues={(e.findtext('ID'),f):e.findtext(f) for e in newtree.findall('.//Entry') for f in ('DefaultText','FemaleText')}
    assert oldvalues.keys()==newvalues.keys()
    assert [key for key in oldvalues if oldvalues[key]!=newvalues[key]]==[('661','DefaultText')]
    report=dict(status='offline_verified',source_sha256=sha(source),translation_sha256=sha(target),
        resolution_sha256=sha(MANIFEST),approved_glossary_sha256=sha(P/'TranslateFiles/glossary/incremental_revision_11/glossary_reviewed.json'),
        payload_directory=str(PAYLOAD),files_verified=len(files),changed_files=changed,changed_fields=1,
        file_sha256=files,api_requests=0,semantic_translation='reuse_existing_approved_term',
        game_started=False,in_game_validation='pending_user_test',published=False,
        other_known_issue='R0012644 branch leak remains outside this requested fix; full export/release guard remains active')
    if install:
        check=subprocess.run(['powershell','-NoProfile','-Command','if (Get-Process -Name TidesOfNumenera -ErrorAction SilentlyContinue) { exit 3 }'],
            capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        if check.returncode:raise ValueError('Game is running')
        game=(P/'Game').resolve()
        destination=(game/'WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en').resolve()
        assert destination.is_relative_to(game)
        current={key:sha(destination/key) for key in files}
        if current==files:
            report['status']='already_installed_verified'
        else:
            assert current==old['file_sha256'],'Installed baseline changed; keep user files'
            backup=P/'backups/silver_occurrence_20261029.zip'
            with zipfile.ZipFile(backup,'x',compression=zipfile.ZIP_DEFLATED) as z:
                for key in changed:z.write(destination/key,key)
            with zipfile.ZipFile(backup) as z:
                assert all(hashlib.sha256(z.read(key)).hexdigest()==current[key] for key in changed)
            try:
                for key in changed:shutil.copy2(PAYLOAD/key,destination/key)
                assert all(sha(destination/key)==files[key] for key in files)
            except BaseException:
                with zipfile.ZipFile(backup) as z:
                    for key in changed:(destination/key).write_bytes(z.read(key))
                raise
            report.update(status='installed_files_verified',backup=str(backup))
        report['game_locale_directory']=str(destination)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key!='file_sha256'},ensure_ascii=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--install',action='store_true')
    main(parser.parse_args().install)
