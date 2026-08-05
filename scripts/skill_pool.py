#!/usr/bin/env python3
from __future__ import annotations
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POOL_PATH = ROOT / 'skills'

def tree_hash(path):
    h = hashlib.sha256()
    for f in sorted(item for item in path.rglob('*') if item.is_file()):
        h.update(f.relative_to(path).as_posix().encode()); h.update(b'\0'); h.update(f.read_bytes())
    return h.hexdigest()
