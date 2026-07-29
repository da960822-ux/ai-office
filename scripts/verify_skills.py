#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; REG=ROOT/'registry'
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
    fail=0
    for e in selected:
        base=ROOT/emps[e]['profile_path'].rsplit('/',1)[0]/'skills'
        check=binds[e]['required']+(binds[e]['optional'] if a.include_optional else [])
        for sid in check:
            p=base/sid; key=f'{e}:{sid}'
            if not (p/'SKILL.md').exists(): print('[MISSING]',key); fail+=1; continue
            if key not in lock: print('[UNLOCKED]',key); fail+=1; continue
            actual=tree_hash(p); expected=lock[key]['tree_sha256']
            if actual!=expected: print('[HASH-MISMATCH]',key); fail+=1
            else: print('[OK]',key)
    raise SystemExit(1 if fail else 0)
if __name__=='__main__': main()
