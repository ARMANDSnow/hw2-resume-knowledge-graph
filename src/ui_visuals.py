"""Self-contained, offline visualizations for the five-stage Streamlit app."""
from __future__ import annotations

import html
import json
import math
import re
from collections import Counter

from .ui_theme import NODE_COLORS, NODE_LABELS_ZH


def _safe_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")


_BASE = """
:root{color-scheme:light;--ink:#24332b;--muted:#52645b;--green:#235a46;--blue:#386889;--ochre:#8b5d18;--line:#dadfd8;--wash:#f3f5f0}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%}body{background:#faf9f6;color:var(--ink);font:14px/1.45 'Inter',-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif}
main{width:100%;height:100%;overflow:auto;background:white;border:1px solid var(--line);border-radius:8px;padding:16px}
h2,h3,p,figure{margin:0}h2{font-size:16px;line-height:1.35}h3{font-size:14px}
header,.toolbar{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}header{margin-bottom:14px}
.controls,.options{display:flex;align-items:center;flex-wrap:wrap;gap:6px}button,input,select{font:inherit;color:inherit}
button,select,input{border:1px solid #b8c6bb;border-radius:5px;background:#fff;min-height:32px;padding:4px 9px;font-size:12px}
button{cursor:pointer}button:hover{background:#edf2ec;border-color:#7a9685}button[aria-pressed=true]{background:var(--green);border-color:var(--green);color:#fff}
button:focus-visible,select:focus-visible,input:focus-visible,canvas:focus-visible,summary:focus-visible,[tabindex]:focus-visible{outline:3px solid #336a96;outline-offset:2px}
small,.muted{color:var(--muted);font-size:12px}code,.numeric{font:500 12px/1.4 'IBM Plex Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}
code{overflow-wrap:anywhere}.empty{color:var(--muted);padding:16px 0}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0}
@media(max-width:520px){main{padding:11px}header{margin-bottom:9px}button,select,input{min-height:34px}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.001ms!important;transition:none!important;scroll-behavior:auto!important}}
"""


def _document(title, content, css="", script=""):
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>{_BASE}{css}</style></head>'
            f'<body><main aria-label="{html.escape(title)}">{content}</main>'
            f'<script>{script}</script></body></html>')


