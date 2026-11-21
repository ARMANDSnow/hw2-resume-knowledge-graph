"""Shared locations and reproducible, project-local configuration."""
import json
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
EXTRACTED = DATA / "extracted_txt"
SAMPLE_PDFS = DATA / "sample_pdfs"
MANIFEST = EXTRACTED / "manifest.json"
PROTECTED_SKILLS = ("C", "C++", "C#", "F#", ".NET", "ASP.NET", "Objective-C",
                    "PL/SQL", "T-SQL", "Node.js", "Next.js", "Vue.js", "React.js")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    os.replace(handle.name, path)
