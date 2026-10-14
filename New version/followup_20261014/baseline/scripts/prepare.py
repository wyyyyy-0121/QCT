from pathlib import Path
import zipfile, json, hashlib, shutil, xml.etree.ElementTree as E
R=Path(__file__).resolve().parents[1]; S=R/'source/HybridGuard_V5_handoff_20260904'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2))
N={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
U=N['s'];E.register_namespace('',U)
regions=['North','Central','East','South','West']
def readwb(p):
 with zipfile.ZipFile(p) as z:
  wb=E.fromstring(z.read('xl/workbook.xml')); rel=E.fromstring(z.read('xl/_rels/workbook.xml.rels'))
  targets={n.get('Id'):n.get('Target').lstrip('/') for n in rel}
  files={n.get('name'):targets[n.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')] for n in wb.findall('s:sheets/s:sheet',N)}
  files={k:(v if v.startswith('xl/') else 'xl/'+v) for k,v in files.items()}
  roots={s:E.fromstring(z.read(f)) for s,f in files.items()}
  fs={s+'!'+c.get('r'):'='+c.find('s:f',N).text for s,root in roots.items() for c in root.findall('.//s:c',N) if c.find('s:f',N) is not None}
  return files,roots,fs

def writewb(src,out,forms,onlynorth=False):
 files,roots,old=readwb(src)
 for s,root in roots.items():
  for c in root.findall('.//s:c',N):
   f=c.find('s:f',N)
   if f is not None:
    f.text=forms[s+'!'+c.get('r')].lstrip('=')
    for v in list(c.findall('s:v',N)):c.remove(v)
 with zipfile.ZipFile(src) as zi,zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as zo:
  for item in zi.infolist():
   data=zi.read(item.filename)
   if item.filename in files.values():data=E.tostring(roots[next(k for k,v in files.items() if v==item.filename)],encoding='utf-8',xml_declaration=True)
   if onlynorth and item.filename=='xl/workbook.xml':
    root=E.fromstring(data);sheets=root.find('s:sheets',N)
    for child in list(sheets):
     if child.get('name')!='North':sheets.remove(child)
    data=E.tostring(root,encoding='utf-8',xml_declaration=True)
   zo.writestr(item,data)
 # Verify every active formula, and unchanged nonformula cell payload.
 _,newroots,actual=readwb(out); expected={k:v for k,v in forms.items() if not onlynorth or k.startswith('North!')}
 assert actual==expected
 for sheet,root in newroots.items():
  def vals(rt):return {c.get('r'):E.tostring(c) for c in rt.findall('.//s:c',N) if c.find('s:f',N) is None}
  assert vals(root)==vals(roots[sheet])
 return actual

def correct(r):return f'=B{r}*C{r}*(1-D{r})*(1-G{r})-B{r}*E{r}-F{r}'
def wrong(r):return correct(r).replace(f'-B{r}*E{r}',f'+B{r}*E{r}')
def special(r):return correct(r).replace(f'-F{r}',f'-2*F{r}')
manifest=[]; clean={}
for src in sorted((S/'workbooks').glob('*.xlsx')):
 name=src.stem; truth=json.loads((src.with_name(name+'_truth.json')).read_text());_,_,observed=readwb(src)
 expected=dict(observed)
 for e in truth['errors']:assert observed[e['cell']]==e['wrong_formula'];expected[e['cell']]=e['correct_formula']
 seed=truth['seed'];clean[seed]=(src,expected)
 for variant in ['original','clean']:
  name2=name if variant=='original' else 'clean_'+str(seed);out=R/'data'/name2;out.mkdir(exist_ok=True)
  if variant=='original':shutil.copy2(src,out/'input.xlsx'); actual=observed
  else:actual=writewb(src,out/'input.xlsx',expected)
  err={k:v for k,v in expected.items() if actual[k]!=v}
  save(out/'truth.json',{'expected_formulas':expected,'errors':err})
  save(out/'public.json',{'parallel_sheets':regions})
  manifest.append({'id':name2,'family':truth['family'] if variant=='original' else 'clean','source_seed':seed,'original':variant=='original','errors':len(err),'formula_cells':len(actual),'input_sha256':digest(out/'input.xlsx')})
for seed in [101,202,303]:
 src,base=clean[seed]
 for cond in ['length_1','length_10','length_100','length_500','length_1499','shared','single','heterogeneous','exception']:
  actual=dict(base);expected=dict(base);single=cond=='single'
  if cond.startswith('length_'):
   for row in range(2,2+int(cond.split('_')[1])):actual[f'North!I{row}']=wrong(row)
  elif cond=='heterogeneous':
   for row in range(2,1501):actual[f'Central!I{row}']=expected[f'Central!I{row}']=special(row)
  else:
   sheets=regions[:3] if cond=='shared' else ['North']
   for sheet in sheets:
    for row in range(300,600):actual[f'{sheet}!I{row}']=wrong(row)
   if cond=='exception':actual['North!I400']=expected['North!I400']=special(400)
  name=cond+'_'+str(seed);out=R/'data'/name;out.mkdir(exist_ok=True)
  actual=writewb(src,out/'input.xlsx',actual,single)
  expected={k:v for k,v in expected.items() if k in actual}
  err={k:v for k,v in expected.items() if actual[k]!=v}
  save(out/'truth.json',{'expected_formulas':expected,'errors':err})
  save(out/'public.json',{'parallel_sheets':['North'] if single else regions})
  manifest.append({'id':name,'family':cond,'source_seed':seed,'original':False,'errors':len(err),'formula_cells':len(actual),'input_sha256':digest(out/'input.xlsx')})
assert len(manifest)==39
save(R/'protocol/data_manifest.json',manifest)
# Check provided hash manifest without trusting Windows path delimiters.
checks=[]
for line in (S/'SHA256SUMS.txt').read_text(encoding='utf-8-sig').splitlines():
 if not line.strip():continue
 h,fn=line.split(maxsplit=1);fn=fn.lstrip('*').replace('\\','/');p=S/fn
 checks.append({'path':fn,'exists':p.exists(),'match':p.exists() and digest(p)==h})
save(R/'qa/source_manifest_audit.json',checks)
print('Prepared',len(manifest),'workbooks; hash manifest',len(checks),'entries;',sum(x['match'] for x in checks),'match')
