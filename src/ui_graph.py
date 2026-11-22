"""Domain-aware Knowledge Graph Studio (LightRAG x Quartz x ReactFlow inspired).

Supports two tailored views on the same offline HTML5 Canvas engine:
- Single-resume extraction view (/extract): Layered semantic hierarchy separating
  Candidate -> Atomic Records (Work/Project/Education) -> Grounded Entities
  (Company/JobTitle/University/Evidenced Skills) vs. Listed-only Skills.
- Global KG exploration view (/graph): Concentric rings place shared hubs inside
  candidates and their records. Clustered and force layouts are also available.
"""
from __future__ import annotations

import html
import json
from collections import Counter

from .ui_theme import NODE_COLORS, NODE_LABELS_ZH

REL_META: dict[str, dict[str, str | int]] = {
    "APPLIED_SKILL": {"zh": "项目实战技能", "short": "项目实战", "color": "#C2693F", "style": "solid", "tier": 1},
    "USED_SKILL": {"zh": "任职使用技能", "short": "任职使用", "color": "#5E7D63", "style": "solid", "tier": 1},
    "AT_COMPANY": {"zh": "就职企业", "short": "就职企业", "color": "#806A93", "style": "solid", "tier": 1},
    "HELD_ROLE": {"zh": "担任岗位", "short": "担任岗位", "color": "#A88443", "style": "solid", "tier": 1},
    "AT_UNIVERSITY": {"zh": "就读院校", "short": "就读院校", "color": "#4F7F86", "style": "solid", "tier": 1},
    "HAS_EXPERIENCE": {"zh": "工作经历", "short": "工作经历", "color": "#7F93A6", "style": "solid", "tier": 2},
    "WORKED_ON": {"zh": "参与项目", "short": "参与项目", "color": "#CF8E6D", "style": "solid", "tier": 2},
    "HAS_EDUCATION": {"zh": "教育背景", "short": "教育背景", "color": "#B48E95", "style": "solid", "tier": 2},
    "HAS_SKILL": {"zh": "清单提及技能", "short": "清单提及", "color": "#B9B5A8", "style": "dashed", "tier": 3},
}


def _safe_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")


def _disambig_lookup(resolved_kg: dict) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for g in resolved_kg.get("disambiguation_groups", []):
        surface = str(g.get("surface", ""))
        for s in g.get("senses", []):
            nid = s.get("node_id")
            if nid and surface:
                mapping[nid] = surface
    return mapping


def _build_graph_payload(
    resolved_kg: dict,
    scope: str = "train",
    max_nodes: int = 160,
    focus_resume: str | None = None,
    active_record_id: str | None = None,
) -> dict:
    nodes_by_id = {n["id"]: n for n in resolved_kg.get("nodes", [])}
    edges = resolved_kg.get("edges", [])
    disambig_map = _disambig_lookup(resolved_kg)

    if focus_resume:
        rel_edges = [
            e for e in edges
            if e.get("properties", {}).get("resume_id") == focus_resume
            and e["source"] in nodes_by_id and e["target"] in nodes_by_id
        ]
        node_ids = {focus_resume} if focus_resume in nodes_by_id else set()
        for e in rel_edges:
            node_ids.add(e["source"])
            node_ids.add(e["target"])
    else:
        cand_ids = {
            n["id"]
            for n in resolved_kg.get("nodes", [])
            if n["label"] == "Candidate" and (scope == "all" or n.get("properties", {}).get("split") == scope)
        }
        scoped_edges = [
            e for e in edges
            if e.get("properties", {}).get("resume_id") in cand_ids
            and e["source"] in nodes_by_id and e["target"] in nodes_by_id
        ]
        deg = Counter()
        ev_deg = Counter()
        for e in scoped_edges:
            deg[e["source"]] += 1
            deg[e["target"]] += 1
            if e["type"] != "HAS_SKILL":
                ev_deg[e["source"]] += 1
                ev_deg[e["target"]] += 1

        by_label: dict[str, list[str]] = {}
        for nid in deg:
            by_label.setdefault(nodes_by_id[nid]["label"], []).append(nid)
        for lst in by_label.values():
            lst.sort(key=lambda nid: (-ev_deg[nid], -deg[nid], nid))

        quotas = {
            "Candidate": max(12, int(max_nodes * 0.16)),
            "Skill": max(24, int(max_nodes * 0.26)),
            "Company": max(14, int(max_nodes * 0.11)),
            "Project": max(12, int(max_nodes * 0.10)),
            "University": max(10, int(max_nodes * 0.08)),
            "JobTitle": max(14, int(max_nodes * 0.10)),
            "WorkExperience": max(14, int(max_nodes * 0.11)),
            "Education": max(8, int(max_nodes * 0.08)),
        }
        node_ids = set()
        # Prioritize disambiguated nodes and their immediate neighbors in scope.
        for nid in disambig_map:
            if nid in deg:
                node_ids.add(nid)
        for e in scoped_edges:
            if e["source"] in disambig_map and e["source"] in node_ids:
                node_ids.add(e["target"])
            elif e["target"] in disambig_map and e["target"] in node_ids:
                node_ids.add(e["source"])
        for lbl, quota in quotas.items():
            node_ids.update(by_label.get(lbl, [])[:quota])
        if len(node_ids) < max_nodes:
            for nid, _ in deg.most_common():
                node_ids.add(nid)
                if len(node_ids) >= max_nodes:
                    break
        rel_edges = [e for e in scoped_edges if e["source"] in node_ids and e["target"] in node_ids]
        connected = set()
        for e in rel_edges:
            connected.add(e["source"])
            connected.add(e["target"])
        node_ids &= connected

    # Aggregate parallel edges & compute domain evidence signals.
    evidenced_skill_counts = Counter()
    node_resumes: dict[str, set[str]] = {}
    edge_map: dict[tuple[str, str, str], dict] = {}
    for e in rel_edges:
        src, dst, etype = e["source"], e["target"], e["type"]
        p = e.get("properties", {})
        rid = p.get("resume_id", "")
        if rid:
            node_resumes.setdefault(src, set()).add(rid)
            node_resumes.setdefault(dst, set()).add(rid)
        if etype in ("USED_SKILL", "APPLIED_SKILL"):
            evidenced_skill_counts[dst] += 1
        key = (src, dst, etype)
        quote = (p.get("evidence_quote") or "").strip()[:220]
        if key not in edge_map:
            edge_map[key] = {
                "source": src,
                "target": dst,
                "type": etype,
                "resume_id": rid,
                "record_id": p.get("record_id", ""),
                "page_num": p.get("page_num", ""),
                "source_kind": p.get("source", ""),
                "valid": bool(p.get("evidence_valid", True)),
                "quote": quote,
                "count": 1,
                "quotes": [quote] if quote else [],
            }
        else:
            item = edge_map[key]
            item["count"] += 1
            if quote and quote not in item["quotes"] and len(item["quotes"]) < 3:
                item["quotes"].append(quote)

    dedup_edges = list(edge_map.values())
    deg_final = Counter()
    ev_deg_final = Counter()
    for e in dedup_edges:
        deg_final[e["source"]] += 1
        deg_final[e["target"]] += 1
        if e["type"] != "HAS_SKILL":
            ev_deg_final[e["source"]] += 1
            ev_deg_final[e["target"]] += 1

    out_nodes = []
    for nid in sorted(node_ids):
        n = nodes_by_id.get(nid)
        if not n:
            continue
        lbl = n["label"]
        props = n.get("properties", {})
        raw_name = props.get("name") or props.get("title") or props.get("degree") or nid
        short = str(raw_name).strip()
        if len(short) > 24:
            short = short[:22] + "…"
        period = ""
        if props.get("start_ym") or props.get("end_ym"):
            period = f"{props.get('start_ym', '?')} ~ {props.get('end_ym', '至今')}"
        elif props.get("year"):
            period = str(props.get("year"))
        aliases = props.get("aliases", [])[:8]
        skill_ev = evidenced_skill_counts[nid] if lbl == "Skill" else 0
        listed_only = bool(lbl == "Skill" and skill_ev == 0)
        out_nodes.append({
            "id": nid,
            "label": lbl,
            "label_zh": NODE_LABELS_ZH.get(lbl, lbl),
            "name": str(raw_name),
            "short": short,
            "degree": deg_final[nid],
            "ev_degree": ev_deg_final[nid],
            "resume_span": len(node_resumes.get(nid, set())),
            "aliases": aliases,
            "split": props.get("split", ""),
            "category": props.get("category", ""),
            "period": period,
            "degree_text": props.get("degree", ""),
            "major": props.get("major", ""),
            "page_num": props.get("page_num", ""),
            "record_text": (props.get("record_text") or "").strip()[:320],
            "disambig": disambig_map.get(nid, ""),
            "evidenced_count": skill_ev,
            "listed_only": listed_only,
            "is_center": bool(focus_resume and nid == focus_resume),
            "is_active_record": bool(active_record_id and nid == active_record_id),
        })

    # Precompute overview shortcuts for the LightRAG Inspector Drawer.
    disambig_ids = [n["id"] for n in out_nodes if n["disambig"]]
    hub_candidates = [
        n for n in out_nodes
        if n["label"] in ("Skill", "Company", "JobTitle", "University")
    ]
    hub_candidates.sort(key=lambda n: (-n["resume_span"], -n["ev_degree"], -n["degree"], n["name"]))
    record_nodes = [
        n for n in out_nodes
        if n["label"] in ("WorkExperience", "Project", "Education")
    ]
    record_nodes.sort(key=lambda n: (
        {"WorkExperience": 0, "Project": 1, "Education": 2}.get(n["label"], 9),
        n["page_num"] if isinstance(n["page_num"], int) else 999,
        n["id"],
    ))

    return {
        "nodes": out_nodes,
        "edges": dedup_edges,
        "colors": NODE_COLORS,
        "labels_zh": NODE_LABELS_ZH,
        "rel_meta": REL_META,
        "focus_mode": bool(focus_resume),
        "focus_resume": focus_resume or "",
        "active_record_id": active_record_id or "",
        "scope": scope,
        "hub_ids": [n["id"] for n in hub_candidates[:8]],
        "disambig_ids": disambig_ids[:8],
        "record_ids": [n["id"] for n in record_nodes[:16]],
    }


IFRAME_THEME = """
:root{
  color-scheme:light;
  --paper:#FAF9F5;--card:#ffffff;--glass:rgba(255,255,255,.92);--wash:#F0EEE6;
  --ink:#1F1E1D;--body:#3D3B36;--muted:#6B6963;--line:#E8E6DC;--line-strong:#D6D3C7;
  --accent:#C96442;--accent-ink:#98482F;--accent-soft:#F5E6DF;--terra:#A0662E;--terra-soft:#F4EADC;
  --plum:#806A93;--plum-soft:#EFEAF2;--slate:#4F6B82;--slate-soft:#E8EDF1;
  --shadow:0 4px 18px rgba(31,30,29,.08),0 1px 3px rgba(31,30,29,.05);
  --sans:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;
  --serif:'Source Han Serif SC','Songti SC',Georgia,serif;
  --mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
}
"""


