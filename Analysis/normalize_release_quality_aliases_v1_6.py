"""Rebind an unchanged accepted report after shared Sol/standard field renaming."""
import copy
import json
from prepare_release_v1_5 import P, Workflow, sha, write


def main():
    flow = Workflow(P)
    old = json.loads((flow.root/'reports/final_quality_review.json').read_text(encoding='utf-8'))
    with flow.db() as db:
        current = flow.build_quality_report(db,'final',flow.config(db))
        if old['report_hash'] == current['report_hash']:
            print('No alias normalization needed'); return
        left, right = copy.deepcopy(old), copy.deepcopy(current)
        assert left['coverage'].pop('sol_records') == right['coverage'].pop('standard_records')
        assert left.pop('sol_scope_policy') == right.pop('standard_scope_policy') == 'disputes_only_v1'
        assert left.pop('round_scope') == []
        before = left.pop('selection_explanation'); after = right.pop('selection_explanation')
        assert before.startswith('Only explicit unresolved reviewer issues need Sol adjudication.')
        assert after.startswith('Only explicit unresolved reviewer issues need standard-tier adjudication.')
        left.pop('report_hash'); right.pop('report_hash')
        assert left == right, 'Changes extend beyond shared report naming; semantic closure cannot be carried'
        approvals = flow.meta(db,'quality_approvals')
        assert approvals['final']['report_hash'] == old['report_hash']
        assert not current['required_decisions'] and not current.get('carried_findings')
        previous = copy.deepcopy(approvals['final'])
        decisions = copy.deepcopy(previous['decisions']); decisions['report_hash'] = current['report_hash']
        flow.accept_quality_in_transaction(db,'final',current,decisions)
        export = flow.meta(db,'last_export')
        assert sha(P/'torment-tides-of-numenera_text_translated.csv') == export['translation_sha256']
        export['quality_review']['report_hash'] = current['report_hash']
        flow.put(db,'last_export',export)
        flow.event(db,'quality_report_alias_normalization',dict(old=old['report_hash'],new=current['report_hash'],semantic_evidence_unchanged=True))
        write(flow.root/'reports/final_quality_review.json',current)
        write(flow.root/'reports/final_validation.json',export)
        write(flow.root/'reports/quality_alias_normalization_v1.6.json',dict(
            previous_approval=previous,previous_report=old,current_report_hash=current['report_hash'],
            changed_fields=['coverage.sol_records -> coverage.standard_records','sol_scope_policy -> standard_scope_policy','empty legacy round_scope','selection_explanation labels'],
            snapshot_review_evidence_and_decisions_unchanged=True,api_requests=0))
    print('Accepted evidence unchanged; shared report aliases rebound')


if __name__ == '__main__': main()
