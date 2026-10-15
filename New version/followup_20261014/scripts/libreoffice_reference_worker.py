"""Run with system Python/UNO in an isolated, timeout-controlled subprocess.

    /usr/bin/python3 libreoffice_reference_worker.py request.json result.json

Read-only import, explicit calculateAll, typed cell outputs; never store a
workbook or apply a repair. Parent kills the entire process group on timeout.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

import uno


def property_value(name, value):
    prop = uno.createUnoStruct('com.sun.star.beans.PropertyValue')
    prop.Name, prop.Value = name, value
    return prop


def main():
    request_path, result_path = map(Path, sys.argv[1:])
    request = json.loads(request_path.read_text())
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='hybridguard-lo-') as profile:
        pipe = 'hybridguard_' + uuid.uuid4().hex
        command = ['/usr/bin/libreoffice', '-env:UserInstallation=' + Path(profile).as_uri(),
                   '--headless', '--nologo', '--nodefault', '--norestore', '--nofirststartwizard',
                   '--accept=pipe,name=' + pipe + ';urp;StarOffice.ServiceManager']
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   env={**os.environ, 'SAL_USE_VCLPLUGIN': 'svp'})
        document = desktop = None
        try:
            local = uno.getComponentContext()
            resolver = local.ServiceManager.createInstanceWithContext(
                'com.sun.star.bridge.UnoUrlResolver', local)
            deadline = time.monotonic() + 15
            while True:
                try:
                    context = resolver.resolve('uno:pipe,name=' + pipe + ';urp;StarOffice.ComponentContext')
                    break
                except Exception:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('Isolated LibreOffice failed to start')
                    time.sleep(.1)
            desktop = context.ServiceManager.createInstanceWithContext(
                'com.sun.star.frame.Desktop', context)
            options = tuple(property_value(k, v) for k, v in {
                'Hidden': True, 'ReadOnly': True,
                'MacroExecutionMode': uno.getConstantByName('com.sun.star.document.MacroExecMode.NEVER_EXECUTE'),
                'UpdateDocMode': uno.getConstantByName('com.sun.star.document.UpdateDocMode.NO_UPDATE'),
            }.items())
            document = desktop.loadComponentFromURL(Path(request['input']).as_uri(), '_blank', 0, options)
            if document is None:
                raise RuntimeError('Read-only workbook load returned no document')
            document.enableAutomaticCalculation(True)
            document.calculateAll()
            cells = {}
            for label in request['cells']:
                sheet, address = label.rsplit('!', 1)
                cell = document.Sheets.getByName(sheet).getCellRangeByName(address)
                error = cell.getError()
                content_type = cell.getType().value
                result_type = cell.getPropertyValue('FormulaResultType').value
                raw = {'uno_error_code': error, 'display': cell.getString(),
                       'content_type': content_type, 'result_type': result_type,
                       'formula_imported': cell.getFormula()}
                if error:
                    raw.update(kind='error', error=cell.getString())
                elif result_type == 'TEXT':
                    raw.update(kind='text', value=cell.getString())
                elif content_type == 'EMPTY':
                    raw.update(kind='missing')
                else:
                    value = cell.getValue()
                    # Boolean formulas use a logical number format in Calc.
                    number_format = document.NumberFormats.getByKey(cell.NumberFormat)
                    is_logical = bool(number_format.getPropertyValue('Type') &
                                      uno.getConstantByName('com.sun.star.util.NumberFormat.LOGICAL'))
                    raw.update(kind='boolean' if is_logical else 'number',
                               value=bool(value) if is_logical else value)
                cells[label] = raw
            result = {'status': 'complete', 'forced_calculate_all': True,
                      'read_only': bool(document.isReadonly()), 'workbook_saved': False,
                      'cells': cells, 'wall_seconds': time.perf_counter() - started,
                      'load_options': {p.Name: p.Value for p in options}}
            result_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True,
                                              indent=2, allow_nan=False) + '\n')
        finally:
            if document is not None:
                try:
                    document.close(True)
                except Exception:
                    pass
            if desktop is not None:
                try:
                    desktop.terminate()
                except Exception:
                    pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == '__main__':
    main()
