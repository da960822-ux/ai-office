#!/usr/bin/env python3
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
emps=json.loads((ROOT/'registry/employees.json').read_text(encoding='utf-8'))
for e,d in emps.items():
    base=ROOT/d['profile_path'].rsplit('/',1)[0]
    rows=[]
    for p in sorted((base/'skills').glob('*/SKILL.md')):
        txt=p.read_text(encoding='utf-8',errors='replace')
        title=next((re.sub(r'^#\s*','',x).strip() for x in txt.splitlines() if x.startswith('#')),p.parent.name)
        summary=' '.join(x.strip() for x in txt.splitlines() if x.strip() and not x.startswith('#'))[:240]
        rows.append(f'- `{p.parent.name}`: {title} — {summary}')
    (base/'SKILL_INDEX.md').write_text('# Skill Routing Index\n\n라우팅 단계에서는 이 요약만 읽고, 선택 후 해당 SKILL.md를 연다.\n\n'+'\n'.join(rows)+'\n',encoding='utf-8')
print('Skill indexes rendered.')
