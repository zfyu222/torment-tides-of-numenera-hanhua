"""Read-only hash check for the five initially identified image targets."""
import hashlib
import json
from pathlib import Path

project = Path(__file__).resolve().parents[2]
base = project/'ImageText'
data = (project/'Game/WIN/TidesOfNumenera_Data').resolve()
binding = json.loads((base/'source_binding_20261027.json').read_text(encoding='utf-8'))
provenance = json.loads((base/'provenance_20261027.json').read_text(encoding='utf-8'))
lookup = {(v['asset'],v['path_id']):k for k,v in provenance.items()}
assets, results = {}, []

def file_hash(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle,'sha256').hexdigest()

for item in binding['targets']:
    name, ident = item['asset'], item['path_id']
    if Path(name).name != name:
        raise ValueError('Asset must be a single file name')
    asset = (data/name).resolve()
    if not asset.is_relative_to(data):
        raise ValueError('Asset escapes game data directory')
    if name not in assets:
        assets[name] = file_hash(asset)
    if assets[name] != item['asset_sha256']:
        raise ValueError(f'Asset has changed: {name}')
    stream = (data/item['stream_path']).resolve()
    if not stream.is_relative_to(data):
        raise ValueError('Stream escapes game data directory')
    offset, remaining = item['stream_offset'], item['stream_size']
    if not isinstance(offset,int) or not isinstance(remaining,int) or offset < 0 or remaining <= 0:
        raise ValueError('Invalid bound stream range')
    h = hashlib.sha256()
    with stream.open('rb') as handle:
        handle.seek(offset)
        while remaining:
            block=handle.read(min(1048576,remaining))
            if not block: raise ValueError('Stream ended inside bound texture')
            h.update(block);remaining-=len(block)
    if h.hexdigest() != item['texture_data_sha256']:
        raise ValueError(f'Texture stream changed: {name}:{ident}')
    image = base/'export_crunch_20261027'/lookup[(name,ident)]
    if file_hash(image) != item['snapshot_png_sha256']:
        raise ValueError(f'Snapshot PNG changed: {name}:{ident}')
    results.append({'asset':name,'path_id':ident,'asset_sha256':assets[name],
                    'texture_data_sha256':h.hexdigest(),'snapshot_sha256':item['snapshot_png_sha256']})

print(json.dumps({'status':'passed','checked_targets':len(results),'targets':results},ensure_ascii=False))