_GRAPH_CSS = IFRAME_THEME + """
*{box-sizing:border-box}
html,body{margin:0;width:100%;height:100%;overflow:hidden;background:var(--paper);color:var(--ink);font:13px/1.45 var(--sans)}
.studio{
  position:relative;width:100%;height:100%;display:grid;
  grid-template-columns:minmax(0,1fr) 292px;
  background:var(--card);border-radius:12px;overflow:hidden;
  transition:grid-template-columns .22s ease;
}
.studio.drawer-closed{grid-template-columns:minmax(0,1fr) 0px}
.stage{position:relative;min-width:0;min-height:0;overflow:hidden;display:grid;
  grid-template-columns:minmax(0,1fr);grid-template-rows:auto minmax(0,1fr) auto;background:var(--paper)}
canvas{width:100%;height:100%;display:block;touch-action:none;cursor:grab}
canvas.grabbing{cursor:grabbing}
canvas.pointer{cursor:pointer}

/* Graph toolbar */
.hud-top{
  position:relative;z-index:10;padding:9px 10px;border-bottom:1px solid var(--line);background:var(--card);
  display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;
  pointer-events:none;
}
.hud-group{
  display:inline-flex;align-items:center;gap:6px;flex-wrap:wrap;
  pointer-events:auto;
}
.hud-pill{
  display:inline-flex;align-items:center;gap:7px;
  background:var(--glass);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
  padding:2px 4px;
}
.hud-title{font:600 13px/1.2 var(--serif);color:var(--ink);letter-spacing:-.01em}
.hud-stat{font:500 11.5px/1 var(--mono);color:var(--muted);padding-left:6px;border-left:1px solid var(--line)}

/* Segmented Layout Switcher */
.seg{
  display:inline-flex;align-items:center;padding:3px;gap:2px;
  background:var(--glass);backdrop-filter:blur(10px);
  border:1px solid var(--line);border-radius:8px;
}
.seg button{
  border:0;background:transparent;color:var(--muted);font:600 11.5px/1 var(--sans);
  padding:5px 9px;border-radius:6px;cursor:pointer;transition:all .16s ease;white-space:nowrap;
}
.seg button:hover{color:var(--ink);background:var(--wash)}
.seg button[aria-pressed=true]{background:var(--accent-soft);color:var(--accent-ink)}

/* Search & Filter Chips */
.search-wrap{position:relative;display:inline-flex;align-items:center}
.search-wrap svg{position:absolute;left:9px;width:13px;height:13px;color:var(--muted);pointer-events:none}
.search-input{
  width:176px;height:31px;padding:0 28px 0 27px;border:1px solid var(--line);border-radius:9px;
  background:var(--glass);backdrop-filter:blur(10px);color:var(--ink);font:12px var(--sans);
  outline:none;transition:border-color .15s,width .18s;
}
.search-input:focus{border-color:var(--accent-ink);width:214px;background:#fff}
.search-badge{
  position:absolute;right:7px;font:600 10px/1 var(--mono);color:var(--accent-ink);
  background:var(--accent-soft);padding:2px 5px;border-radius:4px;display:none;
}
.search-badge.show{display:inline-block}
.search-drop{
  position:absolute;top:36px;right:0;width:250px;max-height:240px;overflow:auto;
  background:#fff;border:1px solid var(--line);border-radius:9px;box-shadow:var(--shadow);
  padding:4px;display:none;z-index:25;
}
.search-drop.open{display:block}
.search-item{
  width:100%;border:0;background:transparent;text-align:left;padding:6px 8px;border-radius:6px;
  display:flex;align-items:center;gap:7px;cursor:pointer;font:12px/1.3 var(--sans);color:var(--ink);
}
.search-item:hover{background:var(--wash)}
.search-item small{margin-left:auto;font:10.5px var(--mono);color:var(--muted);flex:none}
.chip-btn{
  display:inline-flex;align-items:center;gap:5px;height:31px;padding:0 10px;
  background:var(--glass);backdrop-filter:blur(10px);border:1px solid var(--line);border-radius:9px;
  color:var(--body);font:600 11.5px/1 var(--sans);cursor:pointer;
  transition:all .15s ease;white-space:nowrap;
}
.chip-btn:hover{border-color:var(--line-strong);background:#fff;color:var(--ink)}
.chip-btn[aria-pressed=true]{background:var(--accent-soft);border-color:#E2B9A6;color:var(--accent-ink)}
.chip-btn .dot{width:6px;height:6px;border-radius:50%;background:currentColor;opacity:.65}

/* Canvas navigation */
.hud-bottom{
  padding:6px 9px;background:var(--card);border-top:1px solid var(--line);
  display:flex;align-items:center;justify-content:space-between;gap:8px;pointer-events:none;
}
.dock{
  display:inline-flex;align-items:center;gap:2px;padding:3px;
  background:var(--glass);backdrop-filter:blur(10px);
  border:1px solid var(--line);border-radius:8px;pointer-events:auto;
}
.dock button{
  display:inline-flex;align-items:center;justify-content:center;gap:4px;
  min-width:29px;height:28px;padding:0 7px;border:0;border-radius:6px;background:transparent;
  color:var(--body);font:600 11.5px var(--sans);cursor:pointer;transition:all .14s;
}
.dock button:hover{background:var(--wash);color:var(--ink)}
.dock button[aria-pressed=true]{background:var(--accent-soft);color:var(--accent-ink)}
.dock .sep{width:1px;height:16px;background:var(--line);margin:0 2px}
.dock svg{width:14px;height:14px;flex:none}

/* Node type filters */
.legend{
  display:flex;flex-wrap:wrap;justify-content:flex-end;gap:4px;max-width:calc(100% - 250px);
  pointer-events:auto;
}
.leg-btn{
  display:inline-flex;align-items:center;gap:5px;padding:4px 8px;border-radius:999px;
  background:var(--glass);backdrop-filter:blur(8px);border:1px solid var(--line);
  color:var(--ink);font:600 11px/1 var(--sans);cursor:pointer;
  transition:all .14s ease;
}
.leg-btn:hover{background:#fff;border-color:var(--line-strong);transform:translateY(-1px)}
.leg-btn.off{opacity:.42;text-decoration:line-through;background:#F3F1EA}
.leg-cnt{font:500 10.5px var(--mono);color:var(--muted)}
.node-sym{width:14px;height:14px;flex:none}

/* Floating Hover Tooltip Card */
.hover-tip{
  position:absolute;z-index:20;pointer-events:none;opacity:0;transform:translateY(4px);
  transition:opacity .12s ease,transform .12s ease;
  max-width:240px;background:rgba(255,255,255,.97);border:1px solid var(--line-strong);
  border-radius:8px;padding:8px 10px;box-shadow:var(--shadow);
}
.hover-tip.show{opacity:1;transform:translateY(0)}
.tip-head{display:flex;align-items:center;gap:5px;font:600 10.5px var(--sans);color:var(--muted);margin-bottom:2px}
.tip-name{font:700 12.5px/1.3 var(--sans);color:var(--ink);overflow-wrap:anywhere}
.tip-meta{margin-top:4px;display:flex;flex-wrap:wrap;gap:4px}
.mini-tag{
  display:inline-flex;align-items:center;padding:1px 6px;border-radius:4px;
  font:600 10px/1.4 var(--sans);background:var(--wash);color:var(--body);
}
.mini-tag.teal{background:var(--accent-soft);color:var(--accent-ink)}
.mini-tag.terra{background:var(--terra-soft);color:var(--terra)}
.mini-tag.plum{background:var(--plum-soft);color:var(--plum)}
.mini-tag.slate{background:var(--slate-soft);color:var(--slate)}

/* LightRAG Collapsible Right Inspector Drawer */
.drawer{
  background:#fff;border-left:1px solid var(--line);display:flex;flex-direction:column;
  min-width:0;min-height:0;overflow:hidden;
}
.studio.drawer-closed .drawer{border-left:0}
.drawer-head{
  display:flex;align-items:center;justify-content:space-between;gap:6px;
  padding:11px 13px;border-bottom:1px solid var(--line);background:#FBFAF7;flex:none;
}
.drawer-title{font:600 13px var(--serif);color:var(--ink);display:flex;align-items:center;gap:6px}
.drawer-body{flex:1;overflow-y:auto;padding:12px 13px 16px}
.back-btn{
  border:1px solid var(--line);background:#fff;color:var(--accent-ink);border-radius:6px;
  padding:5px 9px;font:600 12px var(--sans);cursor:pointer;
}
.back-btn:hover{background:var(--accent-soft);border-color:#E2B9A6}
.ins-hero{padding-bottom:10px;border-bottom:1px solid var(--line);margin-bottom:10px}
.ins-type{display:flex;align-items:center;gap:6px;font:600 11.5px var(--sans);color:var(--muted);margin-bottom:4px}
.ins-name{font:600 16px/1.35 var(--serif);color:var(--ink);overflow-wrap:anywhere}
.ins-id{display:block;margin-top:3px;font:11px/1.35 var(--mono);color:var(--muted);overflow-wrap:anywhere}
.ins-tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:7px}
.ins-sec{margin-top:11px}
.ins-sec-title{
  display:flex;align-items:center;justify-content:space-between;
  font:700 11px/1.2 var(--sans);color:var(--muted);letter-spacing:.03em;margin-bottom:6px;
}
.kpi-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:10px}
.kpi-box{
  background:var(--paper);border:1px solid var(--line);border-radius:7px;padding:7px 9px;
}
.kpi-box span{display:block;font:10.5px var(--sans);color:var(--muted)}
.kpi-box strong{font:700 16px/1.3 var(--mono);color:var(--ink)}
.kpi-box.teal strong{color:var(--accent-ink)}
.kpi-box.terra strong{color:var(--terra)}

/* Clickable Neighbor / Jump Chips */
.jump-list{display:flex;flex-wrap:wrap;gap:5px}
.jump-chip{
  display:inline-flex;align-items:center;gap:5px;max-width:100%;
  padding:4px 8px;border-radius:7px;border:1px solid var(--line);background:#fff;
  color:var(--ink);font:500 11.5px/1.25 var(--sans);cursor:pointer;text-align:left;
  transition:all .13s ease;
}
.jump-chip:hover{background:var(--accent-soft);border-color:#E2B9A6;color:var(--accent-ink);transform:translateY(-1px)}
.jump-chip .j-txt{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:190px}
.jump-chip .j-meta{font:10px var(--mono);color:var(--muted);flex:none}
.jump-chip.active-rec{border-color:var(--accent-ink);background:var(--accent-soft)}

/* Evidence Quote Cards */
.quote-card{
  background:var(--paper);border:1px solid var(--line);border-left:3px solid var(--accent);
  border-radius:0 7px 7px 0;padding:7px 9px;margin-bottom:7px;
}
.quote-card.project{border-left-color:var(--terra)}
.quote-card.dashed{border-left-color:#B9B5A8}
.quote-top{display:flex;align-items:center;justify-content:space-between;gap:6px;margin-bottom:4px;flex-wrap:wrap}
.quote-rel{font:600 11px var(--sans);color:var(--ink)}
.quote-pg{font:10.5px var(--mono);color:var(--muted)}
.quote-body{font:11.8px/1.55 var(--serif);color:var(--body);margin:0;overflow-wrap:anywhere}
.rec-preview{
  background:#FFFFFF;border:1px solid var(--line);border-radius:7px;padding:8px 9px;
  font:14px/1.6 var(--serif);color:var(--body);white-space:pre-wrap;overflow-wrap:anywhere;
  max-height:140px;overflow-y:auto;
}
.more-btn{
  width:100%;margin-top:4px;padding:5px;border:1px dashed var(--line-strong);border-radius:6px;
  background:transparent;color:var(--accent-ink);font:600 11.5px var(--sans);cursor:pointer;
}
.more-btn:hover{background:var(--accent-soft)}
.hint-note{font:11.5px/1.5 var(--sans);color:var(--muted);margin:6px 0 0}

button:focus-visible,input:focus-visible,canvas:focus-visible{
  outline:2px solid var(--accent-ink);outline-offset:-2px
}
@media(max-width:760px){
  .studio{grid-template-columns:1fr;grid-template-rows:minmax(0,1fr) min(30%,180px)}
  .studio.drawer-closed{grid-template-columns:1fr;grid-template-rows:1fr 0px}
  .drawer{border-left:0;border-top:1px solid var(--line)}
  .hud-top,.hud-bottom{gap:4px;padding:5px 8px}
  .hud-group{gap:4px}
  .hud-bottom{align-items:flex-start;flex-direction:column}
  .legend{justify-content:flex-start;max-width:100%;flex-wrap:nowrap;overflow-x:auto;scrollbar-width:thin;padding:2px 0}
  .leg-btn{flex:none;min-height:27px}
  .search-drop{left:0;right:auto;width:min(210px,64vw)}
}
@media(max-width:500px){
  .hud-group{width:100%;min-width:0}
  .hud-pill{justify-content:space-between;width:100%}
  .search-wrap{flex:1;min-width:60px}
  .search-input,.search-input:focus{width:100%;min-width:0}
  .chip-btn,.dock button,.seg button{min-height:30px}
}
@media(prefers-reduced-motion:reduce){*,*::after,*::before{transition:none!important}}
"""


