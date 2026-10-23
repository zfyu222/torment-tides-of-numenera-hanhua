import json
import sqlite3
import unittest
from workflow_quality import QualityMixin


class GlossaryIndependenceScope(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE records(id TEXT PRIMARY KEY,ordinal INTEGER UNIQUE); CREATE TABLE quality_authors(instance TEXT,record_id TEXT,stage TEXT);')
        self.db.executemany('INSERT INTO records VALUES (?,?)',[(f'r{i}',i) for i in range(1,1701)])
        self.flow=QualityMixin()

    def check(self,ordinals,instance='reviewer'):
        task={'stage':'glossary_review','ids':'[]','payload':json.dumps({'entries':[{'row':{'evidence_rows':ordinals}}]})}
        return self.flow.independent_worker(self.db,task,instance)

    def test_only_authorship_in_cited_scope_blocks(self):
        self.db.execute('INSERT INTO quality_authors VALUES (?,?,?)',('reviewer','r5','extract'))
        self.assertFalse(self.check([5]))
        self.assertTrue(self.check([6]))
        self.assertTrue(self.check([5],'another'))

    def test_unrelated_stage_and_missing_ordinals_do_not_block(self):
        self.db.execute('INSERT INTO quality_authors VALUES (?,?,?)',('reviewer','r5','translate'))
        self.assertTrue(self.check([5,9999]))
        self.assertTrue(self.check([]))

    def test_large_scope_checks_late_chunk_without_full_scan(self):
        self.db.execute('INSERT INTO quality_authors VALUES (?,?,?)',('reviewer','r1699','extract'))
        queries=[];self.db.set_trace_callback(queries.append)
        self.assertFalse(self.check(list(range(1,1701))))
        self.assertEqual(sum('SELECT id FROM records WHERE ordinal IN' in q for q in queries),3)
        self.assertFalse(any('SELECT id,ordinal FROM records' in q for q in queries))


if __name__=='__main__':unittest.main()
