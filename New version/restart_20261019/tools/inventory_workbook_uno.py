#!/usr/bin/python3
"""Read native formulas, export only a copy, and verify the round trip via UNO.

Run using /usr/bin/python3 (python3-uno). Each invocation owns a LibreOffice
process/profile; macros and link updates are disabled. Output is private evidence.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
import uno
from com.sun.star.beans import PropertyValue

def prop(name, value):
    p = PropertyValue()
    p.Name, p.Value = name, value
    return p

def read_inventory(doc):
    sheets = []
    for sheet in doc.Sheets:
        cursor = sheet.createCursor()
        cursor.gotoEndOfUsedArea(False)
        end = cursor.RangeAddress
        if (end.EndRow + 1) * (end.EndColumn + 1) > 3_000_000:
            raise ValueError('Used range exceeds inventory limit; preserve as unsupported')
        rows = sheet.getCellRangeByPosition(0, 0, end.EndColumn, end.EndRow).getFormulaArray()
        cells = {}
        for r, row in enumerate(rows):
            for c, formula in enumerate(row):
                if formula == '':
                    continue
                cell = sheet.getCellByPosition(c, r)
                kind = cell.Type.value
                cells[cell.AbsoluteName.split('.')[-1].replace('$', '')] = {
                    'type': kind, 'formula': formula,
                    # Formula results are recomputed by Calc and are not raw XLS caches.
                    'value': cell.Value if kind in ('VALUE', 'FORMULA') else cell.String,
                    'calc_error': cell.Error,
                }
        sheets.append({'name': sheet.Name, 'cells': cells})
    return sheets

def content_projection(sheets):
    return [{ 'name': s['name'], 'cells': {a: {'type': c['type'], 'formula': c['formula']}
            for a, c in s['cells'].items()}} for s in sheets]

def read_inventory_bulk(doc):
    """Use batch UNO arrays; preserve formula types via the engine's range queries."""
    def coordinates(ranges):
        return {(r, c) for area in ranges for r in range(area.StartRow, area.EndRow + 1)
                for c in range(area.StartColumn, area.EndColumn + 1)}

    def column(index):
        result = ''
        index += 1
        while index:
            index, rem = divmod(index - 1, 26)
            result = chr(65 + rem) + result
        return result

    sheets = []
    for sheet in doc.Sheets:
        cursor = sheet.createCursor()
        cursor.gotoEndOfUsedArea(False)
        end = cursor.RangeAddress
        if (end.EndRow + 1) * (end.EndColumn + 1) > 3_000_000:
            raise ValueError('Used range exceeds inventory limit; preserve as unsupported')
        area = sheet.getCellRangeByPosition(0, 0, end.EndColumn, end.EndRow)
        rows = area.getFormulaArray()
        values = area.getDataArray()
        formulas = coordinates(sheet.queryContentCells(16).RangeAddresses)
        numbers = coordinates(sheet.queryContentCells(1 | 2).RangeAddresses)
        errors = coordinates(sheet.queryFormulaCells(4).RangeAddresses)
        cells = {}
        for r, row in enumerate(rows):
            for c, formula in enumerate(row):
                if formula == '':
                    continue
                kind = 'FORMULA' if (r, c) in formulas else ('VALUE' if (r, c) in numbers else 'TEXT')
                cells[column(c) + str(r + 1)] = {
                    'type': kind, 'formula': formula, 'value': values[r][c],
                    'calc_error': sheet.getCellByPosition(c, r).Error if (r, c) in errors else 0,
                }
        sheets.append({'name': sheet.Name, 'cells': cells})
    return sheets

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--xlsx', required=True, type=Path)
    p.add_argument('--bulk', action='store_true', help='Use batched UNO reads with typed result values')
    args = p.parse_args()
    args.input, args.output, args.xlsx = [x.resolve() for x in (args.input, args.output, args.xlsx)]
    if args.output.exists() or args.xlsx.exists():
        raise SystemExit('Refusing to overwrite evidence')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.xlsx.parent.mkdir(parents=True, exist_ok=True)
    before = hashlib.sha256(args.input.read_bytes()).hexdigest()
    doc = converted = None
    with tempfile.TemporaryDirectory(prefix='hg-uno-inventory-') as profile:
        pipe = 'hg_' + uuid.uuid4().hex
        command = ['libreoffice', '-env:UserInstallation=' + Path(profile).as_uri(),
                   '--headless', '--norestore', '--nodefault', '--nofirststartwizard',
                   '--accept=pipe,name=' + pipe + ';urp;StarOffice.ComponentContext']
        proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            local = uno.getComponentContext()
            resolver = local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver', local)
            deadline = time.monotonic() + 30
            while True:
                try:
                    ctx = resolver.resolve('uno:pipe,name=' + pipe + ';urp;StarOffice.ComponentContext')
                    break
                except Exception:
                    if time.monotonic() > deadline or proc.poll() is not None:
                        raise RuntimeError('LibreOffice connection failed')
                    time.sleep(0.1)
            desktop = ctx.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop', ctx)
            macro_never = uno.getConstantByName('com.sun.star.document.MacroExecMode.NEVER_EXECUTE')
            no_update = uno.getConstantByName('com.sun.star.document.UpdateDocMode.NO_UPDATE')
            assert macro_never == 0 and no_update == 0
            options = (prop('Hidden', True), prop('ReadOnly', True),
                       prop('MacroExecutionMode', macro_never), prop('UpdateDocMode', no_update))
            doc = desktop.loadComponentFromURL(args.input.as_uri(), '_blank', 0, options)
            if doc is None:
                raise RuntimeError('Workbook load failed')
            reader = read_inventory_bulk if args.bulk else read_inventory
            native = reader(doc)
            doc.storeToURL(args.xlsx.as_uri(), (prop('FilterName', 'Calc MS Excel 2007 XML'),
                                               prop('Overwrite', False)))
            converted = desktop.loadComponentFromURL(args.xlsx.as_uri(), '_blank', 0, options)
            roundtrip = reader(converted)
            first, second = content_projection(native), content_projection(roundtrip)
            differences = []
            first_s = {s['name']: s['cells'] for s in first}
            second_s = {s['name']: s['cells'] for s in second}
            for name in sorted(first_s.keys() | second_s.keys()):
                a, b = first_s.get(name, {}), second_s.get(name, {})
                for addr in sorted(a.keys() | b.keys()):
                    if a.get(addr) != b.get(addr):
                        differences.append({'sheet': name, 'cell': addr, 'native': a.get(addr),
                                            'roundtrip': b.get(addr)})
            assert before == hashlib.sha256(args.input.read_bytes()).hexdigest(), 'Original changed'
            result = {'input': str(args.input), 'input_sha256': before,
                      'xlsx': str(args.xlsx), 'xlsx_sha256': hashlib.sha256(args.xlsx.read_bytes()).hexdigest(),
                      'libreoffice_version': subprocess.check_output(['libreoffice', '--version'], text=True).strip(),
                      'macro_execution': 'NEVER_EXECUTE', 'link_updates': 'NO_UPDATE',
                      'reader': 'bulk-v2' if args.bulk else 'per-cell-v1',
                      'values_note': 'Calc evaluates formulas on load; values are not original cached results',
                      'native_sheets': native, 'roundtrip_sheets': roundtrip,
                      'content_projection_sha256': hashlib.sha256(json.dumps(first, sort_keys=True).encode()).hexdigest(),
                      'roundtrip_content_equal': first == second,
                      'roundtrip_differences': differences}
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps({'input': str(args.input), 'sheets': len(native),
                              'formula_count': sum(c['type'] == 'FORMULA' for s in native for c in s['cells'].values()),
                              'roundtrip_differences': len(differences)}))
        finally:
            for opened in (converted, doc):
                if opened is not None:
                    try:
                        opened.close(True)
                    except Exception:
                        pass
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

if __name__ == '__main__':
    main()
