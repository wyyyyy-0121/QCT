"""Check the claimed correction against XLSX and author-master ODF roles."""
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'qa')]
from run_selector_dev5 import read, save, sha
from run_hobyah_natural_dev26 import RUN, verify

T = 'urn:oasis:names:tc:opendocument:xmlns:table:1.0'


def ods_selected(path, targets):
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read('content.xml'))
    result = {}
    for table in root.iter('{' + T + '}table'):
        if table.attrib['{' + T + '}name'] != 'quadratics': continue
        r = 1
        for row in table.findall('{' + T + '}table-row'):
            repeat = int(row.attrib.get('{' + T + '}number-rows-repeated', '1'))
            if r > 24: break
            c = 1
            for cell in row:
                width = int(cell.attrib.get('{' + T + '}number-columns-repeated', '1'))
                for target, (wanted_row, wanted_col) in targets.items():
                    if r <= wanted_row < r + repeat and c <= wanted_col < c + width:
                        result[target] = dict(formula=cell.attrib.get('{' + T + '}formula'),
                                              text=' '.join(cell.itertext()).strip())
                c += width
            r += repeat
    assert set(result) == set(targets)
    return result


def normal_ods(formula):
    assert formula.startswith('of:=')
    result = re.sub(r'\[\.([^\]]+)\]', r'\1', formula[3:]).replace(';', ',')
    return re.sub(r'\s+', '', result)


def role_formula(formula, mapping):
    return re.sub(r'\$?[A-Z]+\$?[0-9]+', lambda m: mapping[m.group().replace('$', '')],
                  re.sub(r'\s+', '', formula))


def main():
    verify(); assert (RUN / 'replay.json').exists()
    diff = read(RUN / 'author_diff.json.gz'); acquisition = read(RUN / 'odf_acquisition.json')
    assert acquisition['source_sha256'] == sha(ROOT / 'qa/acquire_hobyah_odf_dev26.py')
    for row in acquisition['records']:
        assert row['ok'] and sha(ROOT / row['path']) == row['sha256']
    before_targets = {'LCV_term': (13, 12), 'HGV_term': (14, 12),
                      'car_area_label': (18, 7), 'LCV_area_label': (20, 7), 'HGV_area_label': (22, 7)}
    after_targets = {'LCV_term': (13, 10), 'HGV_term': (14, 10),
                     'car_area_label': (18, 5), 'LCV_area_label': (20, 5), 'HGV_area_label': (22, 5)}
    before = ods_selected(RUN / 'raw/before.ods', before_targets)
    after = ods_selected(RUN / 'raw/after.ods', after_targets)
    results = []
    roles_before = dict(H18='car_area', H19='car_drag', H20='LCV_area', H21='LCV_drag',
                        H22='HGV_area', H23='HGV_drag', L10='LCV_density', L11='HGV_density',
                        C14='tunnel_length', C15='tunnel_area', H24='use_blockage')
    roles_after = dict(F18='car_area', F19='car_drag', F20='LCV_area', F21='LCV_drag',
                       F22='HGV_area', F23='HGV_drag', J10='LCV_density', J11='HGV_density',
                       B14='tunnel_length', B15='tunnel_area', F24='use_blockage')
    for role, original, corrected in [('LCV_term', 'L13', 'J13'), ('HGV_term', 'L14', 'J14')]:
        old = diff['before']['formulas']['quadratics!' + original]
        new = diff['after']['formulas']['quadratics!' + corrected]
        assert normal_ods(before[role]['formula']) == re.sub(r'\s+', '', old)
        assert normal_ods(after[role]['formula']) == re.sub(r'\s+', '', new)
        left, right = role_formula(old, roles_before), role_formula(new, roles_after)
        assert left == right
        assert 'car_area' not in left and role.split('_')[0] + '_area' in left
        results.append(dict(role=role, original_cell='quadratics!' + original,
                            corrected_cell='quadratics!' + corrected, original_formula=old,
                            corrected_formula=new, role_formula=left,
                            equivalent_after_verified_role_alignment=True,
                            claimed_car_area_misuse_absent_in_both_pinned_versions=True))
    for role in ['car_area_label', 'LCV_area_label', 'HGV_area_label']:
        assert before[role]['text'] == after[role]['text']
    original_notices = diff['before']['notices']
    assert not any('j13' in n['text'].lower() or 'j14' in n['text'].lower() for n in original_notices)
    target = RUN / 'role_alignment_audit.json'; assert not target.exists()
    result = dict(checked_roles=results, ods_before=before, ods_after=after,
                  formula_inventory_independently_checked_with_ooxml=True,
                  current_correction_formula_truth_supported=False,
                  verified_error_labels=0, precision=None, coverage=None,
                  reason='Pinned parent and correction both already use the appropriate vehicle area for these two terms; no reliable natural-error truth pair established',
                  original_contains_historical_version_notes=True,
                  current_claimed_correction_locations_found_in_original_notices=False,
                  metadata_claim_does_not_override_original_formulas=True,
                  original_prediction_lock_sha256=sha(RUN / 'prediction_lock.json'),
                  author_diff_sha256=sha(RUN / 'author_diff.json.gz'),
                  odf_acquisition_sha256=sha(RUN / 'odf_acquisition.json'),
                  auditor_sha256=sha(Path(__file__)), final_validation_eligible=False)
    save(target, result)
    print('DEV26 claimed correction not established in pinned original; both aligned terms already match', flush=True)


if __name__ == '__main__': main()