def render_funnel_html(manifest: dict) -> str:
    counts = manifest.get("corpus_counts", {})
    if "pdf_files" not in counts or "eligible" not in manifest:
        return _document("样本筛选", '<p class="empty">尚无采集统计。</p>')
    total = counts["pdf_files"]
    dup_file, dup_text = (counts.get(k, 0) for k in ("duplicate_file", "duplicate_text"))
    eligible = manifest["eligible"]
    near = sum(len(g.get("excluded", [])) for g in manifest.get("near_duplicate_groups", []))
    splits = Counter(d.get("split") for d in manifest.get("documents", []))
    stages = [
        ("归档 PDF", total, "原始数据集"),
        ("哈希去重", total - dup_file - dup_text, f"文件重复 {dup_file:,} · 文本重复 {dup_text:,}"),
        ("样本筛选", eligible, "保留符合质量、段落与岗位范围的简历"),
        ("近重复过滤", eligible - near, f"排除 {near:,} 份近重复简历"),
        ("固定快照", splits["train"] + splits["test"], f'训练 {splits["train"]} · 测试 {splits["test"]}'),
    ]
    cards, streams, guides, stations = [], [], [], []
    half_widths = [28 * count / max(total, 1) for _, count, _ in stages]
    for i, (label, count, desc) in enumerate(stages):
        x = 100 + 200 * i
        guides.append(f'<path class="guide" d="M{x} 7V79"/>')
        stations.append(f'<g class="station" transform="translate({x} 46)">'
                        '<circle class="halo" r="10"/><circle class="pin" r="3.6"/></g>')
        cards.append(f'<li data-share="{count / max(total, 1):.2%}">'
                     f'<h3>{label}</h3><strong>{count:,}</strong><span>{desc}</span></li>')
        if i == len(stages) - 1:
            continue
        w, next_w = half_widths[i:i + 2]
        # Split the incoming band into a retained lower stream and an upper exit.
        top, middle, bottom = 46 - w, 46 + w - 2 * next_w, 46 + w
        end_top, end_bottom = 46 - next_w, 46 + next_w

        def curve(start_y, end_y):
            return f'M{x},{start_y:.2f} C{x+88},{start_y:.2f} {x+112},{end_y:.2f} {x+200},{end_y:.2f}'

        if w > next_w:
            exit_band = (f'M{x},{top:.2f} C{x+75},{top:.2f} {x+86},6 {x+153},6 '
                         f'C{x+95},9 {x+78},{middle:.2f} {x},{middle:.2f}Z')
            streams.append(f'<path fill="url(#exit-ink)" d="{exit_band}"/>')
        retained = (curve(middle, end_top) + f' L{x+200},{end_bottom:.2f} '
                    f'C{x+112},{end_bottom:.2f} {x+88},{bottom:.2f} {x},{bottom:.2f}Z')
        streams.append(f'<path fill="url(#river-ink)" d="{retained}"/>')
        for fraction in (.25, .5, .75):
            strand = curve(middle + 2 * next_w * fraction, end_top + 2 * next_w * fraction)
            streams.append(f'<path class="strand" d="{strand}"/>')
    chart = ('<svg class="flow" viewBox="0 0 1000 84" preserveAspectRatio="none" aria-hidden="true"><defs>'
             '<linearGradient id="river-ink" gradientUnits="userSpaceOnUse" x1="100" x2="900">'
             '<stop stop-color="#aecbb4"/><stop offset=".5" stop-color="#548772"/><stop offset="1" stop-color="#285c48"/></linearGradient>'
             '<linearGradient id="exit-ink"><stop stop-color="#d5c5a1"/><stop offset="1" stop-color="#e4d5b5" stop-opacity=".24"/></linearGradient>'
             '<clipPath id="sweep"><rect id="reveal" width="1000" height="84"/></clipPath>'
             '<g id="streams">' + ''.join(streams) + '</g></defs>' + ''.join(guides)
             + '<use href="#streams" opacity=".18"/><use href="#streams" clip-path="url(#sweep)"/>'
             + ''.join(stations) + '</svg>')
    css = """
main{display:flex;flex-direction:column;justify-content:center;padding:16px 20px}
header{margin-bottom:7px}#replay{display:inline-flex;gap:5px;align-items:center;color:var(--green);border-radius:18px;padding:3px 12px}
#replay svg{width:14px;height:14px}.flow{width:100%;height:76px;display:block;background:linear-gradient(#fafbf7,#f5f8f3);border-radius:6px 6px 0 0;flex:none}
.guide{stroke:#cdd8ca;stroke-width:1;stroke-dasharray:2 4}.strand{fill:none;stroke:#44745c;stroke-opacity:.48;stroke-width:.85;vector-effect:non-scaling-stroke}
.halo{fill:#518f70;opacity:0}.pin{fill:#fff;stroke:#638972;stroke-width:1.6}
.station.done .pin,.station.active .pin{fill:var(--green);stroke:white}.station.active .halo{opacity:.22;animation:breathe 1s ease-out infinite}
@keyframes breathe{from{transform:scale(.55);opacity:.36}to{transform:scale(1.35);opacity:0}}
ol{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));padding:0;list-style:none;margin:0;background:#fafbf8}
li{position:relative;min-width:0;padding:11px 10px 12px;border-top:2px solid #cbd9cc;transition:background .25s}
li+li{border-left:1px solid #dde5da}li.active{background:#e6f0e5}li.done,li.active{border-top-color:#638d71}
li strong{display:block;color:var(--green);font:650 clamp(22px,2.7vw,30px)/1.28 'Inter',system-ui,sans-serif;font-variant-numeric:tabular-nums;margin:3px 0}
li span,footer{font-size:12px;color:var(--muted)}footer{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:5px 10px;margin-top:9px}
.legend{display:flex;gap:12px}.legend span{display:inline-flex;align-items:center;gap:5px}.legend i{width:13px;height:3px;border-radius:3px;background:#63947b}.legend .exit{background:#c8b690}
#status{font-variant-numeric:tabular-nums}
@media(max-width:680px){main{padding:10px;justify-content:flex-start}header{margin-bottom:4px}.flow{height:39px}ol{display:block}
li,li+li{display:grid;align-items:center;grid-template-columns:70px 53px 1fr;gap:5px;padding:4px 6px;border:0;border-left:2px solid #d3dfd3;border-bottom:1px solid #e2e9df}
li.done,li.active{border-left-color:#638d71}li h3,li span{font-size:11px}li strong{font-size:17px;margin:0}footer{font-size:11px;margin-top:6px}.legend{gap:7px}}
"""
    script = """
const cards = [...document.querySelectorAll('li')], stations = [...document.querySelectorAll('.station')];
const reveal = document.querySelector('#reveal'), statusLine = document.querySelector('#status');
const motion = matchMedia('(prefers-reduced-motion: reduce)');
const last = cards.length - 1, stepTime = 850, endPause = 480;
let frame = 0, active = null;
function mark(index) {
  if (active === index) return;
  active = index;
  cards.forEach((card, i) => {
    for (const item of [card, stations[i]]) {
      item.classList.toggle('active', i === index);
      item.classList.toggle('done', index < 0 || i < index);
    }
  });
  const card = cards[index < 0 ? last : index];
  statusLine.textContent = card.querySelector('h3').textContent + ' · 留存 ' + card.dataset.share;
}
function finish() {
  cancelAnimationFrame(frame);
  reveal.setAttribute('width', 1000);
  mark(-1);
}
function play() {
  cancelAnimationFrame(frame);
  if (motion.matches || document.hidden) { finish(); return; }
  const start = performance.now();
  function draw(now) {
    const elapsed = now - start, index = Math.min(last, Math.floor(elapsed / stepTime));
    if (elapsed >= last * stepTime + endPause) { finish(); return; }
    mark(index);
    const t = Math.min(1, Math.max(0, (elapsed / stepTime - index - .18) / .82));
    const ease = t * t * (3 - 2 * t);
    reveal.setAttribute('width', 100 + 200 * Math.min(last, index + ease));
    frame = requestAnimationFrame(draw);
  }
  draw(start);
}
const observer = new IntersectionObserver(entries => {
  if (entries.some(entry => entry.isIntersecting)) { observer.disconnect(); play(); }
});
observer.observe(document.querySelector('.flow'));
document.querySelector('#replay').onclick = () => { observer.disconnect(); play(); };
document.addEventListener('visibilitychange', () => { if (document.hidden) finish(); });
motion.addEventListener('change', () => { if (motion.matches) finish(); });
"""
    final_share = stages[-1][1] / max(total, 1)
    content = ('<header><h2>样本筛选</h2><button id="replay" type="button">'
               '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">'
               '<path d="M3 6a5 5 0 1 1 .4 5M3 2.5V6h3.5"/></svg>重播筛选</button></header>'
               + chart + '<ol>' + ''.join(cards) + '</ol>'
               + '<footer><div class="legend"><span><i></i>保留</span><span><i class="exit"></i>筛出</span></div>'
               + f'<span id="status">固定快照 · 留存 {final_share:.2%}</span></footer>')
    return _document("样本筛选", content, css, script)


