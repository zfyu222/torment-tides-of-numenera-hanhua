"""Incremental scope and real response gates; no production writes or API calls."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
import csv
import tempfile
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('incremental_repair', Path(__file__).with_name('repair.py'))
repair = importlib.util.module_from_spec(spec); spec.loader.exec_module(repair)


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(repair.w.DEFAULT)
        self.old = {'characters': [{'source': 'Matkina', 'recommended_translation': '玛特金娜', 'gender': '女性'}],
                    'terms': [{'source': 'user', 'recommended_translation': '用户', 'category_path': '其他'},
                              {'source': 'Hardened', 'recommended_translation': '硬化', 'category_path': '其他'}],
                    'non_translate': [{'source': '[DEBUG]'}]}

    def test_adding_classification_and_default_scope_does_not_reopen_all_names(self):
        new = copy.deepcopy(self.old)
        for row in new['characters'] + new['terms']:
            row.update(term_kind='proper_name', enforcement='required', term_reason='Source-based review.',
                       applicability={'mode': 'text', 'case_sensitive': False, 'reason': 'Same scope'})
        changes, annotations = repair.term_changes(self.old, new, self.config)
        self.assertEqual(changes, []); self.assertEqual(len(annotations), 3)

    def test_removal_level_translation_and_scope_changes_are_effective(self):
        for change in ('remove', 'reference', 'translation', 'scope'):
            new = copy.deepcopy(self.old)
            if change == 'remove':
                new['terms'].pop(0)
            elif change == 'reference':
                new['terms'][0]['enforcement'] = 'reference'
            elif change == 'translation':
                new['terms'][0]['recommended_translation'] = '使用者'
            else:
                new['terms'][0]['applicability'] = {'mode': 'whole_record'}
            with self.subTest(change=change):
                changes, _ = repair.term_changes(self.old, new, self.config)
                self.assertEqual([c['source'] for c in changes], ['user'])

    def test_actual_hidden_marker_and_original_wrappers(self):
        examples = [('Child {Female}', '孩童（{Female}）', '孩童{Female}'),
                    ('Child {Female}', '孩童 ({Female})', '孩童 {Female}'),
                    ('Child ({Female})', '孩童（{Female}）', '孩童（{Female}）'),
                    ('Price {0}', '价格（{0}）', '价格（{0}）')]
        for source, before, expected in examples:
            with self.subTest(source=source):
                self.assertEqual(repair.repair_hidden_wrappers(source, before), expected)
        self.assertTrue(repair.hidden_marker_wrapper_issues('Child {Female}', '孩童（{Female}）'))

    def test_matching_does_not_use_substrings_or_only_changed_probe_overlap(self):
        rules = repair.bridge.patterns()
        g = copy.deepcopy(self.old)
        self.assertEqual(repair.bridge.matched_terms(g, ['A superuser waits.'], self.config, rules=rules), [])
        a = repair.bridge.matched_terms(g, ['The user waits.'], self.config, rules=rules)
        new = copy.deepcopy(g); new['terms'].pop(0)
        b = repair.bridge.matched_terms(new, ['The user waits.'], self.config, rules=rules)
        self.assertNotEqual(repair.matched_meaning(a), repair.matched_meaning(b))

    def test_notes_and_ref_renumbering_cannot_change_match_signature(self):
        old = [{'src': 'Matkina', 'dst': '玛特金娜', 'ref': 'characters:3', 'term_reason': 'old'}]
        new = [{'src': 'Matkina', 'dst': '玛特金娜', 'ref': 'characters:2', 'term_reason': 'new', 'enforcement': 'required'}]
        self.assertEqual(repair.matched_meaning(old), repair.matched_meaning(new))

    def test_current_term_view_keeps_accepted_meaning_and_original_history(self):
        old = copy.deepcopy(self.old)
        old['characters'][0].update(note='Current accepted character context',
            extraction_candidates=[{'row': {'recommended_translation': 'Old resolved proposal'}}])
        view = repair.Repair.audit_snapshot(old)
        self.assertIn('extraction_candidates', old['characters'][0])
        self.assertNotIn('extraction_candidates', view['characters'][0])
        self.assertEqual(view['characters'][0]['recommended_translation'], '玛特金娜')
        self.assertEqual(view['characters'][0]['note'], 'Current accepted character context')
        self.assertEqual(view['non_translate'], [])
        self.assertEqual(old['non_translate'], self.old['non_translate'])


class EvidenceTests(unittest.TestCase):
    def test_real_api_full_correction_passes_and_missing_translation_still_rejects(self):
        fixture = repair.w.read_json(repair.REPO / 'Tools/localization/test_fixtures/source_reference_missing_translation.json')
        complete = fixture['repair']; b = complete['binding']; ids = list(b['short_to_canonical'].values())
        result = repair.canonical_api_result(complete['reply'], b, b['session_id'], b['task_id'], b['input_hash'], ids)
        r = object.__new__(repair.Repair)
        r.snapshot = lambda: {'config': copy.deepcopy(repair.w.DEFAULT)}
        payload = {'stage': 'review', 'layout_policy': 'exact_v1', 'records': [
            {'id': rid, 'source': b['original_sources'][rid], 'translation': b['original_translations'][rid], 'protection': []} for rid in ids]}
        r.validate_result(payload, result, {t: [] for t in repair.TABLES})
        self.assertIn('短发茬', result['records'][0]['translation'])
        missing = fixture['missing']; b = missing['binding']
        with self.assertRaises(ValueError):
            repair.canonical_api_result(missing['reply'], b, b['session_id'], b['task_id'], b['input_hash'], list(b['short_to_canonical'].values()))

    def test_actual_partial_reply_preserves_controls_and_repairs_only_missing_records(self):
        fixture = repair.w.read_json(repair.REPO / 'Tools/localization/test_fixtures/source_reference_missing_translation.json')
        b = fixture['missing']['binding']; ids = list(b['short_to_canonical'].values())
        payload = {'task_id': b['task_id'], 'input_hash': b['input_hash'], 'stage': 'review', 'layout_policy': 'exact_v1',
            'records': [{'id': rid, 'source': b['original_sources'][rid], 'translation': b['original_translations'][rid], 'protection': []} for rid in ids]}
        decoded = repair.canonical_api_partial_result(fixture['missing']['reply'], b, b['session_id'], b['task_id'], b['input_hash'], ids)
        r = object.__new__(repair.Repair); r.snapshot = lambda: {'config': copy.deepcopy(repair.w.DEFAULT)}
        glossary = {t: [] for t in repair.TABLES}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'Only failed'):
                r.save_body_parts(folder, payload, payload, decoded, glossary, 'first-call', 'raw1')
            saved = r.partial_body_rows(folder, payload)
            self.assertEqual(set(saved), {b['short_to_canonical'][k] for k in ('3', '4', '5')})
            corrected = fixture['repair']; rb = corrected['binding']; rid = rb['short_to_canonical']['1']
            decoded = repair.canonical_api_result(corrected['reply'], rb, rb['session_id'], rb['task_id'], rb['input_hash'], [rid])
            subset = {**payload, 'records': [row for row in payload['records'] if row['id'] == rid]}
            with self.assertRaisesRegex(ValueError, 'Only failed'):
                r.save_body_parts(folder, payload, subset, decoded, glossary, 'second-call', 'raw2')
            after = r.partial_body_rows(folder, payload)
            self.assertEqual(len(after), 4)
            self.assertEqual(after[rid]['instance'], 'second-call')
            self.assertTrue(all(after[i] == v for i, v in saved.items()))
            self.assertFalse((folder / 'accepted.json').exists())


class StateTests(unittest.TestCase):
    def setUp(self):
        import test_translation_workflow as fixtures
        self.fixture = fixtures.WorkflowTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.freeze(analysis=True, pilot=True); self.fixture.translate(); self.fixture.review()
        self.flow = self.fixture.flow
        self.target = self.flow.project / (self.flow.project.name + '_text_translated.csv')
        with self.flow.db() as db:
            targets = [r[0] for r in db.execute('SELECT translation FROM records ORDER BY ordinal')]
        with self.target.open('w', encoding='utf-8', newline='') as f:
            csv.writer(f).writerows([[t] for t in targets])
        self.r = repair.Repair(self.flow.project / 'TranslateFiles/incremental_test', self.flow.project)

    def test_prepare_is_read_only_and_note_only_plan_has_empty_body_scope(self):
        before = self.target.read_bytes(); first = self.r.prepare()
        self.assertEqual(first, self.r.prepare()); self.assertEqual(before, self.target.read_bytes())
        new = repair.w.read_json(self.r.work / 'old_glossary.json')
        for table in ('characters', 'terms'):
            for row in new[table]:
                row.update(term_kind='proper_name', enforcement='required', term_reason='New annotation only')
        repair.w.write_json(self.r.work / 'new_glossary.json', new)
        plan = self.r.plan()
        self.assertEqual(plan['total_scope'], 0); self.assertEqual(plan['preserved_records'], 4)

    def test_stale_formal_csv_blocks_repair(self):
        self.r.prepare()
        with self.target.open('a', encoding='utf-8') as f:
            f.write('changed\n')
        with self.assertRaisesRegex(ValueError, 'Formal translation changed'):
            self.r.snapshot()

    def test_service_failure_stops_and_is_not_a_model_budget_charge(self):
        self.r.prepare(); self.r.prepare_terms()
        settings = {**repair.w.DEFAULT['api'], 'think_switch': True, 'concurrency': 25}
        calls = []
        class FailedAPI:
            def __init__(self, *args): pass
            def close(self): pass
            def request(self, *args):
                calls.append(1)
                raise repair.bridge.ApiFailure('InternalServerError:503', False, usage={'usage_reported': False})
        with (patch.object(repair.w, 'load_api_settings', return_value=(settings, 'fixture-only')),
             patch.object(repair.w, 'local_api_name', return_value='fixture'),
             patch.object(repair.bridge, 'AINieeAPI', FailedAPI)):
            result = self.r.run_jobs('glossary_review')
        self.assertEqual(len(calls), 1, result); self.assertTrue(result['remaining'])
        ledger = repair.w.read_json(self.r.work / 'calls.json')
        self.assertTrue(all(repair.service_failure(c['status']) for c in ledger))

    def test_recovery_keeps_unknown_attempts_in_ledger(self):
        self.r.prepare()
        repair.w.write_json(self.r.work / 'calls.json', [{'id': 'x', 'job': 'j', 'stage': 'review', 'status': 'reserved'}])
        self.r.recover_stopped()
        ledger = repair.w.read_json(self.r.work / 'calls.json')
        self.assertEqual(ledger[0]['status'], 'interrupted')
        self.assertFalse(repair.service_failure(ledger[0]['status']))
        self.assertFalse(ledger[0]['usage']['usage_reported'])


if __name__ == '__main__':
    unittest.main()
