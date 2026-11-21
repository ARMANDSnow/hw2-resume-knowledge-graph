"""Download the corpus, inventory unique texts, and export a deterministic snapshot."""
import io
import hashlib
import os
import random
import re
import zipfile
from collections import Counter
from pathlib import Path

import fitz
import requests

from .config import EXTRACTED, MANIFEST, PROCESSED, RAW, ROOT, SAMPLE_PDFS, read_json, write_json
from .provenance import normalize_text, sha256

SEED = 42
ARCHIVE = RAW / "ResumesPDF.zip"
INDEX = RAW / "corpus-index-v2.json"
HEADINGS = [
    r"education|academic (?:background|qualifications?)",
    r"(?:professional |work |employment |relevant |industry )?experience|employment history|work history",
    r"(?:technical |computer |professional |key )?skills|technical (?:expertise|proficiency)|technologies",
]
DOMAIN = re.compile(r"\b(?:python|java|sql|software|programming|data analy\w*|machine learning|computer science|developer|database)\b", re.I)


def download():
    RAW.mkdir(parents=True, exist_ok=True)
    if ARCHIVE.is_file():
        return
    endpoint = os.getenv("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
    url = endpoint + "/datasets/Mehyaar/Annotated_NER_PDF_Resumes/resolve/main/ResumesPDF.zip"
    tmp = ARCHIVE.with_suffix(".download")
    with requests.get(url, stream=True, timeout=(20, 120)) as response:
        response.raise_for_status()
        with tmp.open("wb") as out:
            for block in response.iter_content(1024 * 1024):
                out.write(block)
    with zipfile.ZipFile(tmp) as archive:
        if archive.testzip():
            raise ValueError("Archive CRC mismatch")
    tmp.replace(ARCHIVE)


def pdf_pages(content):
    try:
        with fitz.open(stream=content, filetype="pdf") as pdf:
            texts = [page.get_text("text") for page in pdf]
        if any(t.strip() for t in texts):
            return texts
    except (RuntimeError, ValueError):
        pass
    import pdfplumber
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def page_boundaries(texts):
    result, start = [], 0
    for num, text in enumerate(texts, 1):
        end = start + len(text)
        result.append(dict(page_num=num, char_start=start, char_end=end, text=text))
        start = end + 1
    return result


def employer_signals(full):
    """Predefined train-only sampling stratum for the employer/product ambiguity task."""
    brands = ("Microsoft", "Amazon", "Google", "Adobe", "Oracle", "IBM", "SAP", "Cisco", "Salesforce", "Intel")
    role = r"(?:engineer|manager|developer|consultant|analyst|intern|scientist|architect)"
    found = set()
    lines = full.splitlines()
    for i, line in enumerate(lines):
        for brand in brands:
            hit = re.fullmatch(r"\s*" + brand + r"(?: (?:corporation|inc\.?|technologies|india|labs))?\s*[,|–—-]?.{0,32}", line, re.I)
            if not hit or re.search(r"office|word|excel|web services|cloud|server|database|visual|studio|certif|azure|skills", line, re.I):
                continue
            local = " ".join(lines[max(0,i-2):i+3])
            if re.search(role, local, re.I) and re.search(r"\b(?:19|20)\d{2}\b", local):
                found.add(brand)
    return sorted(found)


def inventory():
    import fcntl
    RAW.mkdir(parents=True, exist_ok=True)
    with (RAW/".inventory.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return near_duplicate_index(_build_index())


def _build_index():
    download()
    with ARCHIVE.open('rb') as source:
        signature = hashlib.file_digest(source,'sha256').hexdigest()
    if INDEX.exists():
        cached = read_json(INDEX)
        if cached["archive_sha256"] == signature:
            return cached
    counts = Counter()
    file_seen, text_seen, candidates = set(), set(), []
    with zipfile.ZipFile(ARCHIVE) as archive:
        for info in archive.infolist():
            if not info.filename.lower().endswith(".pdf") or Path(info.filename).name.startswith("._"):
                continue
            counts["pdf_files"] += 1
            if counts["pdf_files"] % 500 == 0:
                print(f"Inventory {counts['pdf_files']} PDFs", flush=True)
            content = archive.read(info)
            file_hash = sha256(content)
            if file_hash in file_seen:
                counts["duplicate_file"] += 1
                continue
            file_seen.add(file_hash)
            try:
                texts = pdf_pages(content)
            except Exception:
                counts["unreadable"] += 1
                continue
            full = "\n".join(texts)
            norm = normalize_text(full)
            text_hash = sha256(norm)
            if not norm or sum(c.isalpha() for c in norm) < 800 or norm.count("\ufffd") > len(norm) * .01:
                counts["low_quality"] += 1
                continue
            if text_hash in text_seen:
                counts["duplicate_text"] += 1
                continue
            text_seen.add(text_hash)
            if not all(re.search(r"(?:^|\n)[^\S\n]*(?:" + h + r")\b", full, re.I) for h in HEADINGS):
                counts["missing_sections"] += 1
                continue
            # Target software/data roles and prefer explicit project sections for the demonstration.
            if len(set(t.lower() for t in DOMAIN.findall(full))) < 3 or len(texts) > 4:
                counts["outside_role_scope"] += 1
                continue
            lines = [s for s in full.splitlines() if s.strip()]
            layout = (len(texts), round(len(full)/max(1,len(lines))/12), bool(re.search(r"\b(?:19|20)\d\d\s*[–-]", full)))
            candidates.append(dict(source_name=info.filename, file_hash=file_hash, text_hash=text_hash,
                                   layout=list(layout), employer_signals=employer_signals(full), explicit_projects=bool(re.search(
                                       r"(?im)^\s*(?:(?:academic|personal|selected|technical|course)\s+)?projects?\b", full))))
    if len(candidates) < 80:
        raise RuntimeError(f"Only {len(candidates)} unique eligible resumes: {counts}")
    data = dict(archive_sha256=signature, counts=dict(counts), eligible=len(candidates), candidates=candidates)
    write_json(INDEX, data)
    return data


def english_words(text):
    return re.findall(r"[a-z0-9]+",normalize_text(text))


def shingles(words):
    return set(zip(*(words[i:] for i in range(5))))


def near_duplicate_index(index):
    """Before splitting, cluster eligible texts by word 5-gram Jaccard >= 0.70."""
    path = RAW / "near-duplicates-v1.json"
    if path.exists():
        stored = read_json(path)
        if stored["archive_sha256"] == index["archive_sha256"]:
            return {**index, "near_duplicates":stored["groups"]}
    rows = index["candidates"]
    signatures, lengths = [], []
    with zipfile.ZipFile(ARCHIVE) as archive:
        for row in rows:
            words = english_words(" ".join(pdf_pages(archive.read(row["source_name"]))))
            signatures.append(shingles(words))
            lengths.append(len(words))
    parents = list(range(len(rows)))
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    links = []
    for i, left in enumerate(signatures):
        for j in range(i):
            right = signatures[j]
            if min(len(left),len(right)) < .70 * max(len(left),len(right)):
                continue
            overlap = len(left & right)
            ratio = overlap / max(1,len(left)+len(right)-overlap)
            if ratio >= .70:
                parents[find(j)] = find(i)
                links.append(dict(left=rows[i]["text_hash"],right=rows[j]["text_hash"],jaccard=ratio))
    components = {}
    for i in range(len(rows)):
        components.setdefault(find(i),[]).append(i)
    groups = []
    for members in components.values():
        if len(members) < 2:
            continue
        ordered = sorted(members,key=lambda i:(-lengths[i],rows[i]["text_hash"]))
        hashes = [rows[i]["text_hash"] for i in ordered]
        groups.append(dict(kept=hashes[0],excluded=hashes[1:],
                           members=[dict(text_hash=rows[i]["text_hash"],source=rows[i]["source_name"],
                                         words=lengths[i]) for i in ordered],
                           links=[x for x in links if x["left"] in hashes and x["right"] in hashes]))
    write_json(path,dict(archive_sha256=index["archive_sha256"],groups=groups))
    return {**index,"near_duplicates":groups}


def cohort(index):
    rows = sorted(index["candidates"], key=lambda r: r["text_hash"])
    rng = random.Random(SEED)
    rng.shuffle(rows)
    # Balance resumes with and without a separately headed project section.
    project = [r for r in rows if r["explicit_projects"]][:48]
    others = [r for r in rows if not r["explicit_projects"]][:80-len(project)]
    chosen = project + others
    if len(chosen) < 80:
        chosen += [r for r in rows if r not in chosen][:80-len(chosen)]
    rng.shuffle(chosen)
    # Use the original seeded draw only to assign sampling priority. Filtering
    # and same-stratum replacement precede any train/test assignment, so a
    # removed version does not renumber every other document in the snapshot.
    excluded = {h for g in index["near_duplicates"] for h in g["excluded"]}
    rows = [r for r in rows if r["text_hash"] not in excluded]
    if len(rows) < 80:
        raise ValueError("Not enough distinct resume families")
    available = [r for r in rows if r not in chosen]
    for i,r in enumerate(chosen):
        if r["text_hash"] in excluded:
            substitute = next((v for v in available if v["explicit_projects"]==r["explicit_projects"]), available[0])
            chosen[i] = substitute
            available.remove(substitute)
    # Reserve the test set first. Enrich only the independent training pool.
    train, test = chosen[:60], chosen[60:]
    reserve = [r for r in rows if r not in test and r["employer_signals"]]
    brands = sorted({b for r in reserve for b in r["employer_signals"]})
    enriched = []
    for brand in brands:
        enriched.extend([r for r in reserve if brand in r["employer_signals"] and r not in enriched][:2])
    train = (enriched + [r for r in train if r not in enriched])[:60]
    rng.shuffle(train)
    return train + test


def collect(pilot=False, size=12):
    index = inventory()
    chosen = cohort(index)
    if pilot:
        layouts, diverse = set(), []
        for row in sorted(chosen[:60], key=lambda r: not r["employer_signals"]):
            signature = (*row["layout"], row["explicit_projects"])
            if signature not in layouts:
                layouts.add(signature)
                diverse.append(row)
        chosen = (diverse + [r for r in chosen[:60] if r not in diverse])[:size]
    docs = []
    with zipfile.ZipFile(ARCHIVE) as archive:
        for i,row in enumerate(chosen):
            split = "train" if i < 60 else "test"
            rid = "cv-" + row["text_hash"][:12]
            content = archive.read(row["source_name"])
            pages = page_boundaries(pdf_pages(content))
            full = "\n".join(p["text"] for p in pages)
            assert sha256(content) == row["file_hash"] and sha256(normalize_text(full)) == row["text_hash"]
            pdf = SAMPLE_PDFS / split / f"{rid}.pdf"
            txt = EXTRACTED / f"{rid}.txt"
            pdf.parent.mkdir(parents=True, exist_ok=True)
            txt.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(content)
            txt.write_text(full, encoding="utf-8")
            docs.append(dict(**row, resume_id=rid, split=split, pdf_path=str(pdf.relative_to(ROOT)),
                             text_path=str(txt.relative_to(ROOT)), pages=pages))
    counts = index["counts"]
    data = dict(seed=SEED, archive_sha256=index["archive_sha256"], corpus_counts=counts,
                eligible=index["eligible"], near_duplicate_groups=index["near_duplicates"],
                near_duplicate_threshold=.70, cohort_hash=sha256("\n".join(d["split"]+":"+d["text_hash"] for d in docs)),
                dedup_removed_count=counts.get("duplicate_file",0)+counts.get("duplicate_text",0),
                documents=docs, **{s+"_hashes":[d["text_hash"] for d in docs if d["split"] == s] for s in ("train","test")})
    if not pilot and MANIFEST.exists():
        # Preserve superseded generated files outside the submission snapshot.
        current = {doc[key] for doc in docs for key in ("pdf_path","text_path")}
        for old in read_json(MANIFEST)["documents"]:
            for path in (SAMPLE_PDFS/old["split"]/(old["resume_id"]+".pdf"), EXTRACTED/(old["resume_id"]+".txt")):
                path = path.resolve()
                if path.is_relative_to(ROOT) and str(path.relative_to(ROOT)) not in current and path.is_file():
                    backup = RAW/"superseded"/path.relative_to(ROOT)
                    backup.parent.mkdir(parents=True,exist_ok=True)
                    path.replace(backup)
    write_json(PROCESSED / "pilot_manifest.json" if pilot else MANIFEST, data)
    return data