from .ui_graph import _build_graph_payload, render_force_graph_html  # noqa: E402,F401


def _esc(value):
    return html.escape(str(value), quote=True)


_REPLAY = """
const replay = () => {
  const panel=document.querySelector('main');
  panel.classList.remove('play');
  if(!matchMedia('(prefers-reduced-motion: reduce)').matches){
    void panel.offsetWidth;
    panel.classList.add('play');
  }
};
document.querySelector('#replay').addEventListener('click',replay);
"""


def render_disambiguation_animator_html(groups: list[dict]) -> str:
    if not groups:
        return _document("消岐证据", '<p class="empty">当前没有双边证据组。</p>')
    buttons, panels = [], []
    for index, group in enumerate(groups):
        surface = _esc(group["surface"])
        buttons.append(f'<button data-index="{index}" aria-controls="group-{index}" '
                       f'aria-pressed="{str(index == 0).lower()}">{surface}</button>')
        proofs, targets = [], []
        for position, sense in enumerate(group["senses"][:2], 1):
            target = _esc(sense["name"])
            label = _esc(sense["label"])
            targets.append(f'<div class="target"><small>{label}</small><b>{target}</b></div>')
            scores, components = [], []
            for name, values in sense.get("scores", {}).items():
                total = float(values.get("total", 0))
                scores.append(f'<div class="score"><span>{_esc(name)}</span>'
                              f'<meter min="0" max="1" value="{total}"></meter><code>{total:.3f}</code></div>')
                parts = ''.join(f'<td>{float(values.get(signal, 0)):.3f}</td>'
                                for signal in ("tfidf_cosine", "section_prior", "record_coherence"))
                components.append(f'<tr><th scope="row">{_esc(name)}</th>{parts}</tr>')
            breakdown = ('<details><summary>三项得分明细</summary><table><thead><tr><th>义项</th>'
                         '<th>词窗</th><th>段落</th><th>共现</th></tr></thead><tbody>'
                         + ''.join(components) + '</tbody></table></details>')
            proofs.append(f'<article><small>义项 {position} · {label}</small><h3>{target}</h3>'
                          f'<p class="edge"><code>{_esc(sense["edge_source"])} → '
                          f'{_esc(sense["edge_type"])} → {_esc(sense["node_id"])}</code></p>'
                          f'<blockquote>{_esc(sense.get("evidence_quote", ""))}</blockquote>'
                          f'<small>{_esc(sense["resume_id"])} · 第 {_esc(sense["page_num"])} 页</small>'
                          + ''.join(scores) + breakdown + '</article>')
        panels.append(f'<section id="group-{index}"' + (' hidden' if index else '') + '>'
                      + f'<figure><strong>{surface}</strong><svg viewBox="0 0 64 60" preserveAspectRatio="none" aria-hidden="true">'
                        '<path d="M0 30 H20 Q27 30 32 22 L43 10 H64 M20 30 Q27 30 32 38 L43 50 H64" '
                        'fill="none" stroke="#829a87" stroke-width="2"/></svg><div class="targets">'
                      + ''.join(targets) + '</div></figure><div class="proofs">' + ''.join(proofs) + '</div></section>')
    content = ('<header><div class="options" role="group" aria-label="选择同名词">'
               + ''.join(buttons) + '</div><button id="replay">重播分流</button></header>' + ''.join(panels))
    css = """
figure{display:grid;grid-template-columns:minmax(55px,20%) minmax(24px,11%) 1fr;align-items:center;background:#f5f7f2;padding:10px 14px;border-radius:5px}
figure strong{font-size:18px;color:var(--green);text-align:center}figure svg{width:100%;height:62px}.targets{display:grid;gap:5px}
.target{border-left:3px solid #386889;padding:2px 10px;background:#fff;display:flex;align-items:baseline;gap:8px;overflow-wrap:anywhere}.target:nth-child(2){border-color:#8b641d}
.proofs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));margin-top:14px;gap:16px}article{min-width:0}article+article{border-left:1px solid var(--line);padding-left:15px}article h3{overflow-wrap:anywhere}blockquote{margin:6px 0 1px;padding:7px 9px;border-left:2px solid #c5d3c4;background:#f6f7f4;color:#36473d;font-size:13px;overflow-wrap:anywhere}.edge{color:var(--blue);line-height:1.2;margin:3px 0}.score{display:grid;grid-template-columns:minmax(65px,1fr) minmax(35px,1fr) 44px;align-items:center;gap:5px;font-size:12px;overflow-wrap:anywhere}.score:first-of-type{margin-top:7px}.score meter{width:100%;accent-color:var(--green)}
.play .target{animation:branch 650ms ease-out both}.play .target:nth-child(2){animation-delay:100ms}@keyframes branch{from{opacity:.18;transform:translate(-12px,-2px)}to{opacity:1;transform:none}}
details{margin-top:8px;color:var(--muted);font-size:12px}summary{cursor:pointer}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{text-align:left;border-bottom:1px solid var(--line);padding:3px 4px}
@media(max-width:570px){.proofs{grid-template-columns:1fr;gap:10px}article+article{padding:8px 0 0;border:0;border-top:1px solid var(--line)}figure{padding:7px 5px}.target{gap:4px;flex-wrap:wrap}}
"""
    script = _REPLAY + """
const buttons=[...document.querySelectorAll('[data-index]')];
buttons.forEach((button,index)=>button.onclick=()=>{
  buttons.forEach((b,i)=>{const active=i===index;b.setAttribute('aria-pressed',active);
    document.getElementById('group-'+i).hidden=!active});
  replay();
});
"""
    return _document("消岐证据", content, css, script)


