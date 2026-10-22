"""Separate service failures from model-request budgets; retain the raw ledger."""
SERVICE_PREFIXES = ('APIConnectionError:', 'APITimeoutError:', 'InternalServerError:',
                    'RateLimitError:', 'PermissionDeniedError:', 'AuthenticationError:',
                    'BadRequestError:', 'NotFoundError:', 'APIStatusError:')
SERVICE_CODES = {'empty_response', 'unexpected_html_response', 'stream_interrupted',
                 'incomplete_stream'}
CONNECTION_RETRY_LIMIT = 3
CONNECTION_RETRY_BASE_SECONDS = 2


def connection_retry_delay(status, retries_used):
    """Three extra attempts for transient transport faults, never HTTP denials."""
    transient = (status.startswith(('APIConnectionError:', 'APITimeoutError:'))
                 or status in ('stream_interrupted', 'incomplete_stream'))
    if transient and retries_used < CONNECTION_RETRY_LIMIT:
        return CONNECTION_RETRY_BASE_SECONDS * (2 ** retries_used)
    return None


def service_failure(status):
    return isinstance(status, str) and (status.startswith(SERVICE_PREFIXES) or status in SERVICE_CODES)


def budget_requests(db):
    db.create_function('is_api_service_failure', 1, service_failure)
    return db.execute('SELECT count(*) FROM api_calls WHERE status!="cancelled" '
                      'AND NOT is_api_service_failure(status)').fetchone()[0]


def effective_attempts(db, task):
    raw = task['attempt']
    if task['backend'] != 'api' or not raw:
        return raw
    columns = {row[1] for row in db.execute('PRAGMA table_info(api_calls)')}
    if 'session_id' not in columns:
        return raw
    db.create_function('is_api_service_failure', 1, service_failure)
    # New calls bind their exact raw task attempt, including reliability parts.
    # Legacy initial/transport sessions each consumed one attempt; legacy repair
    # parts share a token+round, so credit them conservatively as one round.
    bound = 'a.task_attempt' if 'task_attempt' in columns else 'NULL'
    credits = db.execute(f'''SELECT count(*) FROM (
        SELECT CASE WHEN {bound} IS NOT NULL THEN 'attempt:' || {bound}
                    WHEN b.round=0 THEN 'session:' || a.session_id
                    ELSE 'round:' || b.token || ':' || b.round END AS attempt_key
        FROM api_calls a JOIN batch_runs b ON b.id=a.session_id
        WHERE a.task_id=? AND a.status NOT IN ('cancelled','reserved','interrupted')
        GROUP BY attempt_key
        HAVING min(is_api_service_failure(a.status))=1
    )''', (task['id'],)).fetchone()[0]
    return max(0, raw - credits)
