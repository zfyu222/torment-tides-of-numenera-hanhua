"""Bind a completed engine export to image-text inventory without modifying images."""
import hashlib
import json
import os
from pathlib import Path

project = Path(__file__).resolve().parents[2]
stage = project/'ImageText'
source = stage/'export_crunch_20261027'
report = json.loads((source/'report.json').read_text(encoding='utf-8'))
if len(report['inputs']) != 140 or report['failures']:
    raise ValueError('Finish the engine export and resolve failures first')
provenance = json.loads((source/'provenance.json').read_text(encoding='utf-8'))
target = stage/'input_20261027'
if target.exists():
    raise ValueError('Refusing to replace an existing input snapshot')
target.mkdir()
excluded = []
font_ids = {2627, 2819, 3400, 3703, 4504, 4866, 6062, 6425}
accepted = {}
for name, metadata in provenance.items():
    if metadata['asset'] == 'resources.assets' and metadata['path_id'] in font_ids:
        excluded.append(dict(file=name, provenance=metadata, classification='font_glyph_atlas',
                             reason='Conversation agent viewed all eight on ImageText/calibration_20261027/font-atlases.png: packed individual font glyphs, not composed UI wording. Keep font resources unchanged; not a no-text claim.'))
        continue
    os.link(source/name, target/name)
    accepted[name] = metadata
(stage/'provenance_20261027.json').write_text(json.dumps(accepted,ensure_ascii=False),encoding='utf-8')
summary = {'exported_textures':len(provenance),'inventory_input_files':len(accepted),
           'excluded_font_atlases':excluded,'export_seconds':report['elapsed_seconds'],
           'asset_files':report['inputs'],'export_failures':report['failures'],
           'skipped_zero_dimensions':report['skipped'],
           'formal_baseline':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                              [project/'torment-tides-of-numenera_text.csv',project/'torment-tides-of-numenera_text_translated.csv']},
           'game_modified':False, 'paid_api_requests':0}
(stage/'extraction_20261027.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
policy={'script':'latin','ordinary_score':0.95,'negative_samples':20,'weak_samples':10,
        'ordinary_samples':10,'qwen_batch':100,'seed':42,'families':{},'images':{}}
for name,metadata in accepted.items():
    if metadata['texture_name'] in ('Torment_Logo_Loading_Screen','frontend-menu-torment'):
        policy['images'][name]={'known_text':True,'risks':['art']}
policy['calibration']={'reviewer':'conversation_agent','images_seen':24,
                       'additional_font_atlas_views':8,'ordinary_families_validated':0,
                       'evidence':'ImageText/calibration_20261027/contact-1.png through contact-4.png and font-atlases.png. Two Torment title designs, inXile brand, glyph atlases and non-text surfaces. No ordinary composed UI font family established; keep unknown families on risk route.'}
(stage/'policy_20261027.json').write_text(json.dumps(policy,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'input':str(target),'images':len(accepted),'font_atlases_preserved':len(excluded)}))
