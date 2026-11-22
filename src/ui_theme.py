"""Shared typography, colors and evidence markup for the resume workspace."""
from __future__ import annotations

import html

NODE_COLORS = {
    "Candidate": "#494640",
    "Skill": "#6A7E62",
    "WorkExperience": "#607E91",
    "Company": "#88758C",
    "Project": "#B66B4D",
    "Education": "#AE7980",
    "University": "#60817F",
    "JobTitle": "#96793F",
}

NODE_LABELS_ZH = {
    "Candidate": "简历（CV）",
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
  --bg:#faf9f5; --surface:#fffefa; --wash:#f1eee7; --line:#e3dfd5; --line-strong:#cfc8bb;
  --ink:#26231f; --ink-2:#605c55; --muted:#746e65; --accent:#bd5838; --accent-dark:#944325; --accent-soft:#f4e5dc;
  --serif:"Source Han Serif SC","Songti SC","Noto Serif CJK SC",STSong,Georgia,serif;
  --sans:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  --mono:ui-monospace,"SFMono-Regular",Menlo,monospace;
}
.stApp {background:var(--bg);color:var(--ink);font-family:var(--sans)}
[data-testid="stHeader"] {background:transparent;pointer-events:none}
[data-testid="stHeader"] button {pointer-events:auto}
[data-testid="stAppDeployButton"] {display:none}
[data-testid="stMainBlockContainer"] {max-width:1360px;padding:3.4rem clamp(1.5rem,4.8vw,5.4rem) 4.5rem}
[data-testid="stVerticalBlock"] {gap:.8rem}
[data-testid="stSidebar"] {background:#f2f0e9;border-right:1px solid var(--line)}
[data-testid="stSidebarHeader"] {height:2.3rem;min-height:2.3rem}
[data-testid="stSidebarUserContent"] {padding:1.1rem 1.15rem 1.5rem}
[data-testid="stVerticalBlock"].st-key-sidebar_body {gap:.35rem;min-height:calc(100dvh - 7.8rem)}
.st-key-sidebar_body > [data-testid="stLayoutWrapper"]:has(.st-key-connection_status) {margin-top:auto}
.st-key-sidebar_body a p:has(strong){font-size:.73rem;line-height:1.48;color:var(--muted)}
.st-key-sidebar_body a p strong{font-size:.88rem;color:var(--ink);font-weight:550}
.kg-brand {display:flex;align-items:center;gap:.72rem;margin:0 .52rem 1.8rem}
.kg-brand strong {display:block;font:600 1.22rem/1.3 var(--serif);color:var(--ink)}
.kg-brand small {font:500 .71rem var(--mono);letter-spacing:.04em;color:var(--muted)}
.kg-mark {width:37px;height:37px;background:var(--accent);border-radius:11px;position:relative;flex:none}
.kg-mark i {position:absolute;width:7px;height:7px;border:1.5px solid #fff6e9;background:var(--accent);border-radius:50%;z-index:1}
.kg-mark i:nth-child(1){left:7px;top:20px}.kg-mark i:nth-child(2){left:16px;top:8px}.kg-mark i:nth-child(3){left:24px;top:22px}
.kg-mark:before,.kg-mark:after{content:"";position:absolute;height:1.5px;background:#fff6e9;transform-origin:left center}
.kg-mark:before{left:11px;top:23px;width:16px;transform:rotate(-55deg)}.kg-mark:after{left:20px;top:12px;width:16px;transform:rotate(60deg)}
.kg-nav-heading,.kg-eyebrow,.kg-spec-label {display:flex;align-items:center;gap:9px;font:550 .74rem/1.5 var(--sans);letter-spacing:.06em}
.kg-nav-heading {color:var(--muted);margin:1.55rem .7rem .5rem}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] {border-radius:8px;gap:.68rem;min-height:41px;padding:.45rem .72rem;color:var(--ink-2)}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"][aria-current="page"] {background:var(--accent-soft);color:var(--accent-dark)}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover {background:#eae6dc}
.st-key-connection_status {margin-top:auto;border-top:1px solid var(--line);padding:.9rem .5rem 0}
.kg-status {display:flex;align-items:center;gap:7px;color:var(--ink-2);font-size:.77rem}
.kg-status:before,.kg-spec-label i {content:"";width:7px;height:7px;border-radius:50%;background:#597957;display:inline-block}
.kg-status.offline:before {background:#a67233}
.st-key-connection_status a {background:transparent;border:0;padding:0;font-size:.75rem;color:var(--muted)}
.kg-home-title,.kg-section {color:var(--ink)}
.kg-eyebrow{color:var(--accent-dark);margin-bottom:.8rem}
.kg-eyebrow span {width:23px;height:1px;background:var(--accent)}
.kg-home-title h1,.kg-section h1 {font:500 clamp(1.7rem,2.55vw,2.3rem)/1.28 var(--serif);letter-spacing:-.04em;margin:0;padding:0}
.kg-home-title h1 {font-size:clamp(2.05rem,3.7vw,3.6rem);line-height:1.22}
.kg-home-title em {color:var(--accent-dark);font-style:normal}
.kg-home-title p,.kg-section p {color:var(--ink-2);font:.91rem/1.75 var(--sans);margin:.76rem 0 .15rem}
.kg-home-title p{max-width:32em}
.kg-section{padding-bottom:1.1rem}
.st-key-specimen {border:1px solid var(--line);border-radius:12px;padding:1rem 1.15rem .6rem;background:#fffcf6;gap:.12rem;box-shadow:0 3px 12px #48301d06}
.kg-spec-label {color:var(--ink-2);font-size:.7rem}
.kg-spec-label i{background:var(--accent)}
.kg-spec-label span {margin-left:auto;font:500 .64rem var(--mono);color:var(--muted)}
.kg-specimen blockquote {font:italic 1.1rem/1.4 Georgia,var(--serif);color:#4b4238;margin:.8rem 0;padding:0;border:0}
.kg-trace {display:flex;align-items:center;gap:0;color:var(--muted);font:.72rem var(--sans)}
.kg-trace span,.kg-trace b {border:1px solid var(--line);background:#f8f6f0;padding:.2rem .45rem;border-radius:5px;font-weight:500}
.kg-trace i {width:23px;height:1px;background:var(--line-strong)}.kg-trace b {color:var(--accent-dark);background:var(--accent-soft);border-color:#e7cdbf}
.st-key-open_specimen button{color:var(--accent-dark);padding-left:0;min-height:27px}
.st-key-open_specimen button p{font-size:.74rem}
.kg-facts {padding-inline-start:0!important;display:flex;margin:1.25rem 0 .25rem;padding:.95rem 0;border-block:1px solid var(--line)}
.kg-facts div {flex:1;min-width:0;padding:0 1.25rem;border-left:1px solid var(--line)}
.kg-facts div:first-child{border:0;padding-left:0}
.kg-facts dt {font-size:.76rem;color:var(--muted);margin-bottom:.23rem}
.kg-facts dd {font:500 clamp(1.4rem,2.65vw,2.25rem)/1.12 var(--serif);font-variant-numeric:lining-nums tabular-nums;letter-spacing:-.03em;color:var(--ink);margin:0}
.stMarkdown h3,.stMarkdown h4,[data-testid="stHeadingWithActionElements"] h3,.stMarkdown h3.kg-subhead {font:550 1.09rem/1.45 var(--sans);color:var(--ink);padding:.75rem 0 .22rem;letter-spacing:0}
[data-testid="stWidgetLabel"] p {color:var(--ink-2);font-size:.81rem}
[data-testid="stCaptionContainer"] {color:var(--muted)}
[class*="st-key-flow_"] {position:relative;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:.85rem .8rem .75rem;gap:.25rem;transition:background .16s,border-color .16s}
[class*="st-key-flow_"]:hover,[class*="st-key-flow_"]:focus-within {border-color:#d4a48e;background:#fffaf4}
[class*="st-key-flow_"] a {position:static;padding:0;gap:.45rem;color:var(--ink)}
[class*="st-key-flow_"] a:hover {background:transparent}
[class*="st-key-flow_"] a:after {content:"";position:absolute;inset:0}
[class*="st-key-flow_"] [data-testid="stElementContainer"] {position:static}
[class*="st-key-flow_"] [data-testid="stIconMaterial"] {color:var(--accent-dark)}
.kg-flow-info {color:var(--ink-2);font:.82rem/1.55 var(--sans);pointer-events:none}
.kg-flow-info small {display:block;color:var(--muted);font-size:.7rem;margin-top:.7rem}
.stButton button,.stDownloadButton button,.stLinkButton a,[data-testid="stFormSubmitButton"] button {border-radius:8px}
[data-testid="stTextInputRootElement"],[data-baseweb="select"]>div {background:#fffefa}
.st-key-search_composer {background:var(--surface);border:1px solid var(--line-strong);border-radius:15px;padding:.8rem 1rem;box-shadow:0 4px 18px #392b1907}
.st-key-search_composer:focus-within {border-color:var(--accent)}
.st-key-search_composer [data-testid="stTextAreaRootElement"] {background:transparent;border:0;box-shadow:none}
.st-key-search_composer textarea {background:transparent;font:1rem/1.65 var(--sans);resize:vertical}
.st-key-search_examples button {border-radius:20px;background:transparent;min-height:30px;padding:.2rem .75rem}
.st-key-search_examples button p {font-size:.8rem}
:where(button,a,input,select,textarea,summary,[tabindex]):focus-visible {outline:2px solid var(--accent-dark)!important;outline-offset:2px}
[data-testid="stExpander"] details {background:transparent;border:0;border-top:1px solid var(--line);border-radius:0}
[data-testid="stExpander"] summary {padding:.65rem .15rem;color:var(--ink-2)}
[data-testid="stMetricValue"] {font:500 1.45rem var(--serif)}
.stTabs [role="tablist"]{gap:1.15rem;overflow-x:auto}.stTabs [role="tab"]{flex-shrink:0}
.kg-audit-list{padding:0;margin:0}.kg-audit-list div{display:flex;justify-content:space-between;gap:.5rem;border-bottom:1px solid var(--line);padding:.65rem 0}
.kg-audit-list dt{font-size:.85rem;color:var(--ink-2)}.kg-audit-list dd{margin:0;font:.86rem var(--mono)}
.qz-record-box {overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#fffdfa;border:1px solid var(--line);border-radius:9px;padding:1rem 1.2rem;color:var(--ink);font:1rem/1.65 Georgia,var(--serif)}
.qz-ent {padding:.03rem .16rem;border:1px solid;border-radius:4px;box-decoration-break:clone}.qz-ent-lbl {font:.68rem var(--sans);margin-left:.16rem}
.qz-quote {margin:.6rem 0;background:#f5f2eb;border-left:2px solid #b19b83;padding:.7rem 1rem}
.qz-quote blockquote {border:0;padding:0;margin:0;font:1rem/1.5 Georgia,var(--serif);color:var(--ink);overflow-wrap:anywhere}
.qz-quote figcaption {color:var(--muted);font:.72rem/1.5 var(--sans);margin-top:.45rem}
.qz-quote-meta {display:flex;align-items:center;gap:.45rem;flex-wrap:wrap;color:var(--ink-2);font-size:.88rem}
.qz-pill {border-radius:24px;background:var(--wash);color:var(--ink-2);padding:.18rem .6rem;font-size:.79rem}
.qz-pill.terra {background:var(--accent-soft);color:var(--accent-dark)}
.st-key-record_list {background:#f5f2eb;border-color:var(--line);padding:.5rem .65rem}
.st-key-stage_footer a {font-size:.85rem;color:var(--ink-2)}
@media(max-width:760px){
 [data-testid="stMainBlockContainer"]{padding:3.1rem 1.1rem 3rem}
 .kg-home-title h1 {font-size:2.2rem}.kg-home-title p,.kg-section p{font-size:.85rem}
 .kg-facts {flex-wrap:wrap;row-gap:.75rem;margin:.55rem 0}
 .kg-facts div {flex:1 0 42%;padding:0 .8rem}.kg-facts div:nth-child(odd){border:0;padding-left:0}
 .kg-facts:has(> div:nth-child(3):last-child) div{flex:1 1 0;padding:0 .55rem;border-left:1px solid var(--line)}
 .kg-facts:has(> div:nth-child(3):last-child) div:first-child{padding-left:0;border:0}
 .kg-section{padding-bottom:.3rem}.kg-specimen blockquote{font-size:.95rem}
 [class*="st-key-flow_"]{padding:.55rem .8rem}.kg-flow-info small {display:inline-block;margin:0 0 0 .6rem}
}
@media(prefers-reduced-motion:reduce){* {scroll-behavior:auto!important;transition:none!important}}
</style>
"""


def evidence_card_html(e: dict) -> str:
    rid = html.escape(str(e.get("resume_id", "")))
    page = html.escape(str(e.get("page_num", "?")))
    skill = e.get("skill")
    source = str(e.get("source") or "")
    cls = "project" if source == "project_verified" else "work" if source == "work_verified" else "listed"
    label = {"project_verified": "项目经历", "work_verified": "工作经历", "listed": "技能清单"}.get(source, source)
    meta = " · ".join(x for x in (rid, f"第 {page} 页", html.escape(label), html.escape(str(skill or ""))) if x)
    quote = html.escape(str(e.get("evidence_quote") or "尚无原文引文"))
    return (f'<figure class="qz-quote {cls}"><blockquote lang="en">{quote}</blockquote>'
            f'<figcaption>{meta}</figcaption></figure>')


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
