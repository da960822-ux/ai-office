#!/usr/bin/env python3
from pathlib import Path
import json, sys, yaml, py_compile
from skill_pool import POOL_PATH
ROOT=Path(__file__).resolve().parents[1]
def load(n): return json.loads((ROOT/'registry'/n).read_text(encoding='utf-8'))
emps=load('employees.json'); binds=load('employee-skill-bindings.json'); defs=load('skill-definitions.json'); sources=load('skill-sources.json')
errors=[]
if len(emps)!=24: errors.append(f'employee count={len(emps)}')
for e,d in emps.items():
    base=ROOT/d['profile_path'].rsplit('/',1)[0]
    for name in ['EMPLOYEE.md','SKILLS.md','SKILL_INDEX.md','PERMISSIONS.yaml','EVALUATION.md','skills/_local-role-core/SKILL.md']:
        if not (base/name).exists(): errors.append(f'{e}: missing {name}')
    txt=(base/'EMPLOYEE.md').read_text(encoding='utf-8')
    for rel in ['../../../constitution/CORPORATE.md','../../../constitution/KARPATHY.md','../../../constitution/CAVEMAN.md','../../../constitution/TOKEN_ECONOMY.md','../../../constitution/DIAGNOSIS.md']:
        if f'@{rel}' not in txt: errors.append(f'{e}: bad constitution ref {rel}')
        if not (base/rel).resolve().exists(): errors.append(f'{e}: unresolved {rel}')
    index=(base/'SKILL_INDEX.md').read_text(encoding='utf-8')
    for sid in binds[d['team']]['skills']:
        if sid not in defs: errors.append(f'{e}: undefined {sid}')
        if not (POOL_PATH/sid/'SKILL.md').exists(): errors.append(f'{e}: bound skill is not installed {sid}')
        if f'`{sid}`' not in index: errors.append(f'{e}: bound skill is absent from routing index {sid}')
for sid,d in defs.items():
    if d['source'] != 'local' and d['source'] not in sources: errors.append(f'{sid}: missing source')
excluded_roots={'.cache','.git','.venv','node_modules'}
def package_files(pattern):
    return (f for f in ROOT.rglob(pattern) if not excluded_roots.intersection(f.relative_to(ROOT).parts))
for f in package_files('*.yaml'):
    try: list(yaml.safe_load_all(f.read_text(encoding='utf-8')))
    except Exception as ex: errors.append(f'YAML {f.relative_to(ROOT)}: {ex}')
for f in package_files('*.md'):
    if 'skills' not in f.relative_to(ROOT).parts and f.read_text(encoding='utf-8').count('```')%2:
        errors.append(f'fence {f.relative_to(ROOT)}')
for f in (ROOT/'scripts').glob('*.py'):
    try: py_compile.compile(str(f),doraise=True)
    except Exception as ex: errors.append(f'python {f.name}: {ex}')
if errors:
    print('\n'.join('[FAIL] '+x for x in errors)); raise SystemExit(1)
print(f'[OK] employees={len(emps)}, declared_bindings={sum(len(v["skills"]) for v in binds.values())}, skill_definitions={len(defs)}')
