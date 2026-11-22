"""Quartz x LightRAG warm editorial light theme & HTML card components."""
from __future__ import annotations

import html

NODE_COLORS = {
    "Candidate": "#284B63",       # Quartz signature deep slate-teal
    "Skill": "#247A6E",           # Botanical sage-teal
    "WorkExperience": "#446699",  # Steel indigo
    "Company": "#765094",         # Muted editorial plum
    "Project": "#C45B38",         # Warm terracotta (harmonized with HW1 pick!)
    "Education": "#B54B63",       # Dusty rose
    "University": "#2D7888",      # Deep lagoon
    "JobTitle": "#B07824",        # Warm ochre
}

NODE_LABELS_ZH = {
    "Candidate": "候选人",
    "Skill": "技能",
    "WorkExperience": "工作经历",
    "Company": "企业",
    "Project": "项目",
    "Education": "教育背景",
    "University": "院校",
    "JobTitle": "岗位头衔",
}

ENTITY_COLORS = {
    "skill": ("#1B5E54", "#E6F4F1", "#9FD3C9"),
    "company": ("#5B3A75", "#F3EDF8", "#D3BEE6"),
    "university": ("#215E6B", "#E8F4F6", "#A7D4DC"),
    "degree": ("#8F364B", "#FAECF0", "#E4B2BE"),
    "major": ("#8C3B68", "#F9EDF4", "#E2B5CE"),
    "job title": ("#8A5C17", "#FBF3E4", "#E4C892"),
    "project": ("#9A4225", "#FCF0EB", "#E8B7A5"),
    "date range": ("#33517D", "#ECF1F8", "#B5C8E3"),
    "person": ("#1E3B4E", "#EAF1F5", "#ACC6D6"),
    "certification": ("#65428A", "#F2EDFA", "#CCB8E8"),
}