def render_force_graph_html(
    resolved_kg: dict,
    scope: str = "train",
    max_nodes: int = 160,
    focus_resume: str | None = None,
    height: int = 600,
    active_record_id: str | None = None,
) -> str:
    payload = _build_graph_payload(
        resolved_kg,
        scope=scope,
        max_nodes=max_nodes,
        focus_resume=focus_resume,
        active_record_id=active_record_id,
    )
    scope_zh = {"train": "训练集", "test": "测试集", "all": "全图"}.get(scope, scope.upper())
    title = "简历关系图" if focus_resume else f"关系图 · {scope_zh}"
    layouts = (
        [("layered", "分层"), ("radial", "环形"), ("force", "自由布局")]
        if focus_resume
        else [("radial", "环形"), ("clustered", "按类型"), ("force", "自由布局")]
    )
    layout_btns = "".join(
        f'<button type="button" data-layout="{k}" aria-pressed="{str(i == 0).lower()}">{lbl}</button>'
        for i, (k, lbl) in enumerate(layouts)
    )
    filter_label = "隐藏清单技能" if focus_resume else "隐藏清单关系"
    filter_title = (
        "隐藏只在技能清单中提到的技能，保留经历中用过的技能"
        if focus_resume
        else "隐藏由技能清单建立的连线，保留其他关系"
    )
    body = f"""
<div class="studio" id="studio" style="height:min(100vh,{int(height)}px)">
  <section class="stage" id="stage" aria-label="{html.escape(title)}">
    <div class="hud-top">
      <div class="hud-group">
        <div class="hud-pill">
          <span class="hud-title">{html.escape(title)}</span>
          <span class="hud-stat" id="counter"></span>
        </div>
        <div class="seg" id="layoutSeg" role="group" aria-label="布局切换">{layout_btns}</div>
      </div>
      <div class="hud-group">
        <button type="button" class="chip-btn" id="evidenceToggle" aria-pressed="false" title="{html.escape(filter_title)}">
          <span class="dot"></span>{filter_label}
        </button>
        <div class="search-wrap">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
            <circle cx="7" cy="7" r="4.6"/><path d="M10.5 10.5 14 14" stroke-linecap="round"/>
          </svg>
          <input id="search" class="search-input" type="search" aria-label="搜索图中节点" placeholder="搜索图中节点" autocomplete="off">
          <span id="searchBadge" class="search-badge"></span>
          <div id="searchDrop" class="search-drop" role="group" aria-label="匹配的节点"></div>
        </div>
        <button type="button" class="chip-btn" id="drawerToggle" aria-pressed="true" title="显示或收起节点详情">详情栏</button>
      </div>
    </div>

    <canvas id="g" tabindex="0" aria-label="交互式知识图谱画布，拖动平移，滚轮缩放"></canvas>
    <div id="hoverTip" class="hover-tip" aria-hidden="true"></div>

    <div class="hud-bottom">
      <div class="dock" role="toolbar" aria-label="视图控制">
        <button type="button" id="zoomInBtn" title="放大 (+)">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M8 3.5v9M3.5 8h9" stroke-linecap="round"/></svg>
        </button>
        <button type="button" id="zoomOutBtn" title="缩小 (-)">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3.5 8h9" stroke-linecap="round"/></svg>
        </button>
        <button type="button" id="fitBtn" title="显示全图">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2.5 5.5V3.5a1 1 0 0 1 1-1h2M10.5 2.5h2a1 1 0 0 1 1 1v2M13.5 10.5v2a1 1 0 0 1-1 1h-2M5.5 13.5h-2a1 1 0 0 1-1-1v-2" stroke-linecap="round"/></svg>
        </button>
        <span class="sep"></span>
        <button type="button" id="pulseBtn" aria-pressed="true" title="显示或关闭关系流向动画">流向</button>
        <button type="button" id="edgeLblBtn" aria-pressed="false" title="显示或隐藏关系标签">关系名</button>
        <button type="button" id="pauseBtn" aria-pressed="false" title="暂停或继续自动布局">暂停</button>
      </div>
      <div class="legend" id="legend" role="group" aria-label="实体类型筛选"></div>
    </div>
  </section>

  <aside class="drawer" id="drawer" aria-label="节点与证据详情">
    <div class="drawer-head">
      <span class="drawer-title" id="drawerTitle">图谱导览</span>
      <button type="button" class="back-btn" id="backBtn" style="display:none">← 总览</button>
    </div>
    <div class="drawer-body" id="inspector" aria-live="polite"></div>
  </aside>
</div>
"""
    script = (
        "const RAW=" + _safe_json(payload) + ";\n"
        + _GRAPH_JS_CORE + "\n"
        + _GRAPH_JS_DRAW + "\n"
        + _GRAPH_JS_UI
    )
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{html.escape(title)}</title><style>{_GRAPH_CSS}</style></head>'
        f'<body>{body}<script>{script}</script></body></html>'
    )


