"""Read-only extraction cost/failure audit; no API calls or state mutations."""
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, 'D:/StaticHanHua/Tools/localization')
from translation_workflow import Workflow, write_json
from workflow_tokens import count_tokens

project = Path(__file__).resolve().parent.parent
flow = Workflow(project)
with flow.db() as db:
    calls = [dict(x) for x in db.execute('SELECT * FROM api_calls')]
    runs = [dict(x) for x in db.execute('SELECT * FROM batch_runs')]
    tasks = [dict(x) for x in db.execute('SELECT * FROM tasks WHERE stage="extract" AND revision=?', (flow.meta(db, 'revision'),))]

statuses = {}
for call in calls:
    item = statuses.setdefault(call['status'], collections.Counter())
    item['requests'] += 1
    usage = json.loads(call['usage'] or '{}')
    item['unknown_usage'] += not usage.get('usage_reported', False)
    for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        item[key] += usage.get(key, 0) or 0
    item['reasoning_tokens'] += (usage.get('completion_tokens_details') or {}).get('reasoning_tokens', 0) or 0
    item['cached_prompt_tokens'] += (usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0) or 0
    if usage.get('finish_reason') == 'length':
        item['length_terminated'] += 1

rejections = collections.Counter()
examples = {}
for run in runs:
    path = Path(run['result_file']).with_name('rejection.json')
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
        error = data['error']
        key = error if not any(x in error for x in ('line ', 'column ', 'char ')) else 'JSON parse error'
        rejections[key] += 1
        examples.setdefault(key, {'file': str(path.relative_to(project)), 'error': error})

# Count a deterministic representative sample of original first handoffs.
# These are local tokenizer estimates, not provider billing numbers.
first = {}
for run in runs:
    first.setdefault(run['task_id'], run)
sample = list(first.values())[::max(1, len(first)//100)][:100]
components = collections.Counter()
for run in sample:
    text = Path(run['input_file']).read_text(encoding='utf-8')
    data = json.loads(text.split('```json\n', 1)[1].rsplit('```', 1)[0])
    records = data.get('records', [])
    source = '\n'.join(x.get('source', '') for x in records)
    metadata = json.dumps([x.get('metadata', {}) for x in records], ensure_ascii=False, separators=(',', ':'))
    components['full_input_tokens'] += count_tokens(text)
    components['source_only_tokens'] += count_tokens(source)
    components['metadata_tokens'] += count_tokens(metadata)
    components['records'] += len(records)

report = {
    'scope': 'All stored api_calls for the current project, extraction only; excludes manual probes and Codex usage.',
    'statuses': statuses,
    'rejection_files': dict(rejections),
    'rejection_examples': examples,
    'local_input_sample': {'batches': len(sample), **components, 'note': 'Components are separately tokenized estimates and are not exactly additive.'},
    'task_status': dict(collections.Counter(x['status'] for x in tasks)),
    'limitations': ['Unknown usage is not zero consumption.', 'The user portal 23.11M cannot be equated to this cumulative project sum without its date range and billing aggregation.', 'Reasoning is part of completion tokens; cached prompt tokens are part of prompt tokens, not extra charges to add again.', 'A zero/missing reasoning field does not prove the provider performed no reasoning.'],
}
path = flow.root/'reports/api_extract_cost_audit_20261021.json'
write_json(path, report)
print(json.dumps(report, ensure_ascii=False))