def render_coref_merge_animator_html(coref_audit: dict) -> str:
    aliases = []
    for group in coref_audit.get("cross_document_groups", [])[:6]:
        variants = group.get("aliases") or [e.get("alias") for e in group.get("examples", [])]
        names = ' / '.join(str(x) for x in dict.fromkeys(variants) if x)
        aliases.append(f'<li><span class="variant">{_esc(names)}</span><span class="arrow">→</span>'
                       f'<b>{_esc(group["canonical_name"])}</b></li>')
    controls = []
    for control in coref_audit.get("negative_controls", [])[:5]:
        left, right = control["names"][:2]
        controls.append(f'<li><b>{_esc(left)}</b><span class="guard">≠</span><b>{_esc(right)}</b>'
                        f'<small>相似度 {control.get("similarity", 0):.2f}</small></li>')
    before = coref_audit.get("nodes_before", 0)
    after = coref_audit.get("nodes_after", 0)
    content = (f'<header><div><h2>共指归并</h2><small>节点数 {before:,} → {after:,}</small></div>'
               '<button id="replay">重播归并</button></header><div class="ledger"><section><h3>异名归并</h3><ul>'
               + ''.join(aliases) + '</ul></section><section><h3>保留不同实体</h3><ul>'
               + ''.join(controls) + '</ul></section></div>')
    css = """
.ledger{display:grid;grid-template-columns:1.1fr 1fr;gap:20px}.ledger section{min-width:0}h3{color:var(--green)}ul{list-style:none;margin:5px 0 0;padding:0}li{display:flex;flex-wrap:wrap;align-items:baseline;gap:3px 7px;padding:5px 0;border-bottom:1px solid var(--line);font-size:12px;overflow-wrap:anywhere}li small{margin-left:auto;font-size:11px}.arrow{color:var(--green);font-weight:700}.guard{color:var(--ochre);font-weight:750}.variant{color:var(--muted)}
.play .variant{animation:merge 850ms ease-out both}.play .guard{animation:separate 700ms ease-out both}@keyframes merge{from{transform:translateX(-8px);opacity:.25}to{transform:none;opacity:1}}@keyframes separate{from{transform:scale(.5)}70%{transform:scale(1.4)}to{transform:none}}
@media(max-width:560px){.ledger{grid-template-columns:1fr;gap:12px}}
"""
    return _document("共指归并", content, css, _REPLAY)