_GRAPH_JS_CORE = r'''
const $ = id => document.getElementById(id);
const canvas = $('g'), ctx = canvas.getContext('2d');
const motion = matchMedia('(prefers-reduced-motion: reduce)');
const rootStyle = getComputedStyle(document.documentElement);
const theme = Object.fromEntries(
  ['paper', 'card', 'ink', 'body', 'muted', 'accent', 'terra', 'wash'].map(key =>
    [key, rootStyle.getPropertyValue('--' + key).trim()])
);

// Crisp vector silhouettes shared by Canvas nodes, Legend pills, and Inspector.
const SHAPES = {
  Candidate: 'M-6.2 -8.6H1.8L6.6 -3.8V7.2Q6.6 8.6 5.2 8.6H-4.8Q-6.2 8.6 -6.2 7.2Z',
  Skill: 'M-1.2 -8.2Q0 -9.4 1.2 -8.2L8.2 -1.2Q9.4 0 8.2 1.2L1.2 8.2Q0 9.4 -1.2 8.2L-8.2 1.2Q-9.4 0 -8.2 -1.2Z',
  WorkExperience: 'M-5.8 -7.4H5.8Q7.4 -7.4 7.4 -5.8V5.8Q7.4 7.4 5.8 7.4H-5.8Q-7.4 7.4 -7.4 5.8V-5.8Q-7.4 -7.4 -5.8 -7.4Z',
  Company: 'M0 -8.5L7.4 -4.2V4.2L0 8.5L-7.4 4.2V-4.2Z',
  Project: 'M0 -8.4L7.8 5.8Q8.4 7.2 6.8 7.2H-6.8Q-8.4 7.2 -7.8 5.8Z',
  Education: 'M0 -7.6A7.6 7.6 0 1 1 0 7.6A7.6 7.6 0 1 1 0 -7.6Z',
  University: 'M0 -8.2L7.5 -2.6L4.6 7.4H-4.6L-7.5 -2.6Z',
  JobTitle: 'M0 -7.6A7.6 7.6 0 1 1 0 7.6A7.6 7.6 0 1 1 0 -7.6Z',
};
const CV_FOLD = new Path2D('M1.6 -7.2V-3.4H5.4M-3.5 .8H3.4M-3.5 3.9H1.4');
const symbols = new Map(Object.entries(RAW.colors).map(([label, ink]) => {
  const d = SHAPES[label] || SHAPES.Education;
  const tint = label === 'Candidate' ? ink
    : label === 'Skill' ? '#E3EBDF'
    : label === 'Project' ? '#F6E1D5'
    : label === 'Company' ? '#EAE3EF'
    : label === 'WorkExperience' ? '#E1E8EF'
    : ink + '2b';
  return [label, { d, path: new Path2D(d), ink, tint }];
}));
const fallbackSym = { d: SHAPES.Education, path: new Path2D(SHAPES.Education), ink: '#8A877E', tint: '#EEECE5' };
const symOf = label => symbols.get(label) || fallbackSym;

function symbolIcon(label) {
  const { d, ink, tint } = symOf(label), ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '-11 -11 22 22');
  svg.setAttribute('class', 'node-sym');
  svg.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS(ns, 'path');
  p.setAttribute('d', d); p.setAttribute('fill', tint); p.setAttribute('stroke', ink);
  p.setAttribute('stroke-width', '1.6'); p.setAttribute('stroke-linejoin', 'round');
  svg.append(p);
  if (label === 'Candidate') {
    const f = document.createElementNS(ns, 'path');
    f.setAttribute('d', 'M1.6 -7.2V-3.4H5.4M-3.5 .8H3.4M-3.5 3.9H1.4');
    f.setAttribute('fill', 'none'); f.setAttribute('stroke', '#fff'); f.setAttribute('stroke-width', '1.4');
    svg.append(f);
  }
  return svg;
}

const nodes = RAW.nodes.map((n, i) => {
  const baseR = n.label === 'Candidate'
    ? (n.is_center ? 19 : 12.5)
    : n.label === 'Skill'
      ? Math.min(14, (n.listed_only ? 5.2 : 7.4) + Math.sqrt(n.ev_degree || n.degree) * 1.45)
      : Math.min(13.5, 6.2 + Math.sqrt(n.degree) * 1.35);
  return {
    ...n,
    r: baseR,
    x: 0, y: 0, vx: 0, vy: 0,
    sx: 0, sy: 0, tx: 0, ty: 0,
    opacity: 1,
    idx: i,
  };
});
const byId = new Map(nodes.map(n => [n.id, n]));
const edges = RAW.edges.map((e, i) => {
  const meta = RAW.rel_meta[e.type] || { zh: e.type, short: e.type, color: '#A8A496', style: 'solid', tier: 2 };
  return {
    ...e,
    s: byId.get(e.source),
    t: byId.get(e.target),
    meta,
    offset: (i * 0.381966) % 1,
    curve: 0,
  };
}).filter(e => e.s && e.t);

// Compute subtle curve offsets for parallel / reciprocal edges.
const pairMap = new Map();
edges.forEach(e => {
  const key = e.s.id < e.t.id ? e.s.id + '|' + e.t.id : e.t.id + '|' + e.s.id;
  if (!pairMap.has(key)) pairMap.set(key, []);
  pairMap.get(key).push(e);
});
for (const group of pairMap.values()) {
  if (group.length > 1) {
    group.forEach((e, idx) => {
      const side = (idx - (group.length - 1) / 2) * 26;
      e.curve = side || 14;
    });
  }
}

const links = new Map(nodes.map(n => [n.id, []]));
edges.forEach(e => { links.get(e.s.id).push(e); links.get(e.t.id).push(e); });

const hiddenLabels = new Set();
let hideListedOnly = false;
let layoutMode = document.querySelector('#layoutSeg [aria-pressed="true"]').dataset.layout;
let W = 0, H = 0;
let cam = { x: 0, y: 0, s: 0.85 }, camTarget = null;
let running = !motion.matches && !RAW.focus_mode;
let alphaSim = 1, pulses = !motion.matches, showEdgeLabels = false;
let visible = true, frame = 0;
let selected = null, hovered = null, dragging = null, pointerStart = null, lastPtr = null;
let morphT = 1, morphStart = 0;
let guideMeta = { kind: 'none', lanes: [], rings: [], clusters: [] };

function isNodeVisible(n) {
  if (hiddenLabels.has(n.label)) return false;
  if (hideListedOnly && RAW.focus_mode && n.listed_only) return false;
  return true;
}
function isEdgeVisible(e) {
  if (!isNodeVisible(e.s) || !isNodeVisible(e.t)) return false;
  if (hideListedOnly && e.type === 'HAS_SKILL') return false;
  return true;
}

// Smooth camera fly-to target.
function flyTo(x, y, s) {
  if (motion.matches) { cam = { x, y, s }; camTarget = null; request(); return; }
  camTarget = { x, y, s };
  request();
}
function fit(instant = false) {
  const shown = nodes.filter(isNodeVisible);
  if (!shown.length || !W || !H) return;
  let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
  for (const n of shown) {
    const x = morphT < 1 ? n.tx : n.x;
    const y = morphT < 1 ? n.ty : n.y;
    if (x < xmin) xmin = x; if (x > xmax) xmax = x;
    if (y < ymin) ymin = y; if (y > ymax) ymax = y;
  }
  const padX = Math.max(90, (xmax - xmin) * 0.14);
  const padY = Math.max(85, (ymax - ymin) * 0.16);
  const s = Math.max(0.22, Math.min(1.65, (W - 60) / (xmax - xmin + padX * 2), (H - 90) / (ymax - ymin + padY * 2)));
  const tx = -(xmin + xmax) / 2, ty = -(ymin + ymax) / 2;
  if (instant || motion.matches) { cam = { x: tx, y: ty, s }; camTarget = null; }
  else flyTo(tx, ty, s);
  request();
}

function startMorph(instant = false) {
  if (instant || motion.matches) {
    nodes.forEach(n => { n.x = n.tx; n.y = n.ty; n.sx = n.tx; n.sy = n.ty; n.vx = 0; n.vy = 0; });
    morphT = 1;
    fit(true);
    return;
  }
  nodes.forEach(n => { n.sx = n.x; n.sy = n.y; n.vx = 0; n.vy = 0; });
  morphT = 0;
  morphStart = performance.now();
  fit(false);
  request();
}

// Layout 1 (Tab 2 default): Semantic Layered Architecture with barycenter ordering.
function computeLayeredLayout() {
  const center = nodes.find(n => n.is_center) || nodes.find(n => n.label === 'Candidate');
  const works = nodes.filter(n => n.label === 'WorkExperience' && isNodeVisible(n));
  const projs = nodes.filter(n => n.label === 'Project' && isNodeVisible(n));
  const edus = nodes.filter(n => n.label === 'Education' && isNodeVisible(n));
  const records = [...works, ...projs, ...edus];
  const grounded = nodes.filter(n =>
    isNodeVisible(n) && n !== center && !records.includes(n) && !n.listed_only
  );
  const listed = nodes.filter(n => isNodeVisible(n) && n.listed_only);

  const col0X = -320, col1X = -75, col2X = 195, col3X = 430;
  const recGap = Math.max(44, Math.min(62, 460 / Math.max(records.length, 1)));
  const recSpan = (records.length - 1) * recGap;
  records.forEach((n, i) => {
    n.tx = col1X;
    n.ty = -recSpan / 2 + i * recGap;
  });
  if (center) { center.tx = col0X; center.ty = 0; }

  // Barycenter vertical ordering of Tier 2 entities by connected Tier 1 records.
  const recY = new Map(records.map(r => [r.id, r.ty]));
  const groundedWithY = grounded.map(n => {
    const ys = [];
    for (const e of links.get(n.id)) {
      if (e.type === 'HAS_SKILL') continue;
      const other = e.s === n ? e.t : e.s;
      if (recY.has(other.id)) ys.push(recY.get(other.id));
    }
    const avg = ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : 0;
    const typeBias = { Company: -4, JobTitle: -1, Skill: 1, University: 6 }[n.label] || 0;
    return { n, avg: avg + typeBias };
  }).sort((a, b) => a.avg - b.avg || b.n.ev_degree - a.n.ev_degree);

  const gGap = Math.max(30, Math.min(44, Math.max(recSpan + 70, 340) / Math.max(groundedWithY.length, 1)));
  const gSpan = (groundedWithY.length - 1) * gGap;
  groundedWithY.forEach((item, i) => {
    item.n.tx = col2X + (item.n.label === 'Skill' ? 28 : -16);
    item.n.ty = -gSpan / 2 + i * gGap;
  });

  // Compact 2-column grid for listed-only skills in Tier 3 so they never cause spaghetti.
  if (listed.length) {
    const cols = listed.length > 12 ? 2 : 1;
    const rows = Math.ceil(listed.length / cols);
    const lGap = Math.max(26, Math.min(34, 420 / Math.max(rows, 1)));
    const lSpan = (rows - 1) * lGap;
    listed.sort((a, b) => a.name.localeCompare(b.name)).forEach((n, i) => {
      const c = i % cols, r = Math.floor(i / cols);
      n.tx = col3X + c * 98;
      n.ty = -lSpan / 2 + r * lGap;
    });
  }

  const topY = -Math.max(recSpan, gSpan, 240) / 2 - 48;
  const lanes = [
    { x: col0X, y: topY, title: '候选人', sub: '简历' },
    { x: col1X, y: topY, title: '经历段落', sub: '工作 · 项目 · 教育' },
    { x: col2X + 6, y: topY, title: '技能与机构', sub: '企业 · 岗位 · 院校 · 实战技能' },
  ];
  if (listed.length) {
    lanes.push({ x: col3X + (listed.length > 12 ? 48 : 0), y: topY, title: '清单技能', sub: '只在技能清单中提及' });
  }
  guideMeta = { kind: 'lanes', lanes, rings: [], clusters: [] };
}

// Layout 2: Concentric Radial (tailored for both Tab 2 and Tab 3).
function computeRadialLayout() {
  if (RAW.focus_mode) {
    const center = nodes.find(n => n.is_center) || nodes[0];
    const records = nodes.filter(n => ['WorkExperience', 'Project', 'Education'].includes(n.label) && isNodeVisible(n));
    const grounded = nodes.filter(n => isNodeVisible(n) && n !== center && !records.includes(n) && !n.listed_only);
    const listed = nodes.filter(n => isNodeVisible(n) && n.listed_only);
    if (center) { center.tx = 0; center.ty = 0; }
    const r1 = 135, r2 = 255, r3 = 365;
    const recAng = new Map();
    records.forEach((n, i) => {
      const a = -Math.PI / 2 + (i / Math.max(records.length, 1)) * Math.PI * 2;
      recAng.set(n.id, a);
      n.tx = Math.cos(a) * r1; n.ty = Math.sin(a) * r1;
    });
    const gOrdered = grounded.map(n => {
      let sx = 0, sy = 0, cnt = 0;
      for (const e of links.get(n.id)) {
        if (e.type === 'HAS_SKILL') continue;
        const other = e.s === n ? e.t : e.s;
        if (recAng.has(other.id)) { const a = recAng.get(other.id); sx += Math.cos(a); sy += Math.sin(a); cnt++; }
      }
      return { n, ang: cnt ? Math.atan2(sy, sx) : 0 };
    }).sort((a, b) => a.ang - b.ang);
    gOrdered.forEach((item, i) => {
      const a = -Math.PI + (i / Math.max(gOrdered.length, 1)) * Math.PI * 2;
      item.n.tx = Math.cos(a) * r2; item.n.ty = Math.sin(a) * r2;
    });
    listed.forEach((n, i) => {
      const a = -Math.PI / 2 + (i / Math.max(listed.length, 1)) * Math.PI * 2;
      n.tx = Math.cos(a) * r3; n.ty = Math.sin(a) * r3;
    });
    const rings = [
      { r: r1, label: '工作、项目与教育经历' },
      { r: r2, label: '经历中的技能与机构' },
    ];
    if (listed.length) rings.push({ r: r3, label: '清单技能' });
    guideMeta = { kind: 'rings', lanes: [], rings, clusters: [] };
  } else {
    const hubs = nodes.filter(n => isNodeVisible(n) && ['Skill', 'Company', 'JobTitle', 'University'].includes(n.label))
      .sort((a, b) => b.resume_span - a.resume_span || b.degree - a.degree);
    const coreHubs = hubs.slice(0, Math.min(22, hubs.length));
    const outerEntities = hubs.slice(coreHubs.length);
    const cands = nodes.filter(n => isNodeVisible(n) && n.label === 'Candidate');
    const recs = nodes.filter(n => isNodeVisible(n) && ['WorkExperience', 'Project', 'Education'].includes(n.label));
    const r0 = 115, r1 = 235, r2 = 355;
    coreHubs.forEach((n, i) => {
      const a = -Math.PI / 2 + (i / Math.max(coreHubs.length, 1)) * Math.PI * 2;
      const rad = i === 0 && coreHubs.length > 5 ? 0 : r0 * (0.72 + (i % 2) * 0.28);
      n.tx = Math.cos(a) * rad; n.ty = Math.sin(a) * rad;
    });
    cands.forEach((n, i) => {
      const a = -Math.PI / 2 + (i / Math.max(cands.length, 1)) * Math.PI * 2;
      n.tx = Math.cos(a) * r1; n.ty = Math.sin(a) * r1;
    });
    const outerAll = [...recs, ...outerEntities];
    outerAll.forEach((n, i) => {
      const a = -Math.PI / 2 + (i / Math.max(outerAll.length, 1)) * Math.PI * 2;
      n.tx = Math.cos(a) * (r2 + (i % 2) * 24); n.ty = Math.sin(a) * (r2 + (i % 2) * 24);
    });
    guideMeta = {
      kind: 'rings',
      lanes: [],
      rings: [
        { r: r0, label: '多份简历提到的内容' },
        { r: r1, label: '候选人' },
        { r: r2, label: '经历与较少出现的实体' },
      ],
      clusters: [],
    };
  }
}

// Semantic sector centers for Tab 3 Clustered Force layout.
const CLUSTER_CENTERS = {
  Skill: { x: 0, y: -15, label: '技能' },
  Candidate: { x: -185, y: -95, label: '候选人' },
  WorkExperience: { x: -205, y: 120, label: '工作经历' },
  JobTitle: { x: -15, y: 205, label: '岗位头衔' },
  Company: { x: 185, y: 145, label: '就职企业' },
  Project: { x: 215, y: -30, label: '项目经历' },
  Education: { x: 145, y: -185, label: '教育背景' },
  University: { x: -35, y: -210, label: '就读院校' },
};

function initForcePositions(clustered) {
  nodes.forEach((n, i) => {
    if (clustered && !RAW.focus_mode) {
      const c = CLUSTER_CENTERS[n.label] || { x: 0, y: 0 };
      const a = i * 2.39996, rad = 18 + Math.sqrt(i % 28) * 18;
      n.tx = c.x + Math.cos(a) * rad;
      n.ty = c.y + Math.sin(a) * rad;
    } else {
      const a = i * 2.39996, rad = n.is_center ? 0 : 28 + Math.sqrt(i) * 28;
      n.tx = Math.cos(a) * rad;
      n.ty = Math.sin(a) * rad;
    }
  });
  guideMeta = clustered && !RAW.focus_mode
    ? {
        kind: 'clusters',
        lanes: [],
        rings: [],
        clusters: Object.entries(CLUSTER_CENTERS)
          .filter(([lbl]) => nodes.some(n => n.label === lbl && isNodeVisible(n)))
          .map(([lbl, c]) => ({ ...c, color: symOf(lbl).ink })),
      }
    : { kind: 'none', lanes: [], rings: [], clusters: [] };
}

function stepPhysics() {
  if (!running || (layoutMode !== 'force' && layoutMode !== 'clustered') || morphT < 1 || alphaSim < 0.008) return;
  const repulse = RAW.focus_mode ? 2400 : 1380;
  const gravity = layoutMode === 'clustered' ? 0.006 : 0.013;
  const clusterPull = layoutMode === 'clustered' && !RAW.focus_mode ? 0.036 : 0;

  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i];
    if (!isNodeVisible(a)) continue;
    a.vx -= a.x * gravity * alphaSim;
    a.vy -= a.y * gravity * alphaSim;
    if (clusterPull) {
      const c = CLUSTER_CENTERS[a.label] || { x: 0, y: 0 };
      a.vx += (c.x - a.x) * clusterPull * alphaSim;
      a.vy += (c.y - a.y) * clusterPull * alphaSim;
    }
    for (let j = i + 1; j < nodes.length; j++) {
      const b = nodes[j];
      if (!isNodeVisible(b)) continue;
      const dx = a.x - b.x, dy = a.y - b.y;
      const d2 = dx * dx + dy * dy + 28;
      if (d2 > 76000) continue;
      const f = (repulse / d2) * alphaSim;
      const inv = 1 / Math.sqrt(d2);
      const fx = dx * inv * f, fy = dy * inv * f;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }
  }
  for (let i = 0; i < edges.length; i++) {
    const e = edges[i];
    if (!isEdgeVisible(e)) continue;
    const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const isList = e.type === 'HAS_SKILL';
    const targetLen = RAW.focus_mode ? (isList ? 125 : 88) : (isList ? 98 : 66);
    const k = (isList ? 0.009 : 0.028) * alphaSim;
    const f = (dist - targetLen) * k;
    const fx = (dx / dist) * f, fy = (dy / dist) * f;
    e.s.vx += fx; e.s.vy += fy;
    e.t.vx -= fx; e.t.vy -= fy;
  }
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i];
    if (n === dragging) continue;
    if (n.is_center) { n.x *= 0.85; n.y *= 0.85; n.vx = 0; n.vy = 0; continue; }
    n.vx *= 0.83; n.vy *= 0.83;
    n.x += Math.max(-13, Math.min(13, n.vx));
    n.y += Math.max(-13, Math.min(13, n.vy));
  }
  alphaSim *= 0.991;
}

function applyLayout(mode, instant = false) {
  layoutMode = mode;
  document.querySelectorAll('#layoutSeg button').forEach(b =>
    b.setAttribute('aria-pressed', String(b.dataset.layout === mode))
  );
  if (mode === 'layered') {
    running = false;
    computeLayeredLayout();
    startMorph(instant);
  } else if (mode === 'radial') {
    running = false;
    computeRadialLayout();
    startMorph(instant);
  } else {
    initForcePositions(mode === 'clustered');
    running = !motion.matches;
    alphaSim = 0.95;
    if (instant || motion.matches) {
      nodes.forEach(n => { n.x = n.tx; n.y = n.ty; n.vx = 0; n.vy = 0; });
      morphT = 1;
      for (let k = 0; k < 55; k++) stepPhysics();
      fit(true);
    } else {
      startMorph(false);
    }
  }
  syncToolbar();
}
'''


