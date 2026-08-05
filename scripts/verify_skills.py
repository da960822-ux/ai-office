#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; REG=ROOT/'registry'; POOL=ROOT/'skills'
def load(n): return json.loads((REG/n).read_text(encoding='utf-8'))
def tree_hash(path):
    h=hashlib.sha256()
    for f in sorted(x for x in path.rglob('*') if x.is_file()):
        h.update(str(f.relative_to(path)).encode()); h.update(b'\0'); h.update(f.read_bytes())
    return h.hexdigest()
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--employee',default='ALL'); ap.add_argument('--include-optional',action='store_true'); a=ap.parse_args()
    emps=load('employees.json'); binds=load('employee-skill-bindings.json'); lock=load('skills.lock.json')['installed']
    selected=list(emps) if a.employee.upper()=='ALL' else [a.employee.upper()]
    # Skills live once in the shared pool, so an id is verified once no matter how many
    # employees bind it; the employee loop only decides which ids are in scope.
    check=sorted({sid for e in selected for sid in binds[emps[e]['team']]['skills']})
    fail=0
    for sid in check:
        p=POOL/sid
        if not (p/'SKILL.md').exists(): print('[MISSING]',sid); fail+=1; continue
        if sid not in lock: print('[UNLOCKED]',sid); fail+=1; continue
        if tree_hash(p)!=lock[sid]['tree_sha256']: print('[HASH-MISMATCH]',sid); fail+=1
        else: print('[OK]',sid)
    for e in selected:
        core=ROOT/emps[e]['profile_path'].rsplit('/',1)[0]/'skills'/'_local-role-core'/'SKILL.md'
        if not core.exists(): print('[MISSING]',f'{e}:_local-role-core'); fail+=1
    raise SystemExit(1 if fail else 0)
if __name__=='__main__': main()
