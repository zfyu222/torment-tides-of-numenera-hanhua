"""Collect the entire Sol inspection before dispatching any semantic repairs."""
import json
from workflow_quality import SOL_SCOPE_POLICY
from workflow_tokens import count_tokens


class SolRoundMixin:
    def write_sol_inputs(self, report, round_id, config, *, kind='final'):
        from translation_workflow import write_json, encoded
        from workflow_task_contract import WORKER_INSTRUCTION
        items = [i for key in ('records_to_check', 'consistency', 'glossary_checks') for i in report[key]]
        ids = [i.get('id') for i in items]
        if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('Sol allocation requires unique explicit check IDs')
        prefix = (f'reports/sol_rounds/round_{round_id:05d}' if kind == 'final' else
                  f'reports/pilot_inspections/{report["report_hash"]}')
        instruction = ('Sol 只裁决本包明确未解决的争议，记录 pass/contextual/repair；全部检查结束前不得派发修订。'
                       if kind == 'final' else
                       '验收本包试译样本、术语及一致性证据；通过项记录 pass/contextual 和真实理由，'
                       '发现问题列出具体记录 ID 及原因，由主流程统一退回修复；不得将问题项标记通过。')
        def packet(batch):
            value = {'round': round_id, 'report_hash': report['report_hash'], 'checks': batch,
                'instruction': WORKER_INSTRUCTION + instruction,
                'output_template': {'report_hash': report['report_hash'], 'reviewer': 'sol', 'summary': '',
                    'decisions': [{'id': i['id'], 'disposition': 'pending', 'reason': ''} for i in batch]}}
            if kind == 'pilot':
                prefixes = {str(i['review']['task_id']) + ':' + str(i['review']['instance']) + ':'
                            for i in batch if i.get('review')}
                value['pilot_batch_summaries'] = {key: summary for key, summary in report.get('pilot_batch_summaries', {}).items()
                                                  if any(key.startswith(p) for p in prefixes)}
                value['context'] = {key: config[key] for key in ('source_language', 'target_language', 'style', 'game_background') if key in config}
                value['coverage'] = report.get('coverage', {})
            return value
        def size(batch):
            return count_tokens(json.dumps(packet(batch), ensure_ascii=False, indent=2) + '\n')
        groups, group = [], []
        for item in items:
            candidate = group + [item]
            if group and ((config.get('review_batch_records') is not None and len(candidate) > config['review_batch_records'])
                          or size(candidate) > config.get('task_input_tokens', 16384)):
                groups.append(group); group = []
            if size([item]) > config.get('task_input_tokens', 16384):
                raise ValueError('Sol task allocation exceeds input budget for single check ' + item['id'])
            group.append(item)
        if group:
            groups.append(group)
        manifest = []
        for index, batch in enumerate(groups, 1):
            path = self.root / f'{prefix}.input_{index:04d}.json'
            value = packet(batch)
            write_json(path, value)
            manifest.append({'file': str(path), 'check_ids': [i['id'] for i in batch],
                             'input_tokens': size(batch), 'over_budget': False})
        manifest_path = self.root / f'{prefix}.inputs.json'
        write_json(manifest_path, manifest)
        return manifest_path

    def sol_watch(self, db):
        from translation_workflow import fingerprint
        return fingerprint([self.meta(db, k) for k in ('revision', 'source_hash', 'glossary', 'draft_generation', 'review_generation', 'quality_policy_key')] + [SOL_SCOPE_POLICY])

    def sol_tables(self, db):
        db.execute('CREATE TABLE IF NOT EXISTS sol_review_rounds(id INTEGER PRIMARY KEY,watch TEXT,report TEXT,decisions TEXT,status TEXT,result TEXT)')

    def open_sol_round(self, db, config):
        from translation_workflow import write_json, encoded
        self.sol_tables(db)
        active = db.execute('SELECT * FROM sol_review_rounds WHERE status="open" ORDER BY id DESC LIMIT 1').fetchone()
        watch = self.sol_watch(db)
        if active and active['watch'] == watch:
            report = json.loads(active['report'])
            self.write_sol_inputs(report, active['id'], config)
            return report, active['id']
        if active:
            # Never discard defects already found in the legacy broad inspection.
            # They need repair, not another expensive Sol reading pass.
            pending = self.meta(db, 'sol_pending_findings', {})
            for entry in json.loads(active['decisions']).values():
                if entry['disposition'] == 'repair':
                    for record_id in entry['record_ids']:
                        finding = {'reason': entry['reason'], 'source_round': active['id'], 'check_id': entry['id']}
                        if finding not in pending.setdefault(record_id, []):
                            pending[record_id].append(finding)
            self.put(db, 'sol_pending_findings', pending)
        report = self.build_quality_report(db, 'final', config)
        if active:
            # Only reuse actual passed decisions whose item signatures still match.
            old_report, old_decisions = json.loads(active['report']), json.loads(active['decisions'])
            checkpoints = self.meta(db, 'quality_checkpoints', {})
            for record_id, entry in old_decisions.items():
                if entry['disposition'] in ('pass', 'contextual') and old_report['check_signatures'].get(record_id) == report['check_signatures'].get(record_id):
                    checkpoints.setdefault('final', {})[record_id] = {'signature': report['check_signatures'][record_id],
                        'report_hash': old_report['report_hash'], 'decision': entry}
            self.put(db, 'quality_checkpoints', checkpoints)
            db.execute('UPDATE sol_review_rounds SET status="superseded" WHERE id=?', (active['id'],))
            report = self.build_quality_report(db, 'final', config)
        if self.meta(db, 'quality_approvals', {}).get('final', {}).get('report_hash') == report['report_hash']:
            return report, None
        cursor = db.execute('INSERT INTO sol_review_rounds(watch,report,decisions,status) VALUES (?,?,?,"open")',
                            (watch, encoded(report), '{}'))
        self.write_sol_inputs(report, cursor.lastrowid, config)
        write_json(self.root / f'reports/sol_rounds/round_{cursor.lastrowid:05d}.report.json', report)
        self.event(db, 'sol_round_open', {'round': cursor.lastrowid, 'report_hash': report['report_hash'], 'scope': report['required_decisions']})
        return report, cursor.lastrowid

    def active_sol_round(self, db):
        self.sol_tables(db)
        row = db.execute('SELECT * FROM sol_review_rounds WHERE status="open" ORDER BY id DESC LIMIT 1').fetchone()
        if not row:
            raise ValueError('Open a final quality-report before recording or finishing a Sol round')
        if row['watch'] != self.sol_watch(db):
            raise ValueError('Stale Sol round; request the current quality-report before continuing')
        self.require_review_round_complete(db, 'final_review' if self.config(db)['polish'] else 'review')
        return row

    def record_sol_checks(self, db, decisions, *, direct=False):
        from translation_workflow import encoded, write_json
        if not isinstance(decisions, dict):
            raise ValueError('Sol decisions must be a JSON object')
        row = self.active_sol_round(db)
        report, saved = json.loads(row['report']), json.loads(row['decisions'])
        entries = decisions.get('decisions')
        if direct:
            if (not isinstance(decisions.get('reviewer'), str) or not decisions['reviewer'].startswith('main:')
                    or not isinstance(decisions.get('user_authorization'), str) or not decisions['user_authorization'].strip()
                    or len(report['required_decisions']) > 16):
                raise ValueError('Direct adjudication requires actual main identity, explicit user authorization and at most 16 checks')
        if (decisions.get('report_hash') != report['report_hash'] or (not direct and decisions.get('reviewer') != 'sol')
                or not isinstance(decisions.get('summary'), str) or not decisions['summary'].strip()
                or not isinstance(entries, list) or not entries or any(not isinstance(e, dict) or not isinstance(e.get('id'), str) for e in entries)
                or len({e.get('id') for e in entries}) != len(entries)):
            raise ValueError('Sol checks require unique explicit decisions bound to the current round report')
        items = {i['id']: i for key in ('records_to_check', 'consistency', 'glossary_checks') for i in report[key]}
        for entry in entries:
            record_id = entry.get('id')
            if (record_id not in report['required_decisions'] or entry.get('disposition') not in ('pass', 'contextual', 'repair')
                    or not isinstance(entry.get('reason'), str) or not entry['reason'].strip()):
                raise ValueError('Every Sol decision requires an assigned ID, disposition and evidence/reason')
            if entry['disposition'] == 'repair':
                item = items[record_id]
                allowed = ({record_id} if 'translation' in item else
                           set(item.get('record_ids', [])) | {r['id'] for r in item.get('records', [])})
                ids = entry.get('record_ids', [record_id] if 'translation' in item else [])
                if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids) or not set(ids).issubset(allowed):
                    raise ValueError('Sol repair must name exact affected record IDs within this check')
                entry = {**entry, 'record_ids': ids}
            saved[record_id] = ({**entry, 'reviewer': decisions['reviewer'],
                                'user_authorization': decisions['user_authorization']} if direct else entry)
        db.execute('UPDATE sol_review_rounds SET decisions=? WHERE id=?', (encoded(saved), row['id']))
        write_json(self.root / f'reports/sol_rounds/round_{row["id"]:05d}.progress.json',
                   {'round': row['id'], 'report_hash': report['report_hash'], 'decisions': saved,
                    'remaining_checks': [i for i in report['required_decisions'] if i not in saved], 'repairs_dispatched': False})
        self.event(db, 'sol_round_checks', {'round': row['id'], 'decisions': entries})
        return {'status': 'checks_saved', 'round': row['id'], 'saved_checks': len(saved),
                'remaining_checks': len(set(report['required_decisions']) - set(saved)), 'repairs_dispatched': False, 'stage_approved': False}

    def record_sol_round(self, decisions):
        with self.db() as db:
            self.config(db)
            return self.record_sol_checks(db, decisions)

    def record_direct_quality_round(self, decisions):
        """User-authorized small adjudication, with the real reviewer recorded."""
        with self.db() as db:
            self.config(db)
            return self.record_sol_checks(db, decisions, direct=True)

    def finish_sol_round(self):
        from translation_workflow import encoded, write_json
        with self.db() as db:
            config = self.config(db); row = self.active_sol_round(db)
            report, decisions = json.loads(row['report']), json.loads(row['decisions'])
            missing = set(report['required_decisions']) - set(decisions)
            if missing:
                raise ValueError(f'Complete the entire Sol inspection round before dispatching repairs: {len(missing)} checks remain')
            print(f'sol-round-finish progress: round={row["id"]}; decisions={len(decisions)}/{len(report["required_decisions"])}; carried_findings={len(report.get("carried_findings", {}))}', flush=True)
            problems = {record_id: [f['reason'] for f in findings]
                        for record_id, findings in report.get('carried_findings', {}).items()}
            for entry in decisions.values():
                if entry['disposition'] == 'repair':
                    for record_id in entry['record_ids']:
                        problems.setdefault(record_id, []).append(entry['reason'])
            if problems:
                checkpoints = self.meta(db, 'quality_checkpoints', {})
                for record_id, entry in decisions.items():
                    if entry['disposition'] in ('pass', 'contextual'):
                        checkpoints.setdefault('final', {})[record_id] = {'signature': report['check_signatures'][record_id],
                            'report_hash': report['report_hash'], 'decision': entry}
                self.put(db, 'quality_checkpoints', checkpoints)
                print(f'sol-round-finish progress: preparing repair dispatch for {len(problems)} records', flush=True)
                tasks, blocked = self.plan_review_repairs(db, config, 'final_review' if config['polish'] else 'review',
                                                       problems, f'sol-round-{row["id"]}')
                # Only relinquish an obligation once a durable repair task owns it.
                dispatched = {i for task_id in tasks for i in json.loads(
                    db.execute('SELECT ids FROM tasks WHERE id=?', (task_id,)).fetchone()[0])}
                self.put(db, 'sol_pending_findings', {i: f for i, f in self.meta(db, 'sol_pending_findings', {}).items()
                                                     if i not in dispatched})
                result = {'status': 'needs_attention' if blocked and not tasks else 'repair_round_prepared', 'round': row['id'], 'repair_tasks': tasks, 'repair_dispatch': self.repair_dispatch(db, tasks),
                          'repair_records': len(problems), 'needs_attention_ids': blocked, 'stage_approved': False}
                result['repair_stop_reasons'] = {i: reason for i, reason in self.repair_stops(db, config).items() if i in blocked}
                print(f'sol-round-finish progress: dispatch prepared; tasks={len(tasks)}; blocked={len(blocked)}', flush=True)
            else:
                reviewers = sorted({entry.get('reviewer', 'sol') for entry in decisions.values()})
                supplied = {'report_hash': report['report_hash'], 'reviewer': ','.join(reviewers) if reviewers else 'workflow:no-disputes', 'summary': 'Completed inspection round; explicit per-item decisions and actual reviewer archived.',
                            'decisions': [decisions[i] for i in report['required_decisions']]}
                result = self.accept_quality_in_transaction(db, 'final', report, supplied)
                result['round'] = row['id']
            db.execute('UPDATE sol_review_rounds SET status="finished",result=? WHERE id=?', (encoded(result), row['id']))
            write_json(self.root / f'reports/sol_rounds/round_{row["id"]:05d}.result.json',
                       {'report_hash': report['report_hash'], 'decisions': decisions, **result})
            self.event(db, 'sol_round_finished', result)
            print(f'sol-round-finish progress: complete; status={result["status"]}', flush=True)
            return result

    def guard_sol_dispatch(self, db):
        self.sol_tables(db)
        if db.execute('SELECT 1 FROM sol_review_rounds WHERE status="open"').fetchone():
            raise ValueError('Finish the entire Sol inspection round before dispatching semantic repairs; use sol-round-record / sol-round-finish')