def render_interactive_radar_html(series: list[dict], title: str = "四维能力雷达图", height: int = 360) -> str:
    dims = (("EDU", "教育"), ("EXP", "经历"), ("SKL", "技能"), ("POT", "潜力"))
    # The hue and line style both identify a candidate on overlapping polygons.
    palette = ["#246044", "#396988", "#925721", "#764d79"]
    dashes = ["none", "6 3", "2 3", "8 2 2 2"]
    def pt(axis, value):
        angle = math.pi * (axis / 2 - .5)
        return 185 + 91 * value / 100 * math.cos(angle), 122 + 91 * value / 100 * math.sin(angle)
    def points(values):
        return " ".join(f"{x:.2f},{y:.2f}" for x, y in (pt(i, v) for i, v in enumerate(values)))
    marks = []
    for value in (25, 50, 75, 100):
        marks.append(f'<polygon fill="none" stroke="#bfccbf" points="{points([value]*4)}"/>'
                     f'<text x="191" y="{pt(0,value)[1]+4:.1f}" fill="#52645b" font-size="10">{value}</text>')
    for i, (_, label) in enumerate(dims):
        x, y = pt(i, 100)
        tx, ty = pt(i, 121)
        anchor = ["middle", "start", "middle", "end"][i]
        marks.append(f'<line x1="185" y1="122" x2="{x}" y2="{y}" stroke="#c4d0c3"/>'
                     f'<text x="{tx}" y="{ty+4}" text-anchor="{anchor}" fill="#24332b" font-size="13">{label}</text>')
    buttons = []
    summary = []
    for i, candidate in enumerate(series):
        color = candidate.get("color") or palette[i % len(palette)]
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            color = palette[i % len(palette)]
        name = _esc(candidate["name"])
        vals = [candidate["scores"].get(dim, 0) for dim, _ in dims]
        grades = candidate.get("grades", {})
        info = " · ".join(f"{label} {v} {grades.get(dim,'')}" for (dim,label),v in zip(dims,vals))
        summary.append(info)
        marks.append(f'<g class="series" data-series="{i}"><title>{name} · {_esc(info)}</title>'
                     f'<polygon points="{points(vals)}" fill="{color}" fill-opacity=".08" stroke="{color}" '
                     f'stroke-width="2.6" stroke-dasharray="{dashes[i%len(dashes)]}"/>')
        for j, value in enumerate(vals):
            x, y = pt(j, value)
            marks.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.5" fill="{color}" stroke="#fff"><title>'
                         f'{name} · {dims[j][1]} {value} {grades.get(dims[j][0],"")}</title></circle>')
        marks.append("</g>")
        buttons.append(f'<button data-index="{i}" aria-pressed="false"><i style="background:{color}"></i>{name}</button>')
    content = (f'<h2>{_esc(title)}</h2><svg role="img" aria-label="{_esc(title)}，每个维度满分一百分" viewBox="0 0 370 248">'
               + ''.join(marks) + '</svg><div class="options">' + ''.join(buttons) + '</div>'
               + '<p id="detail" aria-live="polite"></p>')
    css = """
main{display:flex;flex-direction:column;align-items:stretch;gap:4px}svg{display:block;width:100%;min-height:115px;flex:1}
.options{justify-content:center}.options button{display:inline-flex;align-items:center;gap:5px}.options i{width:9px;height:9px;border-radius:50%;border:1px solid #fff8}
.series{transition:opacity .16s}.dim{opacity:.17}#detail{color:var(--muted);text-align:center;font-size:12px;min-height:17px}
"""
    script = 'const data=' + _safe_json(summary) + ';' + """
const legends=[...document.querySelectorAll('button')], sets=[...document.querySelectorAll('.series')];
let pinned=-1;
function show(i){sets.forEach((g,j)=>g.classList.toggle('dim',i>=0&&j!==i));
  document.querySelector('#detail').textContent=data[i]||(data.length===1?data[0]:'');}
legends.forEach((b,i)=>{
 b.onpointerenter=b.onfocus=()=>show(i);b.onpointerleave=b.onblur=()=>show(pinned);
 b.onclick=()=>{pinned=pinned===i?-1:i;legends.forEach((el,j)=>el.setAttribute('aria-pressed',j===pinned));show(pinned)};
});show(-1);
"""
    return _document(title, content, css+f"main{{height:min(100vh,{int(height)}px)}}", script)


