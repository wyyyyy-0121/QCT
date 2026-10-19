#!/usr/bin/env python3
"""Read explicit printed arithmetic with supplied aliases; never infer business laws."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys

from openpyxl import load_workbook

from e3_contract import Unsupported
from relation_candidates_m6 import review
from spreadsheetbench2_scoring import sha256
from trace_paper_candidates import predict


def extract(text, aliases, symbols):
    if not isinstance(text, str) or len(text) > 2000:
        raise Unsupported('missing_or_oversized_source_text')
    value = text.strip()
    if re.search(r'\b10\s*-\s*\d', value):
        raise Unsupported('ambiguous_exponent_typography')
    if any(char in value for char in ('≈', '∑', 'Σ', '[', ']', '^', '"', "'")):
        raise Unsupported('source_notation_unsupported')
    if not value.startswith('='):
        raise Unsupported('no_explicit_rhs_equation')
    if re.search(r'\b(if|unless|not|except|only|may|must|approximately|about)\b', value, re.I):
        raise Unsupported('qualified_source_text')
    value = value[1:].strip()
    if value.endswith('='):
        value = value[:-1].strip()
    if not value or '=' in value:
        raise Unsupported('multiple_or_empty_equations')
    names = [row['text'] for row in aliases]
    if (any(not isinstance(name, str) or not name.strip() for name in names)
            or len(names) != len(set(names))
            or any(row['symbol'] not in symbols for row in aliases)):
        raise Unsupported('ambiguous_or_invalid_aliases')
    # Lex directly: unrecognised words cannot masquerade as internal q/d symbols.
    ordered = sorted(aliases, key=lambda row: len(row['text']), reverse=True)
    parts, used, index = [], set(), 0
    while index < len(value):
        if value[index].isspace():
            index += 1
            continue
        found = []
        for row in ordered:
            name = row['text']
            end = index + len(name)
            if (value.startswith(name, index)
                    and (not name[-1].isalnum() or end == len(value) or not value[end].isalnum())):
                found.append(row)
        if found:
            # Overlapping aliases have unreviewed semantics; reject rather than choose.
            if len(found) != 1:
                raise Unsupported('overlapping_aliases')
            row = found[0]
            parts.append(row['symbol'])
            used.add(row['symbol'])
            index += len(row['text'])
            continue
        number = re.match(r'(?:\d+(?:\.\d*)?|\.\d+)', value[index:])
        if number:
            parts.append(number.group())
            index += len(number.group())
            continue
        if value[index] in '+-*/()×':
            parts.append('*' if value[index] == '×' else value[index])
            index += 1
            continue
        raise Unsupported('unmapped_or_qualified_source_text')
    if not used:
        raise Unsupported('no_mapped_fields_in_equation')
    return dict(lhs='y', rhs=' '.join(parts))


def load_source(request, book):
    source = request['source']
    if source['kind'] == 'cell':
        cell = book[source['sheet']][source['cell']]
        if cell.data_type == 'f':
            raise Unsupported('dynamic_or_executable_source_formula')
        return cell.value
    if source['kind'] == 'text_lines':
        path = Path(source['path'])
        if sha256(path) != source['sha256']:
            raise Unsupported('source_document_hash_mismatch')
        lines = path.read_text().splitlines()
        start, end = source['start'], source['end']
        if not 1 <= start <= end <= len(lines):
            raise Unsupported('invalid_source_locator')
        return '\n'.join(lines[start - 1:end])
    raise Unsupported('source_kind_unsupported')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    source, output = Path(request['workbook']).resolve(), args.output.resolve()
    if output.exists() or output in (source, args.request.resolve()) or sha256(source) != request['workbook_sha256']:
        raise SystemExit('Source hash must match; output must be new and distinct')

    def guard(event, values):
        if event != 'open' or not values or not isinstance(values[0], (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(values[0])).resolve()
        if path == source:
            mode, flags = values[1:3]
            if (isinstance(mode, str) and any(c in mode for c in 'wa+')) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
                raise PermissionError('Original is read-only')
        elif path.suffix.lower() in {'.xlsx', '.xls', '.xlsm', '.ods'} or 'scoring' in path.parts or any(
                name in path.name.lower() for name in ('expected.json', 'golden', 'truth', 'after.xlsx')):
            raise PermissionError('Other workbook or scoring evidence access denied')

    sys.addaudithook(guard)
    book = load_workbook(source, read_only=True, data_only=False)
    result = dict(status='abstain', suggested_formula=None, extracted_relation=None,
                  automatic_field_mapping=False, labels_read=[], final_validation_eligible=False)
    try:
        if any(key in request for key in ('relations', 'constraints', 'candidates')):
            raise Unsupported('supplied_relation_or_candidate_forbidden')
        text = load_source(request, book)
        relation = extract(text, request['aliases'], request['symbols'])
        result['extracted_relation'] = relation
        compiled = deepcopy(request)
        compiled['relations'] = [relation]
        # Keep real original-paper candidate generation; labels never enter this call.
        paper = predict(source)
        target = request['sheet'] + '!' + request['cell']
        observed = paper['observed_formulas'].get(target)
        if observed is None:
            raise Unsupported('existing_formula_target_required')
        candidates = {row['formula'] for row in paper['candidate_trace']['fg'].get(target, [])}
        candidates.update(row['formula'] for row in paper['candidate_trace']['sg'].get(target, {}).get('candidates', []))
        paper_row = next(row for row in paper['paper']['rows'] if row['cell'] == target)
        if paper_row.get('suggested_formula'):
            candidates.add(paper_row['suggested_formula'])
        result.update(review(compiled, observed, sorted(candidates)))
        result.update(observed_formula=observed, paper_target_row=paper_row,
                      unreviewed_paper_formula_rows=len(paper['paper']['rows']) - 1)
    except (Unsupported, SyntaxError, ValueError, KeyError, TypeError) as error:
        result.update(status='unsupported', reason=str(error), suggested_formula=None)
    finally:
        book.close()
    if sha256(source) != request['workbook_sha256']:
        raise SystemExit('Source changed')
    result.update(request_sha256=sha256(args.request), workbook_sha256=sha256(source),
                  original_unchanged=True, relation_origin='Static source equation with manually supplied aliases and mapping',
                  automatic_field_mapping=False, original_source_locator=request['source'])
    with output.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write('\n')


if __name__ == '__main__':
    main()
