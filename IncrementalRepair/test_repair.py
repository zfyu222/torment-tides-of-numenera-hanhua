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
    def test_literal_guard_keeps_original_boundary_and_non_ascii_behavior(self):
        import scope_match
        import re
        guarded = scope_match.LiteralGuard(re.compile(r'\buser\b', re.I), 'user')
        for text in ('the USER waits', 'superuser', 'no matching noun', 'the üser waits', 'ſuser'):
            self.assertEqual([m.span() for m in guarded.finditer(text)],
                             [m.span() for m in guarded.wrapped.finditer(text)])

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

    def test_null_optional_scope_has_same_default_meaning_as_absence(self):
        row = copy.deepcopy(self.old['terms'][0])
        expected = repair.effective_term(row, 'terms', self.config)
        row['applicability'] = None
        self.assertEqual(repair.effective_term(row, 'terms', self.config), expected)

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

    def test_removed_term_with_existing_exception_does_not_retranslate_correct_row(self):
        before = [{'src': 'like', 'dst': '喜欢'}, {'src': 'Sagus', 'dst': '萨古斯'}]
        after = [{'src': 'Sagus', 'dst': '萨古斯'}]
        exception = [{'source': 'like', 'reason': 'Source uses feels like for a comparison, already reviewed.'}]
        self.assertFalse(repair.policy_change_affects_record(before, after, exception))
        self.assertTrue(repair.policy_change_affects_record(before, after, []))
        self.assertTrue(repair.policy_change_affects_record(before, [{'src': 'Sagus', 'dst': '另一个译名'}], exception))
        self.assertTrue(repair.policy_change_affects_record(before,
            after + [{'src': 'like', 'dst': '像', 'enforcement': 'reference'}], exception))