def render_sync_morph_html(sync_report: dict) -> str:
    changes, anchors = sync_report.get("threshold_changes", []), sync_report.get("anchors", [])
    buttons, panels = [], []
    for mode in ("a", "b"):
        snapshot = sync_report["snapshot_" + mode]
        tag = mode.upper()
        buttons.append(f'<button data-mode="{mode}" aria-controls="data-{mode}" aria-pressed="{str(mode=="a").lower()}">'
                       f'快照 {tag} · {snapshot["train_size"]} 人</button>')
        rows = []
        for change in changes:
            a, b = change["threshold_a"], change["threshold_b"]
            value = a if mode == "a" else b
            maximum = max(a or 0, b or 0, .001)
            def fmt(number):
                return "停用" if number is None else f"{number:.3g}"
            rows.append(f'<li><b>{_esc(change["rule_id"])}</b><strong>{fmt(value)}</strong>'
                        f'<small>A {fmt(a)} → B {fmt(b)}</small><i><u style="width:{100*(value or 0)/maximum:.2f}%"></u></i></li>')
        candidates = []
        for candidate in anchors:
            cur = candidate[mode]
            cells = ''.join(f'<td>{cur["scores"][k]} <b>{_esc(cur["grades"][k])}</b></td>' for k in ("EDU","EXP","SKL","POT"))
            delta = "、".join(candidate.get("changed_hit_rules") or []) or ("等级边界变化" if candidate.get("changed") else "无变化")
            candidates.append(f'<tr><th>{_esc(candidate["resume_id"])}</th>{cells}</tr><tr><td colspan="5" class="delta">{_esc(delta)}</td></tr>')
        panels.append(f'<section id="data-{mode}"' + (' hidden' if mode == "b" else '') + '><div class="grid">'
                      f'<div><h3>发生变化的阈值 <small>{len(changes)} 条</small></h3><ul>{"".join(rows)}</ul></div>'
                      '<div><h3>固定候选人 <small>得分 / 等级</small></h3><table><thead><tr><th>简历</th>'
                      '<th>教育</th><th>经历</th><th>技能</th><th>潜力</th></tr></thead><tbody>'
                      + ''.join(candidates) + '</tbody></table></div></div></section>')
    content = ('<header><h2>训练快照对比</h2><div class="controls">' + ''.join(buttons)
               + '<button id="auto" aria-pressed="false">自动切换</button></div></header>' + ''.join(panels))
    css = """
.grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.25fr);gap:18px}.grid>div{min-width:0}
ul{margin:5px 0 0;padding:0;list-style:none}li{display:grid;grid-template-columns:1fr auto auto;gap:3px 9px;align-items:center;padding:4px 0}li b,th{font-size:12px}li strong{color:var(--green);font-variant-numeric:tabular-nums}li i{grid-column:1/-1;background:#e5ebe3;height:4px}li u{display:block;background:#5c8365;height:4px}
table{width:100%;border-collapse:collapse;text-align:left;margin-top:5px;table-layout:fixed}th,td{padding:4px 2px;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}th:first-child{width:35%}td{font-size:12px}thead th{color:var(--muted);border-bottom:1px solid var(--line)}td b{color:var(--green)}.delta{color:var(--muted);border-bottom:1px solid var(--line);font-size:11px}
@media(max-width:640px){.grid{grid-template-columns:1fr;gap:12px}}
"""
    script = """
const buttons=[...document.querySelectorAll('[data-mode]')],auto=document.querySelector('#auto');let mode='a',timer=null;
function set(m){mode=m;buttons.forEach(b=>{const on=b.dataset.mode===mode;b.setAttribute('aria-pressed',on);document.querySelector('#data-'+b.dataset.mode).hidden=!on})}
function stop(){clearInterval(timer);timer=null;auto.setAttribute('aria-pressed','false');auto.textContent='自动切换'}
buttons.forEach(b=>b.onclick=()=>{stop();set(b.dataset.mode)});
auto.onclick=()=>{if(timer){stop();return}auto.textContent='停止切换';auto.setAttribute('aria-pressed','true');
  const next=()=>set(mode==='a'?'b':'a');next();timer=setInterval(next,4000)};
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop()});
"""
    return _document("训练快照对比", content, css, script)