def theme_css() -> str:
    return """
<style>
:root {
  color-scheme: light;
  --bg-paper:#faf9f6; --bg-card:#fff; --bg-subtle:#eff3ed; --border-hair:#d8dfd6;
  --border-strong:#aebbb0; --ink-primary:#23352a; --ink-body:#394a3f; --ink-muted:#5b6b60;
  --accent-slate:#345c73; --accent-teal:#235a46; --accent-terra:#90562e;
  --serif:"Source Han Serif SC","Songti SC",STSong,"Hiragino Mincho ProN",Georgia,serif;
  --sans:Inter,-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}
.stApp { background:var(--bg-paper); color:var(--ink-primary); font-family:var(--sans); }
[data-testid="stHeader"]{background:transparent;pointer-events:none}
[data-testid="stHeader"] button {pointer-events:auto}
[data-testid="stAppDeployButton"] {display:none}
[data-testid="stMainBlockContainer"] {max-width:1512px;padding:2.6rem clamp(1.35rem,4.1vw,5.2rem) 5rem}
[data-testid="stVerticalBlock"] {gap:.85rem}
[data-testid="stSidebar"] {background:#eff2eb;border-right:1px solid var(--border-hair)}
[data-testid="stSidebarUserContent"] {padding:1.65rem 1.25rem 2rem}
[data-testid="stSidebarHeader"] {min-height:1.75rem}
[data-testid="stSidebar"] hr {margin:.55rem 0;border-color:#d2dbcf}
[data-testid="stWidgetLabel"] p {font-size:.83rem;font-weight:600;color:var(--ink-body)}
[data-testid="stCaptionContainer"] {color:var(--ink-muted)}
[data-testid="stMetric"] {border-bottom:1px solid var(--border-hair);padding:.4rem 0 .65rem}
[data-testid="stMetricValue"] {font:600 clamp(1.1rem,2vw,1.65rem)/1.3 var(--sans);color:var(--ink-primary)}
[data-testid="stMetricValue"] > div {overflow-wrap:anywhere;white-space:normal}
[data-testid="stExpander"] {background:#fff;border:1px solid var(--border-hair);border-radius:8px}
[data-testid="stExpander"] summary p {font-size:.86rem}
[data-baseweb="select"]>div {background:white;border-color:var(--border-hair)}
[data-baseweb="popover"],[role="listbox"] {color:var(--ink-primary)}
.stButton button,.stDownloadButton button,.stLinkButton a {border-radius:7px;border-color:var(--border-hair);font-weight:600}
:where(button,a,input,select,textarea,summary,[tabindex]):focus-visible {outline:3px solid #4b8568!important;outline-offset:2px}
.stTabs [role="tablist"] {border-bottom:1px solid var(--border-hair);gap:clamp(.5rem,2.1vw,2.1rem);overflow-x:auto}
.stTabs [role="tab"] {padding:0 .15rem;height:44px;color:var(--ink-muted);flex-shrink:0}
.stTabs [role="tab"] p {font-size:.88rem;font-weight:600}
.stTabs [role="tab"][aria-selected="true"] {color:var(--accent-teal);box-shadow:inset 0 -3px var(--accent-teal)}
.stTabs [data-baseweb="tab-highlight"],.stTabs [data-baseweb="tab-border"] {display:none}
.stTabs [role="tabpanel"] {padding-top:.75rem}
.kg-brand {display:flex;align-items:center;gap:.7rem;margin-bottom:1.2rem}
.kg-brand b {font:700 1.15rem var(--serif);color:var(--ink-primary)}
.kg-brand small,.kg-label {display:block;color:var(--ink-muted);font-size:.77rem;line-height:1.6}
.kg-mark {width:36px;height:38px;background:#254e3e;border-radius:8px;position:relative;flex:none}
.kg-mark i {position:absolute;width:6px;height:6px;border:1.5px solid #f7f4e8;border-radius:50%;background:#254e3e;z-index:1}
.kg-mark i:nth-child(1){left:7px;top:20px}.kg-mark i:nth-child(2){left:17px;top:9px}.kg-mark i:nth-child(3){left:23px;top:22px}
.kg-mark::before,.kg-mark::after {content:"";position:absolute;height:1.3px;background:#dce9ce;transform-origin:left center}
.kg-mark::before {left:10px;top:23px;width:15px;transform:rotate(-48deg)}
.kg-mark::after {left:20px;top:12px;width:14px;transform:rotate(64deg)}
.kg-split {display:flex;height:6px;overflow:hidden;border-radius:6px;background:#e0e5dc;margin:.6rem 0}
.kg-split i {background:#527e63}.kg-split i+i{background:#af7952}
.kg-split-legend {display:flex;justify-content:space-between;font-size:.8rem;color:var(--ink-body);margin-bottom:.75rem}
.kg-side-stats {display:grid;gap:.55rem;margin:.65rem 0 1rem}
.kg-side-stats div {display:flex;justify-content:space-between;font-size:.79rem;color:var(--ink-muted)}
.kg-side-stats strong {font-family:var(--mono);color:var(--ink-body);font-weight:500}
.kg-mast {padding:0 0 .25rem}
.kg-mast-row {display:flex;align-items:center;justify-content:space-between;gap:1rem}
.kg-mast h1 {font:700 clamp(1.9rem,3.1vw,3.05rem)/1.22 var(--serif);letter-spacing:-.035em;color:var(--ink-primary);padding:.2rem 0 .45rem;margin:0}
.kg-byline {color:var(--ink-muted);font-size:.81rem;margin-bottom:1.15rem}
.kg-status {display:inline-flex;align-items:center;gap:.44rem;background:#e7efe5;color:#28543b;border:1px solid #cfdccc;
  padding:.28rem .63rem;font-size:.74rem;white-space:nowrap;border-radius:5px}
.kg-status::before {content:"";width:7px;height:7px;background:#3e7854;border-radius:100%}
.kg-status.offline {background:#faf0de;color:#78521c;border-color:#e6d4b8}.kg-status.offline::before {background:#9c672a}
.kg-facts {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-block:1px solid var(--border-hair);
  margin:.25rem 0 .18rem;padding:.78rem 0}
.kg-facts div {padding:0 1.1rem;border-left:1px solid var(--border-hair)}.kg-facts div:first-child{border:0;padding-left:0}
.kg-facts dt {font-size:.76rem;color:var(--ink-muted);margin-bottom:.15rem}
.kg-facts dd {font:600 clamp(1.25rem,2vw,1.8rem)/1.2 var(--sans);letter-spacing:-.04em;font-variant-numeric:tabular-nums;color:var(--ink-primary);margin:0}
.kg-facts dd small {font:400 .74rem var(--sans);color:var(--ink-muted);letter-spacing:0;margin-left:.35rem}
.kg-section {margin:.45rem 0 .3rem}
.kg-section h2 {font:700 clamp(1.45rem,2.3vw,2rem)/1.35 var(--serif);letter-spacing:-.025em;color:var(--ink-primary);margin:0;padding:0}
.kg-section p {font:.88rem/1.65 var(--sans);color:var(--ink-muted);margin:.25rem 0 0}
.kg-subhead {display:flex;align-items:center;gap:.45rem;flex-wrap:wrap;
  font:650 1.06rem/1.55 var(--sans);color:var(--ink-primary);margin:.65rem 0 .25rem}
.qz-card,.qz-rule-card,.qz-kpi {background:white;border:1px solid var(--border-hair);border-radius:9px;padding:.9rem 1rem;overflow-wrap:anywhere}
.qz-callout,.qz-quote {background:#f1f4ee;border-left:3px solid #618069;padding:.75rem 1rem;border-radius:0 6px 6px 0;margin:.3rem 0 .6rem}
.qz-quote.project,.qz-callout.terra {border-left-color:#a37248}
.qz-quote-meta {display:flex;align-items:center;gap:.35rem;flex-wrap:wrap;margin-bottom:.4rem}
.qz-quote-text {font:1rem/1.65 Georgia,var(--serif);color:var(--ink-body);overflow-wrap:anywhere}
.qz-pill {display:inline-block;padding:.15rem .42rem;margin:.08rem .09rem .08rem 0;border-radius:4px;
  background:#ecede8;color:#435345;font:500 .73rem/1.5 var(--sans);overflow-wrap:anywhere}
.qz-pill.slate {background:#e8eff3;color:#345970}
.qz-pill.teal {background:#e4eee5;color:#285941}
.qz-pill.terra {background:#f6ecde;color:#83532b}
.qz-pill.rose {background:#f6e9e7;color:#894841}
.qz-pill.plum {background:#eeeaf2;color:#674f77}
.qz-record-box {overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#fffefa;
  border:1px solid var(--border-hair);border-radius:8px;padding:1.1rem 1.3rem;color:#354139;font:.94rem/1.72 var(--mono)}
.qz-ent {padding:.03rem .14rem;border:1px solid;border-radius:3px;box-decoration-break:clone}
.qz-ent-lbl {font:600 .68rem var(--sans);margin-left:.15rem}
.qz-bar-track {background:#e5eae3;height:5px;border-radius:5px;margin:.55rem 0;overflow:hidden}
.qz-bar-fill {height:100%;background:#59836a}
.qz-grade {background:#e6eee6;color:#2e5138;font-weight:700;padding:.14rem .42rem;border-radius:4px}
.qz-kpi-label {color:var(--ink-muted);font-size:.78rem}.qz-kpi-val{font:600 1.4rem var(--sans);color:var(--ink-primary)}
.stMarkdown h3.kg-subhead {font:650 1.09rem/1.5 var(--sans);padding:0;margin:.6rem 0 .2rem}
.kg-audit-list {margin:0;padding:0}.kg-audit-list div {display:flex;justify-content:space-between;gap:.6rem;border-bottom:1px solid var(--border-hair);padding:.48rem 0}
.kg-audit-list dt {color:var(--ink-muted);font-size:.84rem}.kg-audit-list dd {margin:0;color:var(--ink-primary);font:600 .9rem var(--mono)}
@media(max-width:768px){
 [data-testid="stMainBlockContainer"]{padding:3rem 1rem 3.5rem}
 .kg-mast-row {align-items:flex-start}.kg-mast h1{font-size:1.85rem}
 .kg-facts {grid-template-columns:repeat(2,minmax(0,1fr));row-gap:.55rem}
 .kg-facts div:nth-child(odd){border:0;padding-left:0}.kg-facts dd small{font-size:.68rem}
 .kg-status{font-size:.67rem}.kg-section p{font-size:.82rem}
}
@media(prefers-reduced-motion:reduce){.stTabs * {scroll-behavior:auto!important;transition:none!important}}
</style>
"""