class EvidenceTests(unittest.TestCase):
    def test_actual_null_policy_replies_restore_only_equivalent_layout(self):
        fixture=repair.w.read_json(Path(__file__).parent/'test_fixtures/real_body_layout.json')
        r=object.__new__(repair.Repair);r.snapshot=lambda:{'config':copy.deepcopy(repair.w.DEFAULT)}
        glossary={'characters':[],'terms':[],'non_translate':[]}
        for example in fixture:
            before=example['item']['translation']; item=copy.deepcopy(example['item'])
            payload={'stage':'translate','layout_policy':None,'records':[example['original']]}
            r.validate_result(payload,{'records':[item]},glossary)
            self.assertEqual(item['translation'].strip().replace('\r\n','\n'),before.strip().replace('\r\n','\n'))
            self.assertFalse(item['_layout_audit']['semantic_checks_created'])
            self.assertEqual(__import__('re').findall(r'\r\n|\r|\n',item['translation']),
                             __import__('re').findall(r'\r\n|\r|\n',example['original']['source']))
            with self.assertRaisesRegex(ValueError,'structural'):
                r.validate_result({**payload,'layout_policy':'off'},
                    {'records':[copy.deepcopy(example['item'])]},glossary)

    def test_layout_recovery_rejects_actual_removed_paragraph(self):
        example=repair.w.read_json(Path(__file__).parent/'test_fixtures/real_body_layout.json')[0]
        r=object.__new__(repair.Repair);r.snapshot=lambda:{'config':copy.deepcopy(repair.w.DEFAULT)}
        item=copy.deepcopy(example['item'])
        item['translation']=item['translation'].replace('\r\n\r\n','\r\n',1).replace('\n\n','\n',1)
        with self.assertRaisesRegex(ValueError,'physical_newlines'):
            r.validate_result({'stage':'translate','layout_policy':None,'records':[example['original']]},
                {'records':[item]},{'characters':[],'terms':[],'non_translate':[]})

    def test_legacy_missing_config_uses_shared_default_but_explicit_off_is_respected(self):
        example=repair.w.read_json(Path(__file__).parent/'test_fixtures/real_body_layout.json')[0]
        config=copy.deepcopy(repair.w.DEFAULT);config.pop('layout_normalization',None)
        r=object.__new__(repair.Repair);r.snapshot=lambda:{'config':config}
        payload={'stage':'translate','layout_policy':'off','records':[example['original']]}
        result={'records':[copy.deepcopy(example['item'])]}
        glossary={'characters':[],'terms':[],'non_translate':[]}
        r.validate_result(payload,result,glossary)
        self.assertEqual(result['records'][0]['_layout_audit']['effective_policy'],'exact_v1')
        config['layout_normalization']='off'
        with self.assertRaisesRegex(ValueError,'structural'):
            r.validate_result(payload,{'records':[copy.deepcopy(example['item'])]},glossary)

    def test_explicit_finding_notes_normalize_but_unknown_refs_are_rejected(self):
        import term_parts
        binding = {'glossary': {'finding_refs': {'f1': 'F0012', 'f2': 'F0013'}}}
        d = {'acknowledged_findings': [{'id': 'f1', 'reason': 'Actual alias comparison'}, 'f2：实际核对来源', 'f1']}
        self.assertEqual(term_parts.normalize_acknowledgments(d, binding)['acknowledged_findings'], ['f1', 'f2'])
        with self.assertRaisesRegex(ValueError, 'Unknown explicit'):
            term_parts.normalize_acknowledgments({'acknowledged_findings': ['f999']}, binding)

    def test_stray_empty_check_does_not_hide_missing_semantic_dimension(self):
        import term_parts
        fixture = repair.w.read_json(Path(__file__).parent / 'test_fixtures/real_term_parts.json')
        bad = copy.deepcopy(fixture['reply'])
        bad['decisions']['entry_reviews'][0]['checks']['.'] = []
        bad['decisions']['entry_reviews'][0]['checks'].pop('source')
        r = object.__new__(repair.Repair)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); raw = folder/'raw.txt'; raw.write_text(__import__('json').dumps(bad), encoding='utf8')
            with self.assertRaises(ValueError):
                term_parts.save(r, folder, fixture['payload'], fixture['payload'], bad, fixture['binding'], 'api:bad', raw)
            self.assertEqual(len(term_parts.rows(folder, fixture['payload'])), 1)
            self.assertFalse((folder/'accepted.json').exists())

    def test_actual_term_reply_reuses_valid_entries_without_defaulting_policy(self):
        import term_parts
        fixture = repair.w.read_json(Path(__file__).parent / 'test_fixtures/real_term_parts.json')
        payload = fixture['payload']; binding = fixture['binding']; reply = fixture['reply']
        base = copy.deepcopy(payload)
        cited = set(reply['decisions']['entry_reviews'][0]['evidence_rows'])
        base['records'] = [row for row in base['records'] if row['ordinal'] not in cited]
        bad = copy.deepcopy(reply)
        bad['decisions']['edits'][1]['patch'].pop('term_reason', None)
        r = object.__new__(repair.Repair)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); raw = folder / 'raw.txt'
            raw.write_text(__import__('json').dumps(bad), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'Only missing/invalid term'):
                term_parts.save(r, folder, base, payload, bad, binding, 'api:first', raw)
            parts = term_parts.rows(folder, base)
            self.assertEqual(len(parts), 1)
            self.assertFalse((folder / 'accepted.json').exists())
            missing = next(e for e in payload['entries'] if e['ref'] not in parts)
            short = next(k for k,v in binding['glossary']['entry_refs'].items() if v == missing['ref'])
            request = {**payload, 'entries': [missing]}
            second = copy.deepcopy(reply)
            second['decisions']['entry_reviews'] = [x for x in second['decisions']['entry_reviews'] if x['ref'] == short]
            second['decisions']['edits'] = [x for x in second['decisions']['edits'] if x['ref'] == short]
            second_binding = copy.deepcopy(binding); second_binding['glossary']['assigned_refs'] = [missing['ref']]
            raw.write_text(__import__('json').dumps(second), encoding='utf8')
            term_parts.save(r, folder, base, request, second, second_binding, 'api:second', raw)
            saved = repair.w.read_json(folder / 'accepted.json')
            self.assertEqual(set(saved['entry_instances'].values()), {'api:first', 'api:second'})
            self.assertEqual(len(saved['result']['decisions']['entry_reviews']), 2)
            with self.assertRaises(ValueError):
                r.validate_result(base, saved['result'], None)
            r.validate_result(term_parts.validation_payload(r, folder, base), saved['result'], None)

    def test_actual_review_omission_inherits_existing_exception_without_api_retry(self):
        fixture = repair.w.read_json(Path(__file__).parent / 'test_fixtures/inherited_like_exception.json')
        b = fixture['binding']; payload = fixture['payload']
        result = repair.canonical_api_result(fixture['reply'], b, b['session_id'], b['task_id'], b['input_hash'], list(b['short_to_canonical'].values()))
        r = object.__new__(repair.Repair); r.snapshot = lambda: {'config': copy.deepcopy(repair.w.DEFAULT)}
        glossary = {'characters': [], 'terms': [{'source': 'like', 'recommended_translation': '喜欢', 'category_path': '其他'}], 'non_translate': []}
        r.validate_result(payload, result, glossary)
        self.assertEqual(result['records'][0]['exceptions'], payload['records'][0]['exceptions'])
        self.assertNotIn('喜欢', result['records'][0]['translation'])

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

    def test_same_size_formal_edit_invalidates_verified_hash_cache(self):
        self.r.prepare(); self.r.snapshot()
        data=self.target.read_bytes(); stat=self.target.stat()
        self.target.write_bytes((b'X' if data[:1]!=b'X' else b'Y')+data[1:])
        repair.os.utime(self.target, ns=(stat.st_atime_ns,stat.st_mtime_ns+1000000000))
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
