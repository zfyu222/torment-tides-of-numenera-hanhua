"""Derive an explicit font-excluded scope from the existing canonical inventory.

Keep the complete inventory/partial scan intact. Reuse exact image snapshots and
per-image/model-bound caches; the official scanner still checks pixels before use.
"""
import json
import os
from pathlib import Path
import shutil
import sys

project = Path(__file__).resolve().parents[2]
repo = project.parents[1]
sys.path.insert(0, str(repo/'Tools/image_text'))
from core import canonical, digest, read_json, write_json

base = project/'ImageText'
old = base/'work_20261027'
new = base/'work_20261027_v2'
if new.exists():
    raise ValueError('Preserve existing scopes; target must be new')
manifest = read_json(old/'manifest.json')
if manifest['manifest_hash'] != digest(canonical({k:v for k,v in manifest.items() if k!='manifest_hash'})):
    raise ValueError('Parent inventory is not intact')
font_names = {
    'resources.assets__2185__Bangers_SDF_Atlas.png',
    'resources.assets__2186__IMPACT_SDF_Atlas.png',
    'resources.assets__6617__ARIAL_SDF_Atlas.png',
    'resources.assets__6618__QuattrocentoSans_SDF_Atlas.png',
    'resources.assets__6619__QuattrocentoSans_SDF_Atlas.png',
    'resources.assets__6620__ARCADE_SDF_Atlas.png',
    'resources.assets__6621__Avalon_Bold_SDF_Atlas.png',
    'resources.assets__6622__QuattrocentoSans_Atlas.png',
}
excluded = [x for x in manifest['images'] if all(s['path'] in font_names for s in x['sources'])]
excluded_ids = {x['image_id'] for x in excluded}
images = [x for x in manifest['images'] if x['image_id'] not in excluded_ids]
files = [x for x in manifest['files'] if x['image_id'] not in excluded_ids]
scoped = dict(manifest, images=images, files=files, parent_manifest_hash=manifest['manifest_hash'],
              scope_reason='Exclude eight additional font glyph atlas references visually checked on ImageText/calibration_20261027/sdf-atlases.png; preserve parent inventory and partial scan')
scoped.pop('manifest_hash')
scoped['manifest_hash'] = digest(canonical(scoped))
(new/'images').mkdir(parents=True)
for image in images:
    name = image['image_id']+'.png'
    os.link(old/'images'/name, new/'images'/name)
copied = 0
for cache in (old/'cache').glob('*/*.json'):
    row = read_json(cache)
    if row['image_id'] not in excluded_ids:
        target = new/'cache'/cache.parent.name/cache.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cache, target)
        copied += 1
write_json(new/'manifest.json', scoped)
report = dict(parent_manifest_hash=manifest['manifest_hash'], scoped_manifest_hash=scoped['manifest_hash'],
              excluded_images=excluded, reason=scoped['scope_reason'],
              unique_images=len(images), source_files=len(files), reusable_cache_images=copied,
              parent_scope_preserved=True, human_approval=False,
              reviewer='conversation_agent', model_label='current conversation model; runtime label unavailable')
write_json(base/'font_scope_20261027.json', report)
print(json.dumps({k:v for k,v in report.items() if k not in ('excluded_images','reason')}, ensure_ascii=False))
