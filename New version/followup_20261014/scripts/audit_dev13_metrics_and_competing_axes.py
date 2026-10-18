"""Independent scoring counts and orthogonal evidence for revealed dev13."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_bidirectional_dev13 import RUN, read, sha, verify, load_case
from run_selector_dev8 import truth_and_observed
from openpyxl.formula.translate import Translator, TranslatorError
from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter


def counts(rows, observed, truth, extra):
    # Construct proposals directly; deliberately do not call metrics() or merge().
    expected = truth['expected_formulas']
    assert set(expected) == set(observed)
    error_labels = {label for label in observed if observed[label] != expected[label]}
    assert error_labels == set(truth['errors'])
    proposals = {}
    for row in rows:
        label = row['cell']
        formula = row.get('suggested_formula')
        if row.get('status') == 'propose':
            if formula and formula != observed[label]:
                proposals[label] = formula
        elif label in extra and extra[label]['formula'] != observed[label]:
            proposals[label] = extra[label]['formula']
    correct = sum(label in error_labels and formula == expected[label]
                  for label,formula in proposals.items())
    return {'proposals':len(proposals),'correct':correct,'wrong':len(proposals)-correct,
            'errors':len(error_labels),
            'harmful_correct_cells':sum(label not in error_labels for label in proposals)}


def main():
    verify()
    report = read(RUN/'score.json')
    scored = {(g,c['id']):c for g,d in report['groups'].items() for c in d['cases']}
    controlled = {c['id']:c for c in read(ROOT/'development/reconciliation_dev12_inputs_v1/truth.json')['cases']}
    checked = 0
    for item in read(RUN/'public_index.json'):
        if item['group'] == 'public':
            continue
        observed,prior = load_case(item)
        truth = controlled[item['id']] if item['group']=='controlled_reconciliation' else truth_and_observed(item)[0]
        prediction = read(RUN/'predictions'/item['group']/(item['id']+'.json.gz'))
        for variant in ['dev11','both','row_only','column_only']:
            extra = {} if variant=='dev11' else prediction['variants'][variant]
            actual = counts(prior['rows'],observed,truth,extra)
            published = scored[(item['group'],item['id'])][variant]
            assert all(actual[key] == published[key] for key in actual), (item['id'],variant,actual,published)
            checked += 1
    audit = read(ROOT/'qa/BIDIRECTIONAL_DEV13_INDEPENDENT_AUDIT_20261018.json')
    index = {i['id']:i for i in read(RUN/'public_index.json') if i['group']=='public'}
    observations = {name:load_case(item)[0] for name,item in index.items()
                    if name in {r['id'] for r in audit['public_candidate_details']}}
    competing = []
    for row in audit['public_candidate_details']:
        observed = observations[row['id']]
        sheet,address = row['cell'].rsplit('!',1)
        r,c = coordinate_to_tuple(address)
        vertical = row['variant']=='row_only'
        votes = []
        for distance in [-2,-1,1,2]:
            nr,nc = (r+distance,c) if vertical else (r,c+distance)
            if min(nr,nc)<1:
                continue
            peer = f'{get_column_letter(nc)}{nr}'
            text = observed.get(sheet+'!'+peer)
            if text is None:
                continue
            try:
                translated = Translator(text,origin=peer).translate_formula(address)
            except (ValueError,TranslatorError):
                continue
            votes.append({'peer':sheet+'!'+peer,'translated_formula':translated,
                          'supports_observed_exactly':translated==row['original_formula'],
                          'supports_candidate_exactly':translated==row['candidate_formula']})
        competing.append({'id':row['id'],'cell':row['cell'],'variant':row['variant'],
                          'orthogonal_votes':votes,
                          'orthogonal_support_for_observed':sum(v['supports_observed_exactly'] for v in votes),
                          'business_truth_proven':False})
    target = ROOT/'qa/DEV13_METRIC_AND_AXIS_AUDIT_20261018.json'
    assert not target.exists()
    result = {'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),
              'audit_script_sha256':sha(Path(__file__)),
              'independent_case_variant_count_checks':checked,
              'all_scoring_counts_agree':True,
              'public_single_axis_candidates':len(competing),
              'candidates_with_two_or_more_orthogonal_supporters_for_observed':sum(
                  x['orthogonal_support_for_observed']>=2 for x in competing),
              'orthogonal_diagnostics':competing,
              'scope':'competing spatial evidence, not natural business-error labels',
              'final_validation_eligible':False}
    target.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='orthogonal_diagnostics'}))


if __name__ == '__main__':
    main()
