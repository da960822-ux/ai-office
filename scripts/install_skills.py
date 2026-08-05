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

def extract_selected(zdata, destination, source_id, definitions):
    """Extract only requested skill trees to avoid Windows path-length failures."""
    source_definitions = [
        d for d in definitions.values() if d["source"] == source_id
    ]
    wanted_dirs = tuple(
        d["source_path"].strip("/") + "/"
        for d in source_definitions if not d.get("single_file")
    )
    wanted_files = {
        d["source_path"].strip("/")
        for d in source_definitions if d.get("single_file")
    }
    with zipfile.ZipFile(io.BytesIO(zdata)) as archive:
        names = [name for name in archive.namelist() if name and not name.endswith("/")]
        root = names[0].split("/", 1)[0]
        for name in names:
            relative = name.split("/", 1)[1] if "/" in name else ""
            if (
                relative in {"LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"}
                or relative in wanted_files
                or relative.startswith(wanted_dirs)
            ):
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
def resolve(source):
    repo=source['repo']; branch=source.get('branch','main')
    candidates=(branch,'master' if branch=='main' else 'main')
    for candidate in candidates:
        try:
            return api_json(f'https://api.github.com/repos/{repo}/commits/{candidate}')['sha'], candidate
        except Exception:
            run=subprocess.run(
                ['git','ls-remote',f'https://github.com/{repo}.git',f'refs/heads/{candidate}'],
                capture_output=True,text=True,timeout=30,shell=False,
            )
            if run.returncode == 0 and run.stdout.strip():
                return run.stdout.split()[0], candidate
    raise RuntimeError(f'Unable to resolve a branch for {repo}')

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
    # Skills are bound per department, not per employee -- every teammate gets the whole pool.
    requested=[(e,s,False) for e in selected for s in binds[emps[e]['team']]['skills']]
    needed_sources=sorted({defs[s]['source'] for _,s,_ in requested if defs[s]['source'] != 'local'})
    default_cache=ROOT/'.cache'/'skill-repos'
    if os.name == 'nt' and len(str(default_cache)) > 80:
        default_cache=Path(tempfile.gettempdir())/'ai-office-skill-cache'
    cache=Path(os.getenv('AI_OFFICE_SKILL_CACHE', str(default_cache))); cache.mkdir(parents=True,exist_ok=True)
    repo_roots={}; source_locks={}
    for source_id in needed_sources:
        src=sources[source_id]
        if src['policy']=='manual_accept_noncommercial' and not args.allow_noncommercial:
            print(f'[SKIP-LICENSE] {source_id}: use --allow-noncommercial after reviewing {src["license"]}')
            continue
        if args.dry_run:
            print('[DRY] fetch',src['repo']); continue
        sha,branch=resolve(src)
        cache_key=f'{source_id}-{sha[:12]}'
        zpath=cache/f'{cache_key}.zip'; edir=cache/cache_key
        if args.refresh and edir.exists(): shutil.rmtree(edir)
        if not edir.exists():
            data=download(f'https://github.com/{src["repo"]}/archive/{sha}.zip')
            zpath.write_bytes(data)
            extract_selected(data, edir, source_id, defs)
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
        if source_id == 'local':
            # Proprietary, authored inside one employee's own folder -- copy it to teammates too
            # now that skills are pooled per department instead of owned by one person.
            src=ROOT/meta['source_path']
            dst=ROOT/emps[emp]['profile_path'].rsplit('/',1)[0]/'skills'/sid
            if args.dry_run:
                print(f'[DRY] {emp}: {src} -> {dst}'); continue
            if not src.exists():
                print(f'[MISSING-LOCAL] {sid}: {src}',file=sys.stderr); continue
            if src.resolve() != dst.resolve():
                if dst.exists(): shutil.rmtree(dst)
                if meta.get('single_file'):
                    dst.mkdir(parents=True); shutil.copy2(src,dst/'SKILL.md')
                else:
                    shutil.copytree(src,dst)
            entry=dst/meta.get('entry','SKILL.md')
            if not entry.exists():
                print(f'[INVALID] {sid}: SKILL.md not found after copy',file=sys.stderr); continue
            lock['installed'][f'{emp}:{sid}']={
                'employee':emp,'skill_id':sid,'source_id':'local','repo':None,'commit_sha':None,
                'license':meta.get('license'),'source_path':meta['source_path'],
                'install_path':str(dst.relative_to(ROOT)),'tree_sha256':tree_hash(dst),'optional':is_optional
            }
            print('[INSTALLED]',emp,sid)
            continue
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
