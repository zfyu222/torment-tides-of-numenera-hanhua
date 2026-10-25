"""Source/result provenance and SQLite backup safeguards; no API calls."""
import copy
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

import integrate


class IntegrationTests(unittest.TestCase):
    def fixture(self, root):
        w = integrate.repair.w
        folder = root / 'jobs/review/test'
        folder.mkdir(parents=True)
        payload = {'task_id': 'test', 'revision': 8, 'stage': 'review',
                   'records': [{'id': 'r1', 'source': 'A name', 'translation': '名称'}]}
        payload['input_hash'] = w.fingerprint(payload)
        raw = folder / 'call1/response.raw.txt'; raw.parent.mkdir(); raw.write_text('actual response', encoding='utf8')
        saved = {'input_hash': payload['input_hash'], 'result': {'records': [
            {'id': 'r1', 'translation': '名称', 'reviewed': True, 'issues': []}]},
            'record_instances': {'r1': 'api:call1'},
            'record_response_sha256': {'r1': integrate.repair.sha(raw)}}
        w.write_json(root / 'review_jobs.json', ['jobs/review/test'])
        w.write_json(folder / 'payload.json', payload); w.write_json(folder / 'accepted.json', saved)
        return SimpleNamespace(work=root), folder, saved

    def test_raw_response_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            r, folder, _ = self.fixture(Path(d))
            self.assertEqual(len(integrate.jobs(r, 'review')), 1)
            (folder / 'call1/response.raw.txt').write_text('modified', encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'response digest'):
                integrate.jobs(r, 'review')

    def test_missing_extra_and_duplicate_coverage_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            r, folder, saved = self.fixture(Path(d))
            for rows in ([], [*saved['result']['records'], *saved['result']['records']],
                         [{'id': 'other', 'translation': '别的'}]):
                bad = copy.deepcopy(saved); bad['result']['records'] = rows
                integrate.repair.w.write_json(folder / 'accepted.json', bad)
                with self.assertRaisesRegex(ValueError, 'coverage'):
                    integrate.jobs(r, 'review')

    def test_unresolved_issue_cannot_be_imported_as_passed(self):
        with tempfile.TemporaryDirectory() as d:
            r, folder, saved = self.fixture(Path(d))
            saved['result']['records'][0]['issues'] = [{'reason': 'Unresolved meaning'}]
            integrate.repair.w.write_json(folder / 'accepted.json', saved)
            with self.assertRaisesRegex(ValueError, 'Unresolved'):
                integrate.jobs(r, 'review')

    def test_backup_includes_committed_wal_without_changing_source(self):
        with tempfile.TemporaryDirectory() as d:
            source, target = Path(d) / 'source.db', Path(d) / 'copy.db'
            with closing(sqlite3.connect(source)) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE history(value TEXT)'); db.execute('INSERT INTO history VALUES (?)', ('保留历史',)); db.commit()
                integrate.backup_db(source, target)
                with closing(sqlite3.connect(target)) as clone:
                    self.assertEqual(clone.execute('SELECT * FROM history').fetchall(), [('保留历史',)])
                    clone.execute('DELETE FROM history'); clone.commit()
                self.assertEqual(db.execute('SELECT count(*) FROM history').fetchone()[0], 1)

    def test_append_preserves_history_but_rewriting_old_row_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            source, staged = Path(d) / 'source.db', Path(d) / 'staged.db'
            with closing(sqlite3.connect(source)) as db:
                for table in ('api_calls', 'quality_attempts', 'quality_authors', 'tasks'):
                    db.execute('CREATE TABLE ' + table + '(value TEXT)')
                    db.execute('INSERT INTO ' + table + ' VALUES ("original")')
                db.commit()
            integrate.backup_db(source, staged)
            with closing(sqlite3.connect(staged)) as db:
                db.execute('INSERT INTO tasks VALUES ("new API result")'); db.commit()
            integrate.verify_history_preserved(source, staged)
            with closing(sqlite3.connect(staged)) as db:
                db.execute('UPDATE api_calls SET value="rewritten"'); db.commit()
            with self.assertRaisesRegex(ValueError, 'history changed'):
                integrate.verify_history_preserved(source, staged)


if __name__ == '__main__':
    unittest.main()
