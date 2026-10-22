"""Indexes for dispatch/collection lookups; no workflow state or budget changes."""


def ensure_dispatch_indexes(db):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    indexes = (
        ('tasks', 'dispatch_tasks', 'stage,revision,backend,status,id'),
        ('tasks', 'dispatch_task_counts', 'revision,status'),
        ('records', 'dispatch_record_counts', 'stage'),
        ('quality_authors', 'dispatch_authors', 'instance,record_id,stage'),
        ('batch_runs', 'dispatch_batch_status', 'status,round,task_id,token'),
        ('batch_runs', 'dispatch_batch_task', 'task_id,token,round'),
        ('batch_repair_plans', 'dispatch_plan_session', 'session_id'),
        ('api_calls', 'dispatch_call_task', 'task_id'),
    )
    for table, name, columns in indexes:
        if table in tables:
            db.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table}({columns})')
