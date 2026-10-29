"""Full real-resource identity roundtrip, reusing existing translations only."""
import csv
import json
import html
import re
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

P=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(P.parents[1]/'Tools/localization'))
from extract_stringtable_occurrences import extract
from workflow_resource_occurrences import locator, sha

work=P/'repack/silver_occurrence_20261029/identity_roundtrip'
work.mkdir(parents=True,exist_ok=True)
source=work/'probe_text.csv'
target=work/'probe_text_translated_raw.csv'
original=P/'repack/feedback_20261028/original/en'
localized=P/'repack/silver_occurrence_20261029/localized/en'
if not source.exists():
    summary=extract(original,source)
mapping=json.loads(source.with_suffix('.mapping.json').read_text(encoding='utf-8'))
values={}
for path in sorted(localized.rglob('*.stringtable')):
    resource='en/'+path.relative_to(localized).as_posix()
    for entry in re.findall(r'<Entry>.*?</Entry>',path.read_bytes().decode('utf-8-sig'),re.S):
        entry_id=html.unescape(re.search(r'<ID>(.*?)</ID>',entry,re.S).group(1))
        for field in ('DefaultText','FemaleText'):
            match=re.search(r'<'+field+r'>(.*?)</'+field+'>',entry,re.S)
            text=html.unescape(match.group(1)) if match else ''
            if text.strip():values[locator(resource,entry_id,field)]=text
assert len(values)==len(mapping['records'])==89239
expected=[[values[row['resource']]] for row in mapping['records']]
if target.exists():
    with target.open(encoding='utf-8',newline='') as f:assert list(csv.reader(f))==expected
else:
    with target.open('x',encoding='utf-8',newline='') as f:csv.writer(f).writerows(expected)
output=work/'localized_raw_preserved/en'
result=subprocess.run([sys.executable,str(P/'repack_stringtables.py'),str(source),str(target),str(original),str(output)],
    capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
if result.returncode:raise RuntimeError(result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace'))
files=[f for f in localized.rglob('*') if f.is_file()]
assert len(files)==2251
assert all(sha(f)==sha(output/f.relative_to(localized)) for f in files)
with source.open(encoding='utf-8',newline='') as f:rows=list(csv.reader(f))
silver=[(row['resource'],values[row['resource']]) for row in mapping['records'] if rows[row['ordinal']-1]==['Silver']]
assert len(silver)==3 and sorted(x[1] for x in silver)==['西尔弗','银潮','银潮']
report=dict(status='full_real_resource_roundtrip_passed',records=89239,files=2251,silver_occurrences=silver,
    byte_identical_to_scoped_fix=True,api_requests=0,game_started=False)
(P/'Analysis/resource_occurrence_roundtrip_20261029.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=True))
