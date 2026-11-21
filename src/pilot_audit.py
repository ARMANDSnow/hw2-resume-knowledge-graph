"""A printable record-to-page review sheet for the 12-resume pilot."""
from collections import Counter, defaultdict

from .config import PROCESSED
from .provenance import validate_quote


def review_ready(manifest, graph):
    docs = {d["resume_id"]:d for d in manifest["documents"]}
    records = {r["record_id"]:r for d in graph["documents"] for r in d["records"]}
    if len(docs) != 12 or {d["split"] for d in docs.values()} != {"train"}:
        raise ValueError("试点需要 12 份互异的训练简历")
    for e in graph["edges"]:
        p = e["properties"]
        page = docs[p["resume_id"]]["pages"][p["page_num"]-1]
        if not validate_quote(page["text"], p["evidence_quote"]):
            raise ValueError(f"试点存在无效页码或引文：{e['source']}")
        if e["type"] in ("APPLIED_SKILL","USED_SKILL"):
            r = records[p["record_id"]]
            expected = "ProjectRecord" if e["type"] == "APPLIED_SKILL" else "WorkRecord"
            if r["kind"] != expected or not validate_quote(r["record_text"],p["evidence_quote"]):
                raise ValueError(f"技能与项目/任职记录错位：{r['record_id']}")


def write_audit(manifest, graph):
    nodes = {n["id"]:n["properties"] for n in graph["nodes"]}
    by_record = defaultdict(list)
    for e in graph["edges"]:
        by_record[e["properties"]["record_id"]].append(e)
    lines = ["# 12 份试点抽检", "", "先在固定训练快照内按页数、行长、日期版式及项目标题分层，逐条检查以下证据，再登记复核结论。",
             "", f"试点文本快照 `{manifest['cohort_hash']}`。模型 `{graph.get('model','')}`。",
             "", "复核时将页内原文与切分后的任职、学历、项目和技能记录对应。工作时间仅在可解析时展示。", ""]
    for doc in graph["documents"]:
        rid = doc["resume_id"]
        original = next(d for d in manifest["documents"] if d["resume_id"] == rid)
        lines += [f"## {rid}", "", f"[原始 PDF](../../{original['pdf_path']}) · {len(original['pages'])} 页 · "
                  + "，".join(f"{k} {v}" for k,v in Counter(r["kind"] for r in doc["records"]).items()), ""]
        for r in doc["records"]:
            edges = by_record[r["record_id"]]
            facts = nodes.get(r["record_id"],{})
            date = " — ".join(str(facts.get(k) or "未知") for k in ("start_ym","end_ym"))
            pairs = [f"{e['type']} → {nodes[e['target']]['name']}" for e in edges if e["type"] in
                     ("AT_COMPANY","HELD_ROLE","AT_UNIVERSITY","USED_SKILL","APPLIED_SKILL","HAS_SKILL")]
            lines.append(f"- 第 {r['page_num']} 页 · {r['kind']} · 全文偏移 [{r['char_start']}, {r['char_end']})　"
                         + " ".join(r["record_text"].split())[:155])
            if r["kind"] == "WorkRecord":
                lines.append("  - 任职区间　"+date)
            if pairs:
                lines.append("  - "+"；".join(pairs[:10]))
        lines.append("")
    lines += ["## 双边消岐与指代复核", ""]
    for group in graph.get("disambiguation_groups",[]):
        lines.append(f"- {group['surface']}")
        for s in group["senses"]:
            lines.append(f"  - {s['resume_id']} p.{s['page_num']} · {s['edge_type']} → {s['name']} · "
                         + " ".join(s['evidence_quote'].split()))
    audit = graph.get("coref_audit", {})
    for key in ("cross_document_groups","within_document_chains","negative_controls"):
        lines.append(f"- {key}　{len(audit.get(key,[]))}")
    lines += ["", "核对技能表与项目的归属时，可逐个比对记录编号与页内引文。[逐份人工式抽查记录](pilot_review_notes.md)列出每份简历核对的位置和结果。放行结论与试点哈希见 pilot_review.json。"]
    (PROCESSED/"pilot_audit.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