def hero_banner_html(stats: dict, acceptance: dict, online: bool) -> str:
    counts = stats.get("all", {})
    checks = acceptance.get("checks", {})
    verified = checks.get("AC-3", {}).get("metrics", {}).get("quote_valid_rate")
    rules = checks.get("AC-6", {}).get("metrics", {}).get("live_rules")
    facts = [
        ("领域实体", counts.get("node_count"), "个节点"),
        ("图谱关系", counts.get("relationship_count"), "条关系"),
        ("原文引文核验率", f"{verified:.0%}" if verified is not None else None, ""),
        ("评估规则", rules, "条"),
    ]
    cells = []
    for label, value, unit in facts:
        display = f"{value:,}" if isinstance(value, int) else str(value) if value is not None else "—"
        cells.append(f"<div><dt>{label}</dt><dd>{display}<small>{unit}</small></dd></div>")
    status = "Neo4j 已连接" if online else "离线快照"
    variant = "" if online else "offline"
    return (
        '<header class="kg-mast"><div class="kg-mast-row"><h1>简历知识图谱</h1>'
        f'<span class="kg-status {variant}">{status}</span></div>'
        '<div class="kg-byline">智能信息系统建模　/　作业 02　·　丁宇轩</div>'
        f'<dl class="kg-facts">{"".join(cells)}</dl></header>'
    )