_GRAPH_JS_DRAW = r'''
const FONT_SANS = '-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif';
function roundBox(x, y, w, h, r) {
  const rad = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rad, y);
  ctx.arcTo(x + w, y, x + w, y + h, rad);
  ctx.arcTo(x + w, y + h, x, y + h, rad);
  ctx.arcTo(x, y + h, x, y, rad);
  ctx.arcTo(x, y, x + w, y, rad);
  ctx.closePath();
}
function displayRadius(n) {
  const minPx = n.label === 'Candidate' ? 6.4 : n.label === 'Skill' ? 4.2 : 3.4;
  return Math.max(n.r, minPx / cam.s);
}

function drawDotGrid() {
  const spacing = cam.s < 0.45 ? 48 : 24;
  const x0 = -W / (2 * cam.s) - cam.x;
  const x1 = W / (2 * cam.s) - cam.x;
  const y0 = -H / (2 * cam.s) - cam.y;
  const y1 = H / (2 * cam.s) - cam.y;
  const sx = Math.floor(x0 / spacing) * spacing;
  const sy = Math.floor(y0 / spacing) * spacing;
  ctx.fillStyle = cam.s < 0.45 ? 'rgba(150,144,128,0.22)' : 'rgba(150,144,128,0.32)';
  const r = Math.min(1.4, Math.max(0.7, 1.05 / cam.s));
  for (let x = sx; x <= x1; x += spacing) {
    for (let y = sy; y <= y1; y += spacing) {
      ctx.fillRect(x - r * 0.5, y - r * 0.5, r, r);
    }
  }
}

function drawGuides() {
  if (guideMeta.kind === 'lanes' && guideMeta.lanes.length) {
    ctx.save();
    for (const lane of guideMeta.lanes) {
      ctx.strokeStyle = 'rgba(204,199,186,0.42)';
      ctx.lineWidth = 1 / cam.s;
      ctx.setLineDash([4 / cam.s, 5 / cam.s]);
      ctx.beginPath();
      ctx.moveTo(lane.x, lane.y + 18);
      ctx.lineTo(lane.x, -lane.y - 26);
      ctx.stroke();
      ctx.setLineDash([]);
      const fs = Math.min(13, Math.max(9.5, 11.5 / cam.s));
      ctx.font = '700 ' + fs + 'px ' + FONT_SANS;
      ctx.textAlign = 'center';
      ctx.fillStyle = theme.body;
      ctx.fillText(lane.title, lane.x, lane.y);
      ctx.font = '500 ' + (fs * 0.82) + 'px ' + FONT_SANS;
      ctx.fillStyle = theme.muted;
      ctx.fillText(lane.sub, lane.x, lane.y + fs * 1.15);
    }
    ctx.restore();
  } else if (guideMeta.kind === 'rings' && guideMeta.rings.length) {
    ctx.save();
    for (const ring of guideMeta.rings) {
      ctx.strokeStyle = 'rgba(200,195,182,0.46)';
      ctx.lineWidth = 1 / cam.s;
      ctx.setLineDash([4 / cam.s, 5 / cam.s]);
      ctx.beginPath();
      ctx.arc(0, 0, ring.r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      const fs = Math.min(12, Math.max(9, 10.5 / cam.s));
      ctx.font = '600 ' + fs + 'px ' + FONT_SANS;
      ctx.textAlign = 'center';
      ctx.fillStyle = theme.muted;
      ctx.fillText(ring.label, 0, -ring.r - 6 / cam.s);
    }
    ctx.restore();
  } else if (guideMeta.kind === 'clusters' && guideMeta.clusters.length) {
    ctx.save();
    for (const c of guideMeta.clusters) {
      const grad = ctx.createRadialGradient(c.x, c.y, 12, c.x, c.y, 105);
      grad.addColorStop(0, c.color + '14');
      grad.addColorStop(1, c.color + '00');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(c.x, c.y, 105, 0, Math.PI * 2);
      ctx.fill();
      if (cam.s < 1.35) {
        const fs = Math.min(13, Math.max(9.5, 11 / cam.s));
        ctx.font = '600 ' + fs + 'px ' + FONT_SANS;
        ctx.textAlign = 'center';
        ctx.fillStyle = c.color + '8c';
        ctx.fillText(c.label, c.x, c.y - 84);
      }
    }
    ctx.restore();
  }
}

function edgeGeom(e) {
  const sx = e.s.x, sy = e.s.y, tx = e.t.x, ty = e.t.y;
  const dx = tx - sx, dy = ty - sy;
  const dist = Math.hypot(dx, dy) || 1;
  const sr = displayRadius(e.s) + 3.5 / cam.s;
  const tr = displayRadius(e.t) + 5.5 / cam.s;
  if (layoutMode === 'layered' && Math.abs(dx) > 40) {
    const x1 = sx + Math.sign(dx) * sr, y1 = sy;
    const x2 = tx - Math.sign(dx) * tr, y2 = ty;
    const mid = (x2 - x1) * 0.46;
    return { kind: 'cubic', x1, y1, cx1: x1 + mid, cy1: y1, cx2: x2 - mid, cy2: y2, x2, y2 };
  }
  const ux = dx / dist, uy = dy / dist;
  const x1 = sx + ux * sr, y1 = sy + uy * sr;
  const x2 = tx - ux * tr, y2 = ty - uy * tr;
  const bend = e.curve || (e.type === 'HAS_SKILL' && RAW.focus_mode ? 18 : 0);
  const cx = (x1 + x2) / 2 - uy * bend;
  const cy = (y1 + y2) / 2 + ux * bend;
  return { kind: 'quad', x1, y1, cx, cy, x2, y2 };
}

function evalPoint(g, t) {
  const u = 1 - t;
  if (g.kind === 'cubic') {
    const x = u * u * u * g.x1 + 3 * u * u * t * g.cx1 + 3 * u * t * t * g.cx2 + t * t * t * g.x2;
    const y = u * u * u * g.y1 + 3 * u * u * t * g.cy1 + 3 * u * t * t * g.cy2 + t * t * t * g.y2;
    return [x, y];
  }
  return [u * u * g.x1 + 2 * u * t * g.cx + t * t * g.x2, u * u * g.y1 + 2 * u * t * g.cy + t * t * g.y2];
}

function drawArrow(x, y, ang, size, color) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(ang);
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(-size, -size * 0.48);
  ctx.lineTo(-size * 0.78, 0);
  ctx.lineTo(-size, size * 0.48);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
  ctx.restore();
}

function drawEdge(e, active, link, now) {
  const g = edgeGeom(e);
  const isList = e.type === 'HAS_SKILL';
  const dimmed = active && !link;
  const alpha = dimmed ? 0.08 : link ? 0.94 : (isList ? (RAW.focus_mode ? 0.34 : 0.22) : 0.64);
  const baseW = link ? 2.1 : (isList ? 0.85 : 1.35);
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = link ? e.meta.color : (isList ? '#B9B5A8' : e.meta.color);
  ctx.lineWidth = baseW / cam.s;
  if (isList && !link) ctx.setLineDash([4 / cam.s, 4 / cam.s]);
  ctx.beginPath();
  ctx.moveTo(g.x1, g.y1);
  if (g.kind === 'cubic') ctx.bezierCurveTo(g.cx1, g.cy1, g.cx2, g.cy2, g.x2, g.y2);
  else ctx.quadraticCurveTo(g.cx, g.cy, g.x2, g.y2);
  ctx.stroke();
  ctx.setLineDash([]);

  // Arrowhead on highlighted or high-priority semantic edges.
  if (!dimmed && (link || (!isList && (RAW.focus_mode || cam.s > 0.72)))) {
    const [px, py] = evalPoint(g, 0.92);
    const ang = Math.atan2(g.y2 - py, g.x2 - px);
    drawArrow(g.x2, g.y2, ang, (link ? 7.2 : 5.4) / cam.s, e.meta.color);
  }

  // Animated subtle flow bead along active or evidenced edges.
  if (pulses && !dimmed && (link || (!active && !isList))) {
    const speed = link ? 1900 : 3200;
    const t = (now / speed + e.offset) % 1;
    const [bx, by] = evalPoint(g, t);
    ctx.beginPath();
    ctx.arc(bx, by, (link ? 2.7 : 1.9) / cam.s, 0, Math.PI * 2);
    ctx.fillStyle = e.meta.color;
    ctx.fill();
  }

  // Crisp pill-framed relation tag on active edges or when edge labels enabled.
  if (!dimmed && ((link && (cam.s > 0.62 || RAW.focus_mode)) || (showEdgeLabels && !isList && cam.s > 0.75))) {
    const [mx, my] = evalPoint(g, 0.52);
    const lbl = e.meta.short;
    const fs = Math.max(8.5, 9.6 / cam.s);
    ctx.font = '600 ' + fs + 'px ' + FONT_SANS;
    const tw = ctx.measureText(lbl).width + 8 / cam.s;
    const th = fs + 4 / cam.s;
    ctx.globalAlpha = 0.95;
    ctx.fillStyle = theme.card;
    ctx.strokeStyle = e.meta.color + '55';
    ctx.lineWidth = 0.9 / cam.s;
    roundBox(mx - tw / 2, my - th / 2, tw, th, 4 / cam.s);
    ctx.fill(); ctx.stroke();
    ctx.fillStyle = e.meta.color;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(lbl, mx, my + 0.5 / cam.s);
  }
  ctx.restore();
}

function paintNode(n, isActive, isNeighbor, now) {
  const { path, ink, tint } = symOf(n.label);
  const r = displayRadius(n);
  ctx.save();
  ctx.globalAlpha = n.opacity;
  ctx.translate(n.x, n.y);

  // Pulsing outer ring for active record from Tab 2 or disambiguated node.
  if (n.is_active_record || n.disambig) {
    const pulse = motion.matches ? 0 : Math.sin(now / 520) * 1.5;
    ctx.save();
    ctx.beginPath();
    ctx.arc(0, 0, r + (4.5 + pulse) / cam.s, 0, Math.PI * 2);
    ctx.strokeStyle = n.disambig ? theme.terra : theme.accent;
    ctx.lineWidth = 1.4 / cam.s;
    ctx.setLineDash([3 / cam.s, 3 / cam.s]);
    ctx.stroke();
    ctx.restore();
  } else if (n.aliases && n.aliases.length > 1) {
    ctx.save();
    ctx.beginPath();
    ctx.arc(0, 0, r + 3.2 / cam.s, 0, Math.PI * 2);
    ctx.strokeStyle = ink + '66';
    ctx.lineWidth = 1 / cam.s;
    ctx.setLineDash([2.5 / cam.s, 2.5 / cam.s]);
    ctx.stroke();
    ctx.restore();
  }

  ctx.scale(r / 9, r / 9);
  const px = 9 / (r * cam.s);
  ctx.lineJoin = 'round'; ctx.lineCap = 'round';

  // Soft LightRAG / Quartz ambient halo on active/neighbor nodes.
  if (isActive) {
    ctx.strokeStyle = ink + '30';
    ctx.lineWidth = 8.5 * px;
    ctx.stroke(path);
  } else if (isNeighbor) {
    ctx.strokeStyle = ink + '1e';
    ctx.lineWidth = 4.5 * px;
    ctx.stroke(path);
  }

  // Crisp white isolation ring separating edges from node silhouette.
  ctx.strokeStyle = theme.paper;
  ctx.lineWidth = 3.2 * px;
  ctx.stroke(path);

  ctx.fillStyle = theme.card; ctx.fill(path);
  ctx.fillStyle = n.listed_only ? theme.wash : tint; ctx.fill(path);
  ctx.strokeStyle = n.listed_only ? '#A8A496' : ink;
  ctx.lineWidth = Math.min(2.3, px * (isActive ? 2.1 : 1.35));
  ctx.stroke(path);

  if (n.label === 'Candidate' && r * cam.s >= 6) {
    ctx.strokeStyle = theme.paper;
    ctx.lineWidth = Math.min(1.8, 1.3 * px);
    ctx.stroke(CV_FOLD);
  }
  ctx.restore();

  // Indicator for skills supported by experience or project records.
  if (RAW.focus_mode && n.label === 'Skill' && !n.listed_only && n.opacity > 0.5) {
    ctx.save();
    ctx.globalAlpha = n.opacity;
    ctx.beginPath();
    ctx.arc(n.x + r * 0.72, n.y - r * 0.72, 2.7 / cam.s, 0, Math.PI * 2);
    ctx.fillStyle = theme.accent;
    ctx.strokeStyle = theme.paper;
    ctx.lineWidth = 1.2 / cam.s;
    ctx.fill(); ctx.stroke();
    ctx.restore();
  }
}

function draw(now) {
  frame = 0;
  if (!visible || document.hidden) return;

  // Smooth layout morph interpolation.
  let animating = false;
  if (morphT < 1) {
    const raw = Math.min(1, (now - morphStart) / 520);
    morphT = 1 - Math.pow(1 - raw, 3);
    for (const n of nodes) {
      n.x = n.sx + (n.tx - n.sx) * morphT;
      n.y = n.sy + (n.ty - n.sy) * morphT;
    }
    if (raw < 1) animating = true;
    else { morphT = 1; alphaSim = 0.85; }
  }

  // Smooth camera fly-to interpolation.
  if (camTarget) {
    const k = 0.16;
    cam.x += (camTarget.x - cam.x) * k;
    cam.y += (camTarget.y - cam.y) * k;
    cam.s += (camTarget.s - cam.s) * k;
    if (Math.hypot(camTarget.x - cam.x, camTarget.y - cam.y) < 0.4 && Math.abs(camTarget.s - cam.s) < 0.002) {
      cam = { ...camTarget };
      camTarget = null;
    } else {
      animating = true;
    }
  }

  stepPhysics();
  ctx.clearRect(0, 0, W, H);
  ctx.save();
  ctx.translate(W / 2, H / 2);
  ctx.scale(cam.s, cam.s);
  ctx.translate(cam.x, cam.y);

  drawDotGrid();
  drawGuides();

  const active = selected || hovered;
  const near = new Set(active ? [active.id] : []);
  const visEdges = [];
  for (const e of edges) {
    if (!isEdgeVisible(e)) continue;
    const link = Boolean(active && (e.s === active || e.t === active));
    if (link) { near.add(e.s.id); near.add(e.t.id); }
    visEdges.push({ e, link });
  }

  // Draw non-highlighted edges first, then highlighted edges on top.
  for (const item of visEdges) if (!item.link) drawEdge(item.e, active, false, now);
  for (const item of visEdges) if (item.link) drawEdge(item.e, active, true, now);

  // Smooth opacity transition for Quartz calm hover-focus dimming.
  const labels = [];
  for (const n of nodes) {
    if (!isNodeVisible(n)) continue;
    const targetOp = active && !near.has(n.id) ? 0.14 : 1;
    if (Math.abs(n.opacity - targetOp) > 0.015 && !motion.matches) {
      n.opacity += (targetOp - n.opacity) * 0.24;
      animating = true;
    } else {
      n.opacity = targetOp;
    }
    if (n !== active) paintNode(n, false, Boolean(active && near.has(n.id)), now);
    const shouldLabel =
      n === active || n.is_center || n.is_active_record || Boolean(n.disambig) ||
      (RAW.focus_mode && !n.listed_only && (!active || near.has(n.id))) ||
      (RAW.focus_mode && n.listed_only && (cam.s > 0.85 || near.has(n.id))) ||
      (!active && (n.resume_span >= 6 || n.degree >= 9)) ||
      (active && near.has(n.id) && near.size <= 18) ||
      cam.s > 1.45;
    if (shouldLabel && n.opacity > 0.3) labels.push(n);
  }
  if (active && isNodeVisible(active)) paintNode(active, true, false, now);

  // Collision-free pill-halo labels prioritized by active / center / hub rank.
  labels.sort((a, b) =>
    Number(b === active) - Number(a === active) ||
    Number(b.is_center) - Number(a.is_center) ||
    Number(Boolean(b.disambig)) - Number(Boolean(a.disambig)) ||
    (b.ev_degree - a.ev_degree) || (b.degree - a.degree)
  );
  const boxes = [];
  const baseFont = Math.max(9.5, 11 / cam.s);
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  for (const n of labels) {
    const isFocus = n === active || n.is_center;
    const text = n.label === 'Candidate' && /^cv-[a-f0-9]+$/i.test(n.short) && !isFocus
      ? 'CV · ' + n.short.slice(3, 9) : n.short;
    const fs = isFocus ? baseFont * 1.08 : baseFont;
    ctx.font = (isFocus ? '700 ' : '600 ') + fs + 'px ' + FONT_SANS;
    const tw = ctx.measureText(text).width;
    const padX = 5 / cam.s, padY = 2.4 / cam.s;
    const lx = n.x;
    const ly = n.y + displayRadius(n) + fs * 0.78 + 3 / cam.s;
    const box = { l: lx - tw / 2 - padX, r: lx + tw / 2 + padX, t: ly - fs / 2 - padY, b: ly + fs / 2 + padY };
    if (!isFocus && boxes.some(b => b.l < box.r && b.r > box.l && b.t < box.b && b.b > box.t)) continue;
    boxes.push(box);

    ctx.save();
    ctx.globalAlpha = Math.min(1, n.opacity + 0.08);
    ctx.fillStyle = isFocus ? theme.card : 'rgba(250,249,245,0.88)';
    ctx.strokeStyle = isFocus ? symOf(n.label).ink + '80' : 'rgba(222,218,206,0.75)';
    ctx.lineWidth = (isFocus ? 1.2 : 0.8) / cam.s;
    roundBox(box.l, box.t, box.r - box.l, box.b - box.t, 4 / cam.s);
    ctx.fill(); ctx.stroke();
    ctx.fillStyle = isFocus ? theme.ink : theme.body;
    ctx.fillText(text, lx, ly);
    ctx.restore();
  }

  ctx.restore();
  if (animating || (running && alphaSim >= 0.008) || pulses || nodes.some(n => n.is_active_record || n.disambig)) {
    request();
  }
}
'''


