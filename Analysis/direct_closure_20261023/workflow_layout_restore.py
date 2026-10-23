"""Explicit, hash-bound restoration of layout in failed reviewed candidates."""
import copy
import hashlib
import json
import re
import uuid

import ainiee_bridge as bridge


def text_hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def restore_exact_layout(source, translation, newlines=None):
    expected = re.findall(r'\r\n|\r|\n', source) if newlines is None else newlines
    if len(re.findall(r'\r\n|\r|\n', translation)) != len(expected):
        raise ValueError('Paragraph count differs; layout-only restoration is unsafe')
    separators = iter(expected)
    value = re.sub(r'\r\n|\r|\n', lambda _: next(separators), translation)
    leading = source[:len(source) - len(source.lstrip(' \t'))]
    trailing = source[len(source.rstrip(' \t')):]
    return leading + value.strip(' \t') + trailing


def restore_review_layout(flow, request):
    """Keep API semantic evidence; explicitly attribute the operator layout check.

    Only pending revalidation is set here. review-scan still checks every gate.
    Raw model replies, original canonical items and repair-stop history survive.
    """
    from translation_workflow import encoded, write_json
    stage = request.get('stage', 'review')
    actor, reason, entries = request.get('reviewer'), request.get('reason'), request.get('records')
    if (stage not in ('review', 'final_review') or not isinstance(actor, str) or not actor.strip()
            or not isinstance(reason, str) or not reason.strip() or not isinstance(entries, list)
            or not 1 <= len(entries) <= 8 or len({r['id'] for r in entries}) != len(entries)):
        raise ValueError('Small explicit layout restore requires reviewer, reason and unique hash-bound records')
    with flow.db() as db:
        config = flow.config(db); flow.review_tables(db); flow.batch_tables(db)
        if (not flow.meta(db, 'paused') or (flow.root / 'state/api_round.lock').exists()
                or db.execute('SELECT 1 FROM tasks WHERE status="running"').fetchone()
                or db.execute('SELECT 1 FROM api_calls WHERE status="reserved"').fetchone()):
            raise ValueError('Pause and finish all workers before layout restoration')
        rules, glossary = flow.rules(db, config), flow.glossary(db)
        updates = []
        for entry in entries:
            row = db.execute('SELECT * FROM records WHERE id=?', (entry['id'],)).fetchone()
            candidate = db.execute('SELECT * FROM review_candidates WHERE record_id=? AND stage=?',
                                   (entry['id'], stage)).fetchone()
            if (not row or row['locked'] or not candidate or candidate['status'] != 'failed'
                    or text_hash(row['source']) != entry.get('source_sha256')
                    or text_hash(candidate['item']) != entry.get('candidate_sha256')):
                raise ValueError('Stale, locked or non-failed layout candidate: ' + entry['id'])
            task = dict(db.execute('SELECT * FROM tasks WHERE id=?', (candidate['task_id'],)).fetchone())
            if task['status'] != 'done' or task['revision'] != flow.meta(db, 'revision'):
                raise ValueError('Candidate task is not current and complete')
            before = json.loads(candidate['item']); item = copy.deepcopy(before)
            issues = bridge.record_structural_issues(row, item['translation'], rules, config)
            if not issues or not set(issues).issubset({'boundary_whitespace', 'physical_newlines'}):
                raise ValueError('Only newline style and boundary whitespace may be restored')
            constraint = bridge.record_constraint(row, config)
            fixed = restore_exact_layout(row['source'], item['translation'], constraint.get('physical_newlines'))
            original = json.loads(candidate['original'])
            changes = [c for c in item.get('changes', []) if c.get('category') != 'placeholders']
            if fixed == original['translation']:
                changes = []
            elif not changes:
                raise ValueError('Restoration must retain explicit semantic change evidence')
            for change in changes:
                if change.get('after') != item['translation']:
                    raise ValueError('Existing change does not bind the candidate translation')
                change['after'] = fixed
            item['translation'], item['changes'] = fixed, changes
            layout = {'reviewer': actor, 'reason': reason,
                      'semantic_reviewer': candidate['instance'], 'source_sha256': entry['source_sha256'],
                      'prior_candidate_sha256': entry['candidate_sha256'], 'restored_issues': issues,
                      'newlines': re.findall(r'\r\n|\r|\n', fixed),
                      'leading': fixed[:len(fixed) - len(fixed.lstrip(' \t'))],
                      'trailing': fixed[len(fixed.rstrip(' \t')):]}
            item['checks']['placeholders'] = {'status': 'pass', 'reviewer': actor,
                'evidence': '人工格式复核：按绑定源文恢复换行类型和边界空白；段落数量及正文字符保持不变。' + encoded(layout)}
            item['layout_restoration'] = layout
            item['reason'] += ' 人工格式复核已撤销候选中统一LF/删除边界空白的处理，按源文恢复。'
            strict = json.loads(task['payload']); strict['strict_review'] = True
            task['payload'] = encoded(strict)
            flow.validate_body_item(db, task, {}, item, original, config, rules, glossary)
            result = json.loads(task['result'])
            if next((r for r in result['records'] if r['id'] == entry['id']), None) != before:
                raise ValueError('Canonical task result differs from the candidate')
            updates.append((row, candidate, before, item, task))
        audit = flow.root / f'history/layout_restore_{uuid.uuid4().hex}.json'
        write_json(audit, {'request': request, 'records': [
            {'id': r['id'], 'before': before, 'after': item} for r, _, before, item, _ in updates]})
        for row, candidate, before, item, task in updates:
            # Reload so multiple restored records in one task retain each other.
            result = json.loads(db.execute('SELECT result FROM tasks WHERE id=?', (task['id'],)).fetchone()[0])
            result['records'] = [item if r['id'] == row['id'] else r for r in result['records']]
            db.execute('UPDATE tasks SET result=? WHERE id=?', (encoded(result), task['id']))
            db.execute('UPDATE batch_items SET item=? WHERE task_id=? AND token=? AND record_id=?',
                       (encoded(item), task['id'], task['lease_token'], row['id']))
            db.execute('UPDATE review_candidates SET item=?,status="pending",diagnostic=NULL WHERE record_id=? AND stage=?',
                       (encoded(item), row['id'], stage))
            db.execute('INSERT INTO record_lineage(task_id,token,record_id,stage,instance,action,item) VALUES (?,?,?,?,?,?,?)',
                       (task['id'], task['lease_token'], row['id'], stage, actor, 'restore_review_layout', encoded(item)))
        flow.event(db, 'restore_review_layout', {'ids': [r['id'] for r, *_ in updates], 'actor': actor,
                                               'audit': str(audit), 'reason': reason})
        return {'status': 'pending_revalidation', 'records': len(updates), 'audit_file': str(audit),
                'next_action': 'review-scan', 'attempts_reset': False}