def evidence_card_html(e: dict) -> str:
    rid = html.escape(str(e.get("resume_id", "")))
    page = html.escape(str(e.get("page_num", "?")))
    skill = e.get("skill")
    source = str(e.get("source") or "")
    cls = "project" if source == "project_verified" else "work" if source == "work_verified" else "listed"
    pills = [f'<span class="qz-pill slate">{rid}</span>', f'<span class="qz-pill">PDF p.{page}</span>']
    if skill:
        pills.append(f'<span class="qz-pill teal">{html.escape(str(skill))}</span>')
    if source:
        s_cls = "terra" if source == "project_verified" else "teal" if source == "work_verified" else ""
        s_label = {"project_verified": "项目实证", "work_verified": "任职实证", "listed": "清单列举"}.get(source, source)
        pills.append(f'<span class="qz-pill {s_cls}">{html.escape(s_label)}</span>')
    quote = html.escape(str(e.get("evidence_quote") or "缺少引文"))
    return f"""
<div class="qz-quote {cls}">
  <div class="qz-quote-meta">{"".join(pills)}</div>
  <div class="qz-quote-text">“{quote}”</div>
</div>
"""


def highlighted_record_html(record: dict) -> str:
    text = record.get("record_text", "")
    entities = record.get("entities", [])
    spans = []
    for ent in sorted(entities, key=lambda x: (x.get("start", 0), -(x.get("end", 0) - x.get("start", 0)))):
        s, e = ent.get("start"), ent.get("end")
        if not isinstance(s, int) or not isinstance(e, int) or s < 0 or e <= s or e > len(text):
            continue
        if spans and s < spans[-1][1]:
            continue
        spans.append((s, e, str(ent.get("label", "entity")), float(ent.get("score", 0.0))))
    parts = []
    pos = 0
    for s, e, label, score in spans:
        if s > pos:
            parts.append(html.escape(text[pos:s]))
        fg, bg, bd = ENTITY_COLORS.get(label.lower(), ("#284B63", "#EAF1F5", "#B8D0DF"))
        parts.append(
            f'<span class="qz-ent" title="{html.escape(label)} (score {score:.2f})" '
            f'style="color:{fg};background:{bg};border-color:{bd};">'
            f'{html.escape(text[s:e])}<span class="qz-ent-lbl">{html.escape(label)}</span></span>'
        )
        pos = e
    if pos < len(text):
        parts.append(html.escape(text[pos:]))
    return f'<div class="qz-record-box">{"".join(parts)}</div>'