_GRAPH_JS_UI = r'''
function request() { if (!frame && visible && !document.hidden) frame = requestAnimationFrame(draw); }
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt !== undefined && txt !== null) e.textContent = String(txt);
  return e;
}

function updateCounter() {
  const vn = nodes.filter(isNodeVisible).length;
  const ve = edges.filter(isEdgeVisible).length;
  $('counter').textContent = vn + ' 节点 · ' + ve + ' 关系';
}

function syncToolbar() {
  const isDyn = layoutMode === 'force' || layoutMode === 'clustered';
  $('pauseBtn').style.display = isDyn ? '' : 'none';
  $('pauseBtn').textContent = running ? '暂停' : '继续';
  $('pauseBtn').setAttribute('aria-pressed', String(!running));
  $('pulseBtn').setAttribute('aria-pressed', String(pulses));
  $('edgeLblBtn').setAttribute('aria-pressed', String(showEdgeLabels));
  $('evidenceToggle').setAttribute('aria-pressed', String(hideListedOnly));
}

function focusNode(n) {
  if (!n) { select(null); return; }
  if (hiddenLabels.has(n.label)) {
    hiddenLabels.delete(n.label);
    rebuildLegendState();
  }
  if (hideListedOnly && RAW.focus_mode && n.listed_only) {
    hideListedOnly = false;
    syncToolbar();
    if (layoutMode === 'layered' || layoutMode === 'radial') applyLayout(layoutMode, false);
  }
  select(n);
  flyTo(-n.x, -n.y, Math.max(cam.s, RAW.focus_mode ? 1.05 : 1.25));
}

function makeJumpChip(n, subText = '') {
  const btn = el('button', 'jump-chip' + (n.is_active_record ? ' active-rec' : ''));
  btn.type = 'button';
  btn.append(symbolIcon(n.label), el('span', 'j-txt', n.short));
  if (subText) btn.append(el('span', 'j-meta', subText));
  btn.title = n.label_zh + ' · ' + n.name;
  btn.onclick = () => focusNode(n);
  return btn;
}

function renderOverview() {
  const box = $('inspector');
  box.replaceChildren();
  $('drawerTitle').textContent = RAW.focus_mode ? '这份简历' : '图中有哪些内容';
  $('backBtn').style.display = 'none';

  if (RAW.focus_mode) {
    const works = nodes.filter(n => n.label === 'WorkExperience').length;
    const projs = nodes.filter(n => n.label === 'Project').length;
    const evSkills = nodes.filter(n => n.label === 'Skill' && !n.listed_only).length;
    const listSkills = nodes.filter(n => n.label === 'Skill' && n.listed_only).length;
    const kpi = el('div', 'kpi-grid');
    const mk = (lbl, val, cls = '') => {
      const k = el('div', 'kpi-box ' + cls);
      k.append(el('span', '', lbl), el('strong', '', val));
      return k;
    };
    kpi.append(mk('工作经历', works), mk('项目经历', projs, 'terra'), mk('用过的技能', evSkills, 'teal'), mk('仅列在清单', listSkills));
    box.append(kpi);

    const recs = RAW.record_ids.map(id => byId.get(id)).filter(Boolean);
    if (recs.length) {
      const sec = el('div', 'ins-sec');
      sec.append(el('div', 'ins-sec-title', '定位到经历段落'));
      const list = el('div', 'jump-list');
      for (const r of recs) {
        list.append(makeJumpChip(r, r.page_num ? 'p.' + r.page_num : ''));
      }
      sec.append(list);
      box.append(sec);
    }
    const evList = nodes.filter(n => n.label === 'Skill' && !n.listed_only).sort((a, b) => b.evidenced_count - a.evidenced_count);
    if (evList.length) {
      const sec = el('div', 'ins-sec');
      sec.append(el('div', 'ins-sec-title', '经历中用过的技能'));
      const list = el('div', 'jump-list');
      for (const s of evList.slice(0, 12)) list.append(makeJumpChip(s, '×' + s.evidenced_count));
      sec.append(list);
      box.append(sec);
    }
    box.append(el('p', 'hint-note', '虚线连接技能清单里的条目。点击一段经历，可以查看对应的简历原句。'));
  } else {
    const vn = nodes.filter(isNodeVisible).length;
    const ve = edges.filter(isEdgeVisible).length;
    const disN = nodes.filter(n => n.disambig).length;
    const aliasN = nodes.filter(n => n.aliases && n.aliases.length > 1).length;
    const kpi = el('div', 'kpi-grid');
    const mk = (lbl, val, cls = '') => {
      const k = el('div', 'kpi-box ' + cls);
      k.append(el('span', '', lbl), el('strong', '', val));
      return k;
    };
    kpi.append(mk('当前节点', vn), mk('当前关系', ve), mk('已消歧的实体', disN, 'terra'), mk('有别名的实体', aliasN, 'teal'));
    box.append(kpi);

    const disNodes = RAW.disambig_ids.map(id => byId.get(id)).filter(Boolean);
    if (disNodes.length) {
      const sec = el('div', 'ins-sec');
      sec.append(el('div', 'ins-sec-title', '同一写法的不同含义'));
      const list = el('div', 'jump-list');
      for (const d of disNodes) list.append(makeJumpChip(d, d.disambig));
      sec.append(list);
      box.append(sec);
    }
    const hubNodes = RAW.hub_ids.map(id => byId.get(id)).filter(Boolean);
    if (hubNodes.length) {
      const sec = el('div', 'ins-sec');
      sec.append(el('div', 'ins-sec-title', '多份简历共同提到'));
      const list = el('div', 'jump-list');
      for (const h of hubNodes) list.append(makeJumpChip(h, h.resume_span + '份'));
      sec.append(list);
      box.append(sec);
    }
    box.append(el('p', 'hint-note', '点击节点查看关联和原句。双击画布可回到全图。'));
  }
}

let showAllQuotes = false;
function select(n) {
  selected = n;
  showAllQuotes = false;
  if (!n) { renderOverview(); request(); return; }
  renderInspector(n);
  request();
}

function renderInspector(n) {
  const box = $('inspector');
  box.replaceChildren();
  $('drawerTitle').textContent = '节点详情';
  $('backBtn').style.display = '';

  const hero = el('div', 'ins-hero');
  const typeLine = el('div', 'ins-type', n.label_zh + ' · ' + n.degree + ' 条关联');
  typeLine.prepend(symbolIcon(n.label));
  hero.append(typeLine, el('div', 'ins-name', n.name), el('code', 'ins-id', n.id));

  const tags = el('div', 'ins-tags');
  if (n.split) tags.append(el('span', 'mini-tag slate', n.split === 'train' ? '训练集' : '测试集'));
  if (n.period) tags.append(el('span', 'mini-tag slate', n.period));
  if (n.category) tags.append(el('span', 'mini-tag', n.category));
  if (n.label === 'Skill') {
    tags.append(n.listed_only
      ? el('span', 'mini-tag', '仅清单提及')
      : el('span', 'mini-tag teal', '经历提及 ×' + n.evidenced_count));
  }
  if (n.resume_span > 1) tags.append(el('span', 'mini-tag teal', '跨 ' + n.resume_span + ' 份简历'));
  if (n.disambig) tags.append(el('span', 'mini-tag terra', '原词　' + n.disambig));
  if (n.aliases && n.aliases.length > 1) tags.append(el('span', 'mini-tag plum', '归并别名 ×' + n.aliases.length));
  if (tags.children.length) hero.append(tags);
  if (n.aliases && n.aliases.length > 1) {
    hero.append(el('p', 'hint-note', '别名：' + n.aliases.join(' / ')));
  }
  box.append(hero);

  if (n.record_text) {
    const sec = el('div', 'ins-sec');
    sec.append(el('div', 'ins-sec-title', '经历原文' + (n.page_num ? '（第 ' + n.page_num + ' 页）' : '')));
    sec.append(el('div', 'rec-preview', n.record_text));
    box.append(sec);
  }

  // Group neighbors by semantic relationship type for LightRAG-style hop jumping.
  const rels = links.get(n.id).filter(isEdgeVisible)
    .sort((a, b) => (a.meta.tier - b.meta.tier) || b.count - a.count);
  if (rels.length) {
    const grouped = new Map();
    for (const e of rels) {
      const dir = e.s === n ? '→ ' : '← ';
      const key = dir + e.meta.zh;
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push({ other: e.s === n ? e.t : e.s, edge: e });
    }
    const navSec = el('div', 'ins-sec');
    navSec.append(el('div', 'ins-sec-title', '相关节点'));
    for (const [grpLabel, items] of grouped) {
      const sub = el('div', 'hint-note', grpLabel + ' (' + items.length + ')');
      sub.style.margin = '5px 0 3px';
      navSec.append(sub);
      const wrap = el('div', 'jump-list');
      for (const it of items.slice(0, 12)) {
        wrap.append(makeJumpChip(it.other, it.edge.count > 1 ? '×' + it.edge.count : ''));
      }
      navSec.append(wrap);
    }
    box.append(navSec);

    // Verified PDF quotes section.
    const qSec = el('div', 'ins-sec');
    qSec.append(el('div', 'ins-sec-title', '关系与出处（' + rels.length + ' 条）'));
    const limit = showAllQuotes ? rels.length : 5;
    for (const e of rels.slice(0, limit)) {
      const other = e.s === n ? e.t : e.s;
      const cls = e.type === 'APPLIED_SKILL' || e.type === 'WORKED_ON' ? 'project' : e.type === 'HAS_SKILL' ? 'dashed' : '';
      const card = el('div', 'quote-card ' + cls);
      const top = el('div', 'quote-top');
      top.append(
        el('span', 'quote-rel', (e.s === n ? '→ ' : '← ') + e.meta.short + ' · ' + other.short),
        el('span', 'quote-pg', (e.resume_id || '') + ' · p.' + (e.page_num || '?') + (e.valid ? ' ✓' : ''))
      );
      card.append(top);
      const quoteText = (e.quotes && e.quotes[0]) || e.quote || '此关系记录了条目归属。';
      card.append(el('p', 'quote-body', quoteText));
      qSec.append(card);
    }
    if (!showAllQuotes && rels.length > 5) {
      const more = el('button', 'more-btn', '展开全部 ' + rels.length + ' 条证据');
      more.type = 'button';
      more.onclick = () => { showAllQuotes = true; renderInspector(n); };
      qSec.append(more);
    }
    box.append(qSec);
  }
}

// Floating Hover Tooltip Card.
const hoverTip = $('hoverTip');
function showHoverTip(n, clientX, clientY) {
  if (!n) { hoverTip.classList.remove('show'); return; }
  const rect = $('stage').getBoundingClientRect();
  hoverTip.replaceChildren();
  const head = el('div', 'tip-head', n.label_zh + ' · ' + n.degree + ' 关联');
  head.prepend(symbolIcon(n.label));
  hoverTip.append(head, el('div', 'tip-name', n.name));
  const meta = el('div', 'tip-meta');
  if (n.period) meta.append(el('span', 'mini-tag slate', n.period));
  if (n.label === 'Skill') {
    meta.append(n.listed_only ? el('span', 'mini-tag', '仅清单') : el('span', 'mini-tag teal', '经历中用过'));
  }
  if (n.disambig) meta.append(el('span', 'mini-tag terra', '原词　' + n.disambig));
  if (n.aliases && n.aliases.length > 1) meta.append(el('span', 'mini-tag plum', '归并 ×' + n.aliases.length));
  if (n.resume_span > 1) meta.append(el('span', 'mini-tag teal', n.resume_span + ' 份简历'));
  if (meta.children.length) hoverTip.append(meta);
  const lx = Math.min(rect.width - 252, Math.max(12, clientX - rect.left + 16));
  const ly = Math.min(rect.height - 96, Math.max(52, clientY - rect.top + 14));
  hoverTip.style.left = lx + 'px';
  hoverTip.style.top = ly + 'px';
  hoverTip.classList.add('show');
}

// Entity Legend Pills with live counts.
const legendBtns = new Map();
function buildLegend() {
  const counts = {};
  for (const n of nodes) counts[n.label] = (counts[n.label] || 0) + 1;
  const order = ['Candidate', 'WorkExperience', 'Project', 'Education', 'Skill', 'Company', 'JobTitle', 'University'];
  for (const lbl of order) {
    if (!counts[lbl]) continue;
    const btn = el('button', 'leg-btn');
    btn.type = 'button';
    btn.setAttribute('aria-pressed', 'true');
    btn.append(symbolIcon(lbl), el('span', '', RAW.labels_zh[lbl] || lbl), el('span', 'leg-cnt', counts[lbl]));
    btn.onclick = () => {
      if (hiddenLabels.has(lbl)) hiddenLabels.delete(lbl);
      else hiddenLabels.add(lbl);
      rebuildLegendState();
      if (selected && !isNodeVisible(selected)) select(null);
      hovered = null; showHoverTip(null);
      updateCounter();
      if (layoutMode === 'layered' || layoutMode === 'radial') applyLayout(layoutMode, false);
      else request();
    };
    legendBtns.set(lbl, btn);
    $('legend').append(btn);
  }
}
function rebuildLegendState() {
  for (const [lbl, btn] of legendBtns) {
    const on = !hiddenLabels.has(lbl);
    btn.classList.toggle('off', !on);
    btn.setAttribute('aria-pressed', String(on));
  }
}

// Search input + interactive match dropdown.
const searchInput = $('search'), searchBadge = $('searchBadge'), searchDrop = $('searchDrop');
function runSearch() {
  const q = searchInput.value.trim().toLowerCase();
  searchDrop.replaceChildren();
  if (!q) {
    searchBadge.classList.remove('show');
    searchDrop.classList.remove('open');
    return;
  }
  const hits = nodes.filter(n =>
    isNodeVisible(n) && (
      n.name.toLowerCase().includes(q) ||
      n.id.toLowerCase().includes(q) ||
      n.label_zh.toLowerCase().includes(q) ||
      (n.aliases || []).some(a => a.toLowerCase().includes(q))
    )
  ).sort((a, b) => b.ev_degree - a.ev_degree || b.degree - a.degree);
  searchBadge.textContent = hits.length;
  searchBadge.classList.add('show');
  if (!hits.length) {
    searchDrop.append(el('div', 'hint-note', '未找到匹配节点'));
  } else {
    for (const n of hits.slice(0, 12)) {
      const item = el('button', 'search-item');
      item.type = 'button';
      item.append(symbolIcon(n.label), el('span', '', n.short), el('small', '', n.label_zh));
      item.onclick = () => { searchDrop.classList.remove('open'); focusNode(n); };
      searchDrop.append(item);
    }
  }
  searchDrop.classList.add('open');
}
searchInput.oninput = runSearch;
searchInput.onfocus = () => { if (searchInput.value.trim()) searchDrop.classList.add('open'); };
searchInput.onkeydown = e => {
  if (e.key === 'Enter') {
    const first = searchDrop.querySelector('.search-item');
    if (first) first.click();
  } else if (e.key === 'Escape') {
    searchDrop.classList.remove('open');
  }
};
document.addEventListener('click', e => {
  if (!e.target.closest('.search-wrap')) searchDrop.classList.remove('open');
});

// Canvas pointer, wheel zoom-around-cursor, and keyboard bindings.
function worldXY(e) {
  const r = canvas.getBoundingClientRect();
  return [(e.clientX - r.left - W / 2) / cam.s - cam.x, (e.clientY - r.top - H / 2) / cam.s - cam.y];
}
function hitTest(x, y) {
  let best = null, bestD = Infinity;
  for (const n of nodes) {
    if (!isNodeVisible(n)) continue;
    const d = Math.hypot(n.x - x, n.y - y);
    if (d < displayRadius(n) + 6 / cam.s && d < bestD) { best = n; bestD = d; }
  }
  return best;
}

canvas.onpointerdown = e => {
  camTarget = null;
  const [x, y] = worldXY(e);
  dragging = hitTest(x, y);
  pointerStart = [e.clientX, e.clientY];
  lastPtr = [e.clientX, e.clientY];
  canvas.classList.add('grabbing');
  canvas.setPointerCapture(e.pointerId);
};
canvas.onpointermove = e => {
  const [x, y] = worldXY(e);
  if (lastPtr) {
    if (dragging) {
      dragging.x = x; dragging.y = y; dragging.vx = 0; dragging.vy = 0;
      morphT = 1;
      showHoverTip(null);
    } else {
      cam.x += (e.clientX - lastPtr[0]) / cam.s;
      cam.y += (e.clientY - lastPtr[1]) / cam.s;
    }
    lastPtr = [e.clientX, e.clientY];
    request();
  } else {
    const h = hitTest(x, y);
    if (h !== hovered) { hovered = h; request(); }
    canvas.classList.toggle('pointer', Boolean(h));
    showHoverTip(h, e.clientX, e.clientY);
  }
};
canvas.onpointerup = canvas.onpointercancel = e => {
  if (pointerStart) {
    const moved = Math.hypot(e.clientX - pointerStart[0], e.clientY - pointerStart[1]);
    if (moved < 5) {
      const [x, y] = worldXY(e);
      const target = hitTest(x, y);
      select(target);
    }
  }
  dragging = null; lastPtr = null; pointerStart = null;
  canvas.classList.remove('grabbing');
};
canvas.onpointerleave = () => { hovered = null; showHoverTip(null); canvas.classList.remove('pointer'); request(); };
canvas.ondblclick = () => { select(null); fit(false); };

function zoomAt(factor, clientX = null, clientY = null) {
  camTarget = null;
  const nextS = Math.max(0.18, Math.min(4.2, cam.s * factor));
  if (clientX !== null && clientY !== null) {
    const r = canvas.getBoundingClientRect();
    const mx = clientX - r.left - W / 2, my = clientY - r.top - H / 2;
    cam.x += mx / nextS - mx / cam.s;
    cam.y += my / nextS - my / cam.s;
  }
  cam.s = nextS;
  request();
}
canvas.addEventListener('wheel', e => {
  e.preventDefault();
  zoomAt(e.deltaY < 0 ? 1.14 : 0.88, e.clientX, e.clientY);
}, { passive: false });
canvas.onkeydown = e => {
  if (e.key === 'Escape') select(null);
  else if (e.key === '+' || e.key === '=') zoomAt(1.18);
  else if (e.key === '-') zoomAt(0.85);
  else if (e.key.startsWith('Arrow')) {
    const step = 28 / cam.s;
    if (e.key === 'ArrowLeft') cam.x += step;
    if (e.key === 'ArrowRight') cam.x -= step;
    if (e.key === 'ArrowUp') cam.y += step;
    if (e.key === 'ArrowDown') cam.y -= step;
    request();
  } else return;
  e.preventDefault();
};

// Wire up HUD & Dock controls.
document.querySelectorAll('#layoutSeg button').forEach(b => {
  b.onclick = () => applyLayout(b.dataset.layout, false);
});
$('evidenceToggle').onclick = () => {
  hideListedOnly = !hideListedOnly;
  syncToolbar();
  updateCounter();
  if (selected && !isNodeVisible(selected)) select(null);
  else if (selected) renderInspector(selected);
  else renderOverview();
  if (layoutMode === 'layered' || layoutMode === 'radial') applyLayout(layoutMode, false);
  else { alphaSim = Math.max(alphaSim, 0.45); request(); }
};
$('drawerToggle').onclick = () => {
  const closed = $('studio').classList.toggle('drawer-closed');
  $('drawerToggle').setAttribute('aria-pressed', String(!closed));
  $('drawer').inert = closed;
  setTimeout(resize, 230);
};
$('backBtn').onclick = () => { select(null); fit(false); };
$('zoomInBtn').onclick = () => zoomAt(1.22);
$('zoomOutBtn').onclick = () => zoomAt(0.82);
$('fitBtn').onclick = () => fit(false);
$('pulseBtn').onclick = () => { pulses = !pulses; syncToolbar(); request(); };
$('edgeLblBtn').onclick = () => { showEdgeLabels = !showEdgeLabels; syncToolbar(); request(); };
$('pauseBtn').onclick = () => {
  running = !running;
  if (running) alphaSim = Math.max(0.28, alphaSim);
  syncToolbar();
  request();
};

function resize() {
  const r = canvas.getBoundingClientRect();
  if (r.width < 20 || r.height < 20) return;
  const dpr = Math.min(devicePixelRatio || 1, 2);
  W = r.width; H = r.height;
  canvas.width = Math.round(W * dpr);
  canvas.height = Math.round(H * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  fit(true);
}

buildLegend();
updateCounter();
applyLayout(layoutMode, true);
resize();
renderOverview();
new ResizeObserver(resize).observe(canvas);
new IntersectionObserver(es => { visible = es[0].isIntersecting; if (visible) request(); }).observe(canvas);
document.addEventListener('visibilitychange', request);
motion.addEventListener('change', () => {
  if (motion.matches) { pulses = false; running = false; syncToolbar(); }
});
'''
