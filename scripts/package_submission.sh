#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
name="${1:-ISM2026HW2-524031910745丁宇轩}"
case "$name" in */*|.|..|"") echo "请使用单个文件名" >&2; exit 2;; esac
mkdir -p dist demo_video
.venv/bin/python - "$name" <<'PY'
import os
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

name = sys.argv[1].removesuffix(".zip")
if not name or name in {".",".."}:
    raise SystemExit("无效文件名")
roots = ["src","app.py","scripts","docker-compose.yml","pyproject.toml","requirements.txt",
         "README.md",".env.example","data/sample_pdfs","data/extracted_txt","data/processed","docs","demo_video"]
with tempfile.NamedTemporaryFile(dir="dist", delete=False) as tmp:
    temporary = Path(tmp.name)
try:
    with ZipFile(temporary,"w",ZIP_DEFLATED,compresslevel=5) as z:
        for item in roots:
            root = Path(item)
            if not root.exists():
                raise FileNotFoundError(root)
            if root.is_dir():
                z.writestr(f"{name}/{item}/", "")
            for p in sorted(root.rglob("*")) if root.is_dir() else [root]:
                if (p.is_file() and not p.is_symlink() and "__pycache__" not in p.parts
                    and p.name != ".DS_Store" and p.suffix != ".pyc"):
                    z.write(p,f"{name}/{p.as_posix()}")
    dest = Path("dist") / (name+".zip")
    os.replace(temporary,dest)
    print(dest)
finally:
    temporary.unlink(missing_ok=True)
PY
