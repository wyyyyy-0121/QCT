"""Make a read-only analysis view of ordinary OOXML xlsx/xlsm packages.

Preserve every worksheet byte, formula, cache and workbook property. Remove
only VBA payloads and their package declarations; never run Office, VBA or
recalculation. This is not a functional export for opening in Excel. Unsupported
packages remain failures and cannot be deleted from an evaluation denominator.
"""
from pathlib import Path, PurePosixPath
import hashlib
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

VERSION = 'hybridguard-static-ooxml-analysis-view-dev1'
LIMITS = {'members': 4096, 'uncompressed_bytes': 256 * 1024 * 1024,
          'single_part_bytes': 64 * 1024 * 1024}
PROTECTED = re.compile(r'answer|label|ground.?truth|secret|post.?run', re.I)
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'
XLSM = 'application/vnd.ms-excel.sheet.macroEnabled.main+xml'
VBA_TYPES = {'application/vnd.ms-office.vbaProject',
             'application/vnd.ms-office.vbaProjectSignature',
             'application/vnd.ms-excel.vbaData+xml'}
VBA_REL = {'vbaProject', 'vbaProjectSignature', 'vbaData'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _xml(data):
    if re.search(br'<!DOCTYPE|<!ENTITY', data, re.I):
        raise ValueError('DTD/entity declarations are not supported')
    return ET.fromstring(data)


def _target(relpart, target):
    # Package relationships live in _rels/<source>.rels, except root _rels/.rels.
    base = '' if relpart == '_rels/.rels' else posixpath.dirname(posixpath.dirname(relpart))
    resolved = posixpath.normpath(posixpath.join(base, target)) if not target.startswith('/') else target[1:]
    if resolved == '..' or resolved.startswith('../') or '\\' in resolved:
        raise ValueError('relationship target escapes package')
    return resolved


def create_view(source, destination):
    source, destination = Path(source), Path(destination)
    if source.suffix.lower() not in {'.xlsx', '.xlsm'}:
        raise ValueError('Only static OOXML xlsx/xlsm is supported; xls/xlsb remain unsupported')
    if destination.suffix.lower() != '.xlsx' or destination.exists() or source.resolve() == destination.resolve():
        raise ValueError('Destination must be a new, separate xlsx analysis file')
    original_hash = sha(source.read_bytes())
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if len(infos) > LIMITS['members'] or len(set(names)) != len(names):
            raise ValueError('Duplicate member or package member limit')
        if sum(i.file_size for i in infos) > LIMITS['uncompressed_bytes'] or any(
                i.file_size > LIMITS['single_part_bytes'] for i in infos):
            raise ValueError('Package size limit')
        if any(n.startswith('/') or '..' in PurePosixPath(n).parts or '\\' in n for n in names):
            raise ValueError('Unsafe package member path')
        if any(i.flag_bits & 1 for i in infos):
            raise ValueError('Encrypted members are unsupported')
        required = {'[Content_Types].xml', 'xl/workbook.xml', 'xl/_rels/workbook.xml.rels'}
        if not required <= set(names):
            raise ValueError('Missing core OOXML parts')
        # Inspect manifest first. Protected sheet bodies and shared strings must
        # never be read if a potential answer/label sheet is present.
        workbook_raw = archive.read('xl/workbook.xml')
        manifest = _xml(workbook_raw)
        sheets = [dict(x.attrib) for x in manifest.findall('{*}sheets/{*}sheet')]
        if any(PROTECTED.search(s['name']) for s in sheets):
            raise ValueError('Potential answer/label sheet: reject before reading cells or shared strings')
        types = _xml(archive.read('[Content_Types].xml'))
        unsupported = ('macrosheet', 'dialogsheet', 'activex', 'oleobject', 'signature', 'externalLink')
        for item in types:
            description = item.get('ContentType', '')
            if description in VBA_TYPES:
                continue
            if any(word.casefold() in description.casefold() for word in unsupported):
                raise ValueError('Unsupported active, signed, external-link or legacy sheet package')
        relations = {}
        removed = {x.get('PartName', '').lstrip('/') for x in types if x.get('ContentType') in VBA_TYPES}
        for name in names:
            if not name.endswith('.rels'):
                continue
            root = _xml(archive.read(name))
            for rel in root:
                if rel.get('TargetMode') == 'External':
                    # Ordinary hyperlinks are retained as metadata, never fetched.
                    if not rel.get('Type', '').endswith('/hyperlink'):
                        raise ValueError('External non-hyperlink relationship unsupported')
                    continue
                kind = rel.get('Type', '').rsplit('/', 1)[-1]
                target = _target(name, rel.get('Target', ''))
                if kind in VBA_REL:
                    removed.add(target)
                elif any(word in kind.casefold() for word in ['activex', 'oleobject', 'macrosheet', 'signature']):
                    raise ValueError('Unsupported active/signed relationship')
            relations[name] = root
        # Fail closed for unrecognised executable payloads; printer settings
        # are passive print metadata and never interpreted by the model.
        for name in names:
            if name.lower().endswith('.bin') and name not in removed and not name.startswith('xl/printerSettings/'):
                raise ValueError('Unrecognised binary payload')
        removed |= {n for n in names if n.endswith('.rels') and
                    (posixpath.join(posixpath.dirname(posixpath.dirname(n)),
                                    posixpath.basename(n)[:-5]) in removed)}
        changed = {}
        for relname, root in relations.items():
            if relname in removed:
                continue
            before = len(root)
            for rel in list(root):
                if rel.get('TargetMode') != 'External' and _target(relname, rel.get('Target', '')) in removed:
                    root.remove(rel)
            if len(root) != before:
                changed[relname] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        main = [x for x in types if x.get('PartName') == '/xl/workbook.xml']
        if len(main) != 1 or main[0].get('ContentType') not in {XLSX, XLSM}:
            raise ValueError('Unsupported workbook content type')
        types_changed = main[0].get('ContentType') != XLSX
        main[0].set('ContentType', XLSX)
        for entry in list(types):
            if entry.get('PartName', '').lstrip('/') in removed:
                types.remove(entry); types_changed = True
            elif entry.tag == '{'+CT+'}Default' and entry.get('ContentType') in VBA_TYPES:
                extension = '.' + entry.get('Extension', '')
                remaining = [n for n in names if n not in removed and n.endswith(extension)]
                # A default bin type may cover passive printer settings. Refuse
                # ambiguity rather than reassign its meaning during conversion.
                if remaining:
                    raise ValueError('Ambiguous default VBA content type')
                types.remove(entry); types_changed = True
        if types_changed:
            changed['[Content_Types].xml'] = ET.tostring(types, encoding='utf-8', xml_declaration=True)
        payload = {name: changed.get(name, archive.read(name)) for name in names if name not in removed}
        original_parts = {name: sha(archive.read(name)) for name in names}
    worksheet_parts = [n for n in names if n.startswith('xl/worksheets/') and n.endswith('.xml')]
    assert worksheet_parts and not (set(worksheet_parts) & (set(changed) | removed))
    assert payload['xl/workbook.xml'] == workbook_raw
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open('xb') as file:
            with zipfile.ZipFile(file, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for name in sorted(payload):
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, payload[name])
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    assert sha(source.read_bytes()) == original_hash
    return {'version': VERSION, 'source_sha256': original_hash,
            'view_sha256': sha(destination.read_bytes()), 'sheet_manifest': sheets,
            'removed_parts': {n: original_parts[n] for n in sorted(removed) if n in original_parts},
            'modified_package_metadata': sorted(changed),
            'preserved_parts': {n: original_parts[n] for n in sorted(payload) if n not in changed},
            'worksheet_xml_preserved_byte_for_byte': True,
            'macro_execution': False, 'recalculation': False,
            'functional_excel_equivalence_proven': False,
            'business_correctness_proven': False, 'final_validation_eligible': False}
