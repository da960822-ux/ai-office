#!/usr/bin/env python3
"""Install exact public skill folders into each employee's local skills directory.
Network is used only while this script runs. Repositories are downloaded once, then
selected skill directories are copied into employee folders. Resolved commit SHA and
tree hashes are written to registry/skills.lock.json.
"""
from __future__ import annotations
import argparse, hashlib, io, json, os, shutil, subprocess, sys, tempfile, urllib.request, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REG=ROOT/'registry'

def load(name): return json.loads((REG/name).read_text(encoding='utf-8'))
def tree_hash(path):
    h=hashlib.sha256()
    for f in sorted(x for x in path.rglob('*') if x.is_file()):
        h.update(str(f.relative_to(path)).encode()); h.update(b'\0'); h.update(f.read_bytes())
    return h.hexdigest()
def api_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Corporate-OS-v6.2-skill-installer','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=30) as r: return json.load(r)
def download(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Corporate-OS-v6.2-skill-installer'})
    with urllib.request.urlopen(req,timeout=120) as r: return r.read()
def resolve(source):
    repo=source['repo']; branch=source.get('branch','main')
    try: return api_json(f'https://api.github.com/repos/{repo}/commits/{branch}')['sha'], branch
    except Exception:
        alt='master' if branch=='main' else 'main'
        return api_json(f'https://api.github.com/repos/{repo}/commits/{alt}')['sha'], alt

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--employee',default='ALL',help='ALL or employee ID')
    ap.add_argument('--include-optional',action='store_true')
    ap.add_argument('--allow-noncommercial',action='store_true',help='Allow CC BY-NC-SA Product Manager skills')
    ap.add_argument('--refresh',action='store_true')
    ap.add_argument('--dry-run',action='store_true')
    args=ap.parse_args()
    sources=load('skill-sources.json'); defs=load('skill-definitions.json'); binds=load('employee-skill-bindings.json'); emps=load('employees.json')
    selected=list(emps) if args.employee.upper()=='ALL' else [args.employee.upper()]
    missing=[e for e in selected if e not in emps]
    if missing: raise SystemExit(f'Unknown employee: {missing}')
    requested=[]
    for e in selected:
        requested += [(e,s,False) for s in binds[e]['required']]
        if args.include_optional: requested += [(e,s,True) for s in binds[e]['optional']]
    needed_sources=sorted({defs[s]['source'] for _,s,_ in requested})
    cache=Path(os.getenv('AI_OFFICE_SKILL_CACHE', str(ROOT/'.cache'/'skill-repos'))); cache.mkdir(parents=True,exist_ok=True)
    repo_roots={}; source_locks={}
    for source_id in needed_sources:
        src=sources[source_id]
        if src['policy']=='manual_accept_noncommercial' and not args.allow_noncommercial:
            print(f'[SKIP-LICENSE] {source_id}: use --allow-noncommercial after reviewing {src["license"]}')
            continue
        if args.dry_run:
            print('[DRY] fetch',src['repo']); continue
        sha,branch=resolve(src)
        zpath=cache/f'{source_id}-{sha}.zip'; edir=cache/f'{source_id}-{sha}'
        if args.refresh and edir.exists(): shutil.rmtree(edir)
        if not edir.exists():
            data=download(f'https://github.com/{src["repo"]}/archive/{sha}.zip')
            zpath.write_bytes(data)
            with zipfile.ZipFile(io.BytesIO(data)) as z: z.extractall(edir)
        roots=[p for p in edir.iterdir() if p.is_dir()]
        if len(roots)!=1: raise RuntimeError(f'Unexpected archive layout: {src["repo"]}')
        repo_roots[source_id]=roots[0]
        source_locks[source_id]={'repo':src['repo'],'commit_sha':sha,'license':src['license'],'branch_resolved':branch}
        candidates=[roots[0]/src.get('license_path','LICENSE'), roots[0]/'LICENSE.md', roots[0]/'LICENSE.txt', roots[0]/'COPYING']
        lic=next((x for x in candidates if x.exists()),None)
        if lic:
            dst=ROOT/'third_party'/'licenses'/source_id; dst.mkdir(parents=True,exist_ok=True)
            shutil.copy2(lic,dst/lic.name)
        else:
            print(f'[LICENSE-MISSING] {src["repo"]}: manual review required',file=sys.stderr)
    lock=load('skills.lock.json')
    for emp,sid,is_optional in requested:
        meta=defs[sid]; source_id=meta['source']
        if source_id not in repo_roots: continue
        src=repo_roots[source_id]/meta['source_path']
        dst=ROOT/emps[emp]['profile_path'].rsplit('/',1)[0]/'skills'/sid
        if args.dry_run:
            print(f'[DRY] {emp}: {src} -> {dst}'); continue
        if not src.exists():
            print(f'[MISSING-UPSTREAM] {sid}: {src}',file=sys.stderr); continue
        if dst.exists(): shutil.rmtree(dst)
        if meta.get('single_file'):
            dst.mkdir(parents=True); shutil.copy2(src,dst/'SKILL.md')
        else:
            shutil.copytree(src,dst)
        entry=dst/meta.get('entry','SKILL.md')
        if not entry.exists():
            print(f'[INVALID] {sid}: SKILL.md not found after copy',file=sys.stderr); shutil.rmtree(dst); continue
        lock['installed'][f'{emp}:{sid}']={
            'employee':emp,'skill_id':sid,'source_id':source_id,'repo':source_locks[source_id]['repo'],
            'commit_sha':source_locks[source_id]['commit_sha'],'license':source_locks[source_id]['license'],
            'source_path':meta['source_path'],'install_path':str(dst.relative_to(ROOT)),
            'tree_sha256':tree_hash(dst),'optional':is_optional
        }
        print('[INSTALLED]',emp,sid)
    if not args.dry_run:
        (REG/'skills.lock.json').write_text(json.dumps(lock,ensure_ascii=False,indent=2),encoding='utf-8')
        try:
            import yaml
            (REG/'skills.lock.yaml').write_text(yaml.safe_dump(lock,allow_unicode=True,sort_keys=False),encoding='utf-8')
        except Exception: pass
        print('Lock updated:',REG/'skills.lock.json')
if __name__=='__main__': main()
