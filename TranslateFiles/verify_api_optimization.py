"""Bounded live verification in isolated fixtures; never modifies production state."""
import copy
import argparse
import csv
import hashlib
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, 'D:/StaticHanHua/Tools/localization')
import translation_workflow as w
import workflow_task_contract as contract
import ainiee_bridge as bridge
from workflow_profile import usage_totals
from workflow_tokens import count_tokens

project = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--run-name', required=True)
parser.add_argument('--modes', choices=('baseline', 'optimized'), nargs='+', default=['baseline', 'optimized'])
parser.add_argument('--request-limit', type=int, choices=range(1, 5), default=4)
args = parser.parse_args()
if not args.run_name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.run_name):
    raise SystemExit('run-name must be a simple directory name')
folder = project/'TranslateFiles/verification'/args.run_name
folder.mkdir(parents=True, exist_ok=True)
report_file = folder/'report.json'
if report_file.exists():
    raise SystemExit('Existing verification retained; no implicit paid replay')
production = w.Workflow(project)
with production.db() as db:
    config = production.config(db)
    tasks = [dict(x) for x in db.execute('SELECT * FROM tasks WHERE stage="extract" AND revision=?', (production.meta(db, 'revision'),))]
    runs = [dict(x) for x in db.execute('SELECT * FROM batch_runs')]
    before_status = [dict(x) for x in db.execute('SELECT status,count(*) n FROM tasks GROUP BY status')]
chosen = None
for task in tasks:
    data = json.loads(task['payload'])
    hit = next((r for r in data['records'] if 'White. Death.' in r.get('source', '')), None)
    if hit:
        chosen = [hit] + [r for r in data['records'] if r['id'] != hit['id']][:5]
        break
assert chosen

# Reconstruct every sampled metadata object before comparing token estimates.
first = {}
for run in runs: first.setdefault(run['task_id'], run)
sample = list(first.values())[::max(1, len(first)//100)][:100]
old_tokens = new_tokens = 0
for run in sample:
    original = Path(run['input_file']).read_text(encoding='utf-8')
    old_data = json.loads(original.split('```json\n', 1)[1].rsplit('```', 1)[0])
    new_data = copy.deepcopy(old_data); contract.compact_record_metadata(new_data)
    for old, new in zip(old_data['records'], new_data['records']):
        restored = {}
        for ref in new.get('metadata_refs', []): restored.update(new_data['shared_metadata'][ref])
        restored.update(new.get('metadata', {}))
        resource = restored.get('resource')
        if isinstance(resource, dict) and 'prefix_ref' in resource:
            restored['resource'] = new_data['shared_metadata_text'][resource['prefix_ref']] + resource['suffix']
        assert restored == old.get('metadata', {})
        assert new['source'] == old['source'] and new['ordinal'] == old['ordinal']
    head = original.split('```json\n', 1)[0]
    revised = head + 'shared_metadata 是共用上下文表；每条 metadata_refs 引用其字段，与本条 metadata 合并理解。resource 的 prefix_ref 引用 shared_metadata_text，完整资源位置为该前缀与 suffix 原样拼接。\n```json\n' + json.dumps(new_data, ensure_ascii=False, separators=(',', ':')) + '\n```\n'
    old_tokens += count_tokens(original); new_tokens += count_tokens(revised)

settings, key = w.load_api_settings(config)
settings = {**settings, 'target_platform': 'deepseek', 'think_switch': True, 'think_depth': 'high', 'concurrency': 1}
client = bridge.AINieeAPI(settings, key); del key
report = {'status': 'running', 'request_limit': args.request_limit, 'requests': [], 'stages': [],
          'model': settings['model_name'], 'thinking': 'enabled; existing service/model, high',
          'local_benchmark': {'batches': len(sample), 'before_tokens': old_tokens, 'after_tokens': new_tokens,
                              'reduction_percent': round(100*(old_tokens-new_tokens)/old_tokens, 2),
                              'metadata_reconstruction': 'all sampled records identical; sources and ordinals identical'},
          'original_ordinals': [r['ordinal'] for r in chosen]}
w.write_json(report_file, report)

class Bounded:
    def request(self, system, user):
        if len(report['requests']) >= report['request_limit']:
            raise bridge.ApiFailure('verification_request_limit', False)
        entry = {'number': len(report['requests'])+1, 'usage': {'usage_reported': False}}
        report['requests'].append(entry); w.write_json(report_file, report)
        try:
            text, usage = client.request(system, user)
        except bridge.ApiFailure as error:
            entry.update(error=str(error), usage=error.usage or {'usage_reported': False})
            w.write_json(report_file, report); raise
        entry['usage'] = usage; w.write_json(report_file, report)
        return text, usage
    def close(self): pass

try:
    with (folder/'execution.log').open('w', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
        for mode in args.modes:
            root = folder/mode; root.mkdir()
            source = root/'sample_text.csv'
            with source.open('w', encoding='utf-8', newline='') as stream:
                csv.writer(stream).writerows([[r['source']] for r in chosen])
            contexts = {str(i): r['metadata'] for i, r in enumerate(chosen, 1)}
            context_path = root/'context.json'; w.write_json(context_path, contexts)
            flow = w.Workflow(root)
            flow.init(source, {'backend': 'api', 'max_attempts': 1, 'batch_records': 6,
                'game_background': config['game_background'], 'style': config['style'],
                'source_language': config['source_language'], 'target_language': config['target_language'],
                'api': {'max_completion_tokens': 16384, 'concurrency': 1}}, context_path)
            with patch.object(contract, 'compact_record_metadata', (lambda x: None) if mode == 'baseline' else contract.compact_record_metadata):
                result = w.run_api(flow, 'extract', requester_factory=lambda *_: Bounded())
            report['stages'].append({'mode': mode, 'stage': 'extract', **{k: result.get(k) for k in ('accepted','failed','stage_clean','needs_attention','pending_handoffs')}})
            w.write_json(report_file, report)
            if result.get('paused') or result.get('needs_attention') or result.get('pending_handoffs'):
                raise ValueError(mode + ' extraction incomplete; no paid automatic replay')
            if mode == 'optimized':
                result = w.run_api(flow, 'glossary_review', requester_factory=lambda *_: Bounded())
                report['stages'].append({'mode': mode, 'stage': 'glossary_review', **{k: result.get(k) for k in ('accepted','failed','stage_clean','needs_attention','pending_handoffs')}})
                w.write_json(report_file, report)
                if result.get('paused') or result.get('needs_attention') or result.get('pending_handoffs'):
                    raise ValueError('Review incomplete')
                report['frozen'] = flow.freeze_glossary()
        report['status'] = 'completed'
except Exception as error:
    report.update(status='needs_attention', error=str(error))
finally:
    client.close()
    with production.db() as db:
        report['production_state_unchanged'] = before_status == [dict(x) for x in db.execute('SELECT status,count(*) n FROM tasks GROUP BY status')]
    report['usage'] = usage_totals(r['usage'] for r in report['requests'])
    w.write_json(report_file, report)
print(json.dumps(report, ensure_ascii=False))
