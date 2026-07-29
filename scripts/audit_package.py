#!/usr/bin/env python3
from pathlib import Path
import json, sys, yaml, py_compile
ROOT=Path(__file__).resolve().parents[1]
def load(n): return json.loads((ROOT/'registry'/n).read_text(encoding='utf-8'))
emps=load('employees.json'); binds=load('employee-skill-bindings.json'); defs=load('skill-definitions.json'); sources=load('skill-sources.json')
errors=[]
if len(emps)!=24: errors.append(f'employee count={len(emps)}')
for e,d in emps.items():
    base=ROOT/d['profile_path'].rsplit('/',1)[0]
    for name in ['EMPLOYEE.md','ROLE.md','SOP.md','SKILLS.md','SKILL_INDEX.md','PERMISSIONS.yaml','EVALUATION.md','skills/_local-role-core/SKILL.md']:
        if not (base/name).exists(): errors.append(f'{e}: missing {name}')
    txt=(base/'EMPLOYEE.md').read_text(encoding='utf-8')
    for rel in ['../../../constitution/CORPORATE.md','../../../constitution/KARPATHY.md','../../../constitution/CAVEMAN.md','../../../constitution/TOKEN_ECONOMY.md']:
        if f'@{rel}' not in txt: errors.append(f'{e}: bad constitution ref {rel}')
        if not (base/rel).resolve().exists(): errors.append(f'{e}: unresolved {rel}')
    for sid in binds[e]['required']+binds[e]['optional']:
        if sid not in defs: errors.append(f'{e}: undefined {sid}')
        if f'@./skills/{sid}/SKILL.md' not in txt: errors.append(f'{e}: missing reference {sid}')
for sid,d in defs.items():
    if d['source'] not in sources: errors.append(f'{sid}: missing source')
for f in ROOT.rglob('*.yaml'):
    try: yaml.safe_load(f.read_text(encoding='utf-8'))
    except Exception as ex: errors.append(f'YAML {f.relative_to(ROOT)}: {ex}')
for f in ROOT.rglob('*.md'):
    if f.read_text(encoding='utf-8').count('```')%2: errors.append(f'fence {f.relative_to(ROOT)}')
for f in (ROOT/'scripts').glob('*.py'):
    try: py_compile.compile(str(f),doraise=True)
    except Exception as ex: errors.append(f'python {f.name}: {ex}')
if errors:
    print('\n'.join('[FAIL] '+x for x in errors)); raise SystemExit(1)
print(f'[OK] employees={len(emps)}, declared_bindings={sum(len(v["required"])+len(v["optional"]) for v in binds.values())}, skill_definitions={len(defs)}')
