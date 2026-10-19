#!/usr/bin/env python3
"""Observe actual paper candidate calls without changing their return values."""
import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
import gzip
import importlib.util
import json
import os
from pathlib import Path
import posixpath
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT.parent / 'followup_20261014'
sys.path.insert(0, str(LEGACY / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
MAIN = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def xml_inventory(source):
    cells = {}
    with zipfile.ZipFile(source) as archive:
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        rels = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        targets = {r.attrib['Id']: r.attrib['Target'] for r in rels}
        for sheet in workbook.find(MAIN + 'sheets'):
            target = targets[sheet.attrib[REL + 'id']]
            path = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl', target))
            root = ET.fromstring(archive.read(path))
            for cell in root.iter(MAIN + 'c'):
                formula = cell.find(MAIN + 'f')
                value = cell.find(MAIN + 'v')
                inline = cell.find(MAIN + 'is')
                if formula is not None:
                    kind = 'formula_' + formula.get('t', 'normal')
                elif cell.get('t') in {'s', 'str', 'inlineStr'} and (value is not None or inline is not None):
                    kind = 'text'
                elif value is None or value.text is None:
                    kind = 'blank'
                else:
                    kind = {'b': 'boolean', 'e': 'error', 'd': 'date'}.get(cell.get('t'), 'numeric')
                cells[sheet.attrib['name'] + '!' + cell.attrib['r']] = kind
    return cells


@contextmanager
def observe_candidates(fg, sg):
    """Patch callable references temporarily; never replace a model result."""
    traces = {'fg': {}, 'sg': {}}
    original_probes, original_repair = fg._candidate_probes, sg._candidate_repair
    original_translate, original_safe = sg.translate_formula, sg._translate_is_safe
    active = [None]

    def probes(model, cell, *args, **kwargs):
        result = original_probes(model, cell, *args, **kwargs)
        traces['fg'][cell[0] + '!' + cell[1]] = [asdict(probe) for probe in result]
        return result

    def translate(formula, origin, destination):
        result = original_translate(formula, origin, destination)
        if active[0] is not None:
            active[0]['last_source'] = origin
        return result

    def safe(formula, target):
        result = original_safe(formula, target)
        if active[0] is not None:
            active[0]['accepted' if result else 'rejected'][formula] += 1
            if result:
                active[0]['sources'].setdefault(formula, active[0].get('last_source'))
        return result

    def repair(target, *args, **kwargs):
        state = {'accepted': Counter(), 'rejected': Counter(), 'sources': {}}
        previous = active[0]
        active[0] = state
        try:
            result = original_repair(target, *args, **kwargs)
        finally:
            active[0] = previous
        traces['sg'][target.cell_id] = {
            'candidates': [dict(formula=f, calls=n, source=state['sources'][f])
                           for f, n in state['accepted'].items()],
            'unsafe_candidate_calls': sum(state['rejected'].values()),
            'pre_gate_selection': result[0], 'selected_source': result[1],
            'repair_consensus': result[2]}
        return result

    fg._candidate_probes, sg._candidate_repair = probes, repair
    sg.translate_formula, sg._translate_is_safe = translate, safe
    try:
        yield traces
    finally:
        fg._candidate_probes, sg._candidate_repair = original_probes, original_repair
        sg.translate_formula, sg._translate_is_safe = original_translate, original_safe


def predict(source):
    import formulaguard.v5_structural_guard as fg
    import structuralguard.detector as sg
    from formulaguard.workbook import WorkbookModel
    model = WorkbookModel.from_xlsx(source)
    observed = {s + '!' + a: f for (s, a), f in model.formulas.items()}
    with observe_candidates(fg, sg) as traces:
        structural = sg.analyze_workbook(source)['results']
        formula = [dict(rank=rank, cell=v.cell_label, score=v.score,
                        candidate_formula=v.candidate_formula, evidence=v.evidence)
                   for rank, v in enumerate(fg.v5_structural_guard_scores(model), 1)]
        spec = importlib.util.spec_from_file_location('trace_paper_adapter', LEGACY / 'baseline/scripts/predict.py')
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        paper = adapter.hybrid((model, structural, formula, observed, []), {})
    assert observed == {s + '!' + a: f for (s, a), f in model.formulas.items()}
    return {'paper': paper, 'observed_formulas': observed, 'candidate_trace': traces,
            'fg_selected': {r['cell']: r['candidate_formula'] for r in formula},
            'sg_selected': {r['sheet'] + '!' + r['cell']: r['suggested_formula'] for r in structural}}


def main():
    from spreadsheetbench2_scoring import sha256
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--frozen-prediction', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.input.resolve(), args.output.resolve()
    if not source.is_file() or output.exists() or source == output:
        raise SystemExit('Input must exist; output must be new and distinct')
    before = sha256(source)
    allowed = {source}
    if args.frozen_prediction:
        allowed.add(args.frozen_prediction.resolve())

    def guard(event, values):
        if event != 'open' or not values or not isinstance(values[0], (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(values[0])).resolve()
        if path in allowed:
            mode, flags = values[1:3]
            if (isinstance(mode, str) and any(c in mode for c in 'wa+')) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
                raise PermissionError('Source evidence is read-only')
            return
        if path.suffix.lower() in {'.xlsx', '.xls', '.xlsm', '.ods'} or any(
                part in {'scoring', 'model_m1'} for part in path.parts) or any(
                marker in path.name.lower() for marker in ('golden', 'truth', 'dataset.json', 'candidate_differences')):
            raise PermissionError('Trace cannot read other workbooks or scoring evidence')

    sys.addaudithook(guard)
    result = {'input_xml_types': xml_inventory(source), 'labels_read': [],
              'input_sha256': before, 'trace_scope': 'Actual probes after candidate cap; SG safe translated candidates'}
    if args.frozen_prediction:
        result.update(predict(source))
        frozen = json.loads(args.frozen_prediction.read_text())
        result['paper_content_identical'] = result['paper'] == frozen['paper']
        result['observed_formulas_identical'] = result['observed_formulas'] == frozen['observed_formulas']
        result['frozen_prediction_sha256'] = sha256(args.frozen_prediction)
        if not result['paper_content_identical'] or not result['observed_formulas_identical']:
            # Keep the observed evidence and signal a failed comparison.
            result['comparison_failure'] = True
    else:
        result['trace_not_run'] = 'Inherited baseline timeout; input type inventory only'
    if sha256(source) != before:
        raise SystemExit('Source changed')
    with gzip.open(output, 'xt', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    if result.get('comparison_failure'):
        raise SystemExit('Tracing changed paper output; preserve and investigate')


if __name__ == '__main__':
    main()
