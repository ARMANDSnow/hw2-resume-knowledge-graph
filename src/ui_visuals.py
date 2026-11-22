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
    shades = ["#b4c9b6", "#95b39a", "#729980", "#527f62", "#366548"]
    cells, markers, bands = [], [], []
    for index, (label, count, desc) in enumerate(stages):
        share = count / max(total, 1)
        x = 100 + index * 200
        thickness = 50 * share
        cells.append(f'<li data-label="{label}" data-share="{share:.2%}"><h3>{label}</h3>'
                     f'<strong>{count:,}</strong><span>{desc}</span></li>')
        if index < len(stages) - 1:
            next_thickness = 50 * stages[index + 1][1] / max(total, 1)
            points = f'{x},{31-thickness/2:.2f} {x+200},{31-next_thickness/2:.2f} {x+200},{31+next_thickness/2:.2f} {x},{31+thickness/2:.2f}'
            bands.append(f'<polygon points="{points}" fill="{shades[index]}" opacity=".8"/>')
        markers.append(f'<circle cx="{x}" cy="31" r="4" fill="{shades[index]}" stroke="#315740" stroke-width="1.5"/>')
    chart = ('<svg class="ribbon" viewBox="0 0 1000 62" preserveAspectRatio="none" aria-hidden="true">'
             '<line x1="100" x2="900" y1="31" y2="31" stroke="#648771"/>'
             + ''.join(bands + markers) + '</svg>')
    css = """
main{display:flex;flex-direction:column;justify-content:center}header{margin-bottom:6px}.ribbon{display:block;height:56px;width:100%;flex:none}
ol{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));padding:0;list-style:none;margin:0}
li{min-width:0;padding:6px 10px 8px;border-top:2px solid #d3dfd1;transition:background-color .23s}li+li{border-left:1px solid var(--line)}
li.current{background:#e8f0e5;border-top-color:var(--green)}.ribbon circle.current{r:6;fill:var(--green)}
strong{display:block;font-variant-numeric:tabular-nums;font-size:clamp(21px,2.7vw,30px);font-weight:650;color:var(--green);margin:3px 0}
li span,#status{color:var(--muted);font-size:12px}#status{margin:7px 0 0;text-align:right;font-variant-numeric:tabular-nums}
@media(max-width:680px){main{justify-content:flex-start}header{margin-bottom:2px}.ribbon{height:20px}ol{display:block}li,li+li{padding:3px 1px;border:0;border-bottom:1px solid var(--line);display:grid;align-items:center;gap:3px 7px;grid-template-columns:76px 51px 1fr}li strong{font-size:17px;margin:0}li h3,li span{font-size:11px}#status{margin-top:3px}}
"""
    script = """
const stages=[...document.querySelectorAll('li')], dots=[...document.querySelectorAll('circle')],statusLine=document.getElementById('status');
let timer=null;
function show(i){
 stages.forEach((el,j)=>{el.classList.toggle('current',i===j);dots[j].classList.toggle('current',i===j)});
 statusLine.textContent=stages[i].dataset.label+' · 占原始语料 '+stages[i].dataset.share;
}
document.getElementById('replay').onclick=()=>{
 clearTimeout(timer);
 if(matchMedia('(prefers-reduced-motion: reduce)').matches){show(stages.length-1);return}
 const step=i=>{show(i);if(i+1<stages.length)timer=setTimeout(()=>step(i+1),850)};
 step(0);
};
document.addEventListener('visibilitychange',()=>{if(document.hidden){clearTimeout(timer);show(stages.length-1)}});
"""
    final_share = stages[-1][1] / max(total, 1)
    content = ('<header><h2>样本筛选</h2><button id="replay">重播筛选</button></header>' + chart
               + '<ol>' + ''.join(cells) + '</ol>'
               + f'<p id="status" role="status">固定快照 · 占原始语料 {final_share:.2%}</p>')
    return _document("样本筛选", content, css, script)


def _build_graph_payload(resolved_kg: dict, scope: str = "train", max_nodes: int = 160, focus_resume: str | None = None) -> dict:
    nodes_by_id = {n["id"]: n for n in resolved_kg.get("nodes", [])}
    edges = resolved_kg.get("edges", [])

    if focus_resume:
        rel_edges = [e for e in edges if e.get("properties", {}).get("resume_id") == focus_resume]
        node_ids = set()
        for e in rel_edges:
            node_ids.add(e["source"])
            node_ids.add(e["target"])
        node_ids.add(focus_resume)
    else:
        cand_ids = {
            n["id"]
            for n in resolved_kg.get("nodes", [])
            if n["label"] == "Candidate" and (scope == "all" or n.get("properties", {}).get("split") == scope)
        }
        rel_edges = [e for e in edges if e.get("properties", {}).get("resume_id") in cand_ids]
        deg = Counter()
        for e in rel_edges:
            deg[e["source"]] += 1
            deg[e["target"]] += 1

        # Preserve the less frequent entity types in the sampled view.
        by_label: dict[str, list[str]] = {}
        for nid in deg:
            if nid in nodes_by_id:
                by_label.setdefault(nodes_by_id[nid]["label"], []).append(nid)
        for lst in by_label.values():
            lst.sort(key=lambda nid: (-deg[nid], nid))

        quotas = {
            "Candidate": max(12, int(max_nodes * 0.16)),
            "Skill": max(24, int(max_nodes * 0.28)),
            "Company": max(12, int(max_nodes * 0.10)),
            "Project": max(12, int(max_nodes * 0.10)),
            "University": max(10, int(max_nodes * 0.08)),
            "JobTitle": max(12, int(max_nodes * 0.10)),
            "WorkExperience": max(12, int(max_nodes * 0.10)),
            "Education": max(8, int(max_nodes * 0.08)),
        }
        node_ids = set()
        for lbl, quota in quotas.items():
            node_ids.update(by_label.get(lbl, [])[:quota])
        # Fill up to max_nodes by highest degree
        if len(node_ids) < max_nodes:
            for nid, _ in deg.most_common():
                if nid in nodes_by_id:
                    node_ids.add(nid)
                if len(node_ids) >= max_nodes:
                    break
        rel_edges = [e for e in rel_edges if e["source"] in node_ids and e["target"] in node_ids]
        # Remove isolated nodes after filtering
        connected = set()
        for e in rel_edges:
            connected.add(e["source"])
            connected.add(e["target"])
        node_ids &= connected

    deg_final = Counter()
    dedup_edges = []
    seen_e = set()
    for e in rel_edges:
        k = (e["source"], e["target"], e["type"])
        if k in seen_e:
            continue
        seen_e.add(k)
        deg_final[e["source"]] += 1
        deg_final[e["target"]] += 1
        p = e.get("properties", {})
        dedup_edges.append({
            "source": e["source"],
            "target": e["target"],
            "type": e["type"],
            "resume_id": p.get("resume_id", ""),
            "page_num": p.get("page_num", ""),
            "source_kind": p.get("source", ""),
            "quote": (p.get("evidence_quote") or "")[:200],
        })

    out_nodes = []
    for nid in sorted(node_ids):
        n = nodes_by_id.get(nid)
        if not n:
            continue
        props = n.get("properties", {})
        raw_name = props.get("name") or props.get("title") or props.get("degree") or nid
        short = str(raw_name)
        if len(short) > 26:
            short = short[:24] + "…"
        out_nodes.append({
            "id": nid,
            "label": n["label"],
            "label_zh": NODE_LABELS_ZH.get(n["label"], n["label"]),
            "name": str(raw_name),
            "short": short,
            "color": NODE_COLORS.get(n["label"], "#94A3B8"),
            "degree": deg_final[nid],
            "aliases": props.get("aliases", [])[:8],
            "split": props.get("split", ""),
            "is_center": bool(focus_resume and nid == focus_resume),
        })

    return {
        "nodes": out_nodes,
        "edges": dedup_edges,
        "colors": NODE_COLORS,
        "labels_zh": NODE_LABELS_ZH,
        "focus_mode": bool(focus_resume),
    }


def render_force_graph_html(resolved_kg: dict, scope: str = "train", max_nodes: int = 160, focus_resume: str | None = None, height: int = 600) -> str:
    payload = _build_graph_payload(resolved_kg, scope=scope, max_nodes=max_nodes, focus_resume=focus_resume)
    title = "简历关联图" if focus_resume else f"{scope.upper()} · 图谱样本"
    content = f"""
<header><div><h2>{html.escape(title)}</h2><small id="counter"></small></div>
<div class="controls"><label class="sr-only" for="search">搜索节点</label><input id="search" type="search" placeholder="搜索技能、机构或简历">
<button id="pulseBtn" aria-pressed="false">关系流向</button><button id="pauseBtn">暂停布局</button>
<button id="reheatBtn">重排</button><button id="resetBtn">居中</button></div></header>
<div class="plot"><canvas id="g" aria-label="关系图，方向键移动，减号或加号缩放" tabindex="0"></canvas></div>
<aside><label for="nodepick">节点详情</label><select id="nodepick"><option value="">选择节点</option></select>
<div id="inspector" aria-live="polite"></div></aside>
<div class="legend" id="legend" role="group" aria-label="显示的实体类别"></div>"""
    css = """
main{padding:0;overflow:hidden;display:grid;grid-template-columns:minmax(0,1fr) minmax(165px,25%);grid-template-rows:auto minmax(0,1fr) auto}
header{grid-column:1/-1;border-bottom:1px solid var(--line);padding:10px 14px;margin:0}.controls input{width:150px;min-width:0}
.plot{position:relative;min-height:0;min-width:0;grid-row:2;background:#fbfcf9}canvas{width:100%;height:100%;display:block;touch-action:none;cursor:grab}
aside{grid-column:2;grid-row:2/4;border-left:1px solid var(--line);padding:12px;overflow:auto;min-width:0}
aside label{display:block;color:var(--green);font-weight:650}select{width:100%;margin:5px 0 10px}.ins-head,.ins-sub,.ins-rel{font:11px/1.5 ui-monospace,monospace;color:var(--muted);overflow-wrap:anywhere}.ins-name{font-size:15px;font-weight:650;overflow-wrap:anywhere}.ins-quote{font-size:12px;border-top:1px solid var(--line);margin-top:6px;padding-top:6px;overflow-wrap:anywhere}.ins-badge{padding:2px 5px;border-radius:3px}.hint{font-size:12px;color:var(--muted)}.legend{padding:6px 9px;border-top:1px solid var(--line);display:flex;flex-wrap:wrap;gap:4px}.leg-item{display:inline-flex;gap:5px;align-items:center;min-height:27px;padding:2px 6px}.leg-item[aria-pressed=true]{background:#f1f5ef;color:var(--ink);border-color:#a8b9ac}.leg-item.off{color:#67736a;text-decoration:line-through}.leg-item.off i{background:transparent!important}.leg-item i{width:9px;height:9px;border-radius:50%;border:1px solid currentColor}
@media(max-width:620px){main{grid-template-columns:1fr;grid-template-rows:auto minmax(90px,1fr) auto minmax(80px,22%)}header{padding:7px 9px;gap:4px}header h2{font-size:14px}.controls{gap:4px}.controls input{width:126px}.controls button{font-size:11px;padding:2px 6px}.legend{grid-row:3}.leg-item{font-size:11px;min-height:24px}aside{grid-column:1;grid-row:4;border-left:0;border-top:1px solid var(--line);padding:6px 9px}aside label{display:inline;margin-right:6px}aside select{width:min(65%,270px);margin:0 0 5px}}
"""
    script = "const RAW=" + _safe_json(payload) + ";\n" + _GRAPH_SCRIPT
    return _document(title, content, css + f"main{{height:min(100vh,{int(height)}px)}}", script)


_GRAPH_SCRIPT = r'''const $=id=>document.getElementById(id);
const canvas=$('g'), ctx=canvas.getContext('2d'), motion=matchMedia('(prefers-reduced-motion: reduce)');
const nodes=RAW.nodes.map((n,i)=>{
  const angle=i*2.39996, radius=n.is_center?0:22+Math.sqrt(i)*24;
  return {...n,x:radius*Math.cos(angle),y:radius*Math.sin(angle),r:n.is_center?12:Math.min(12,4+Math.sqrt(n.degree)*1.5),vx:0,vy:0};
});
const byId=new Map(nodes.map(n=>[n.id,n]));
const edges=RAW.edges.map((e,i)=>({...e,s:byId.get(e.source),t:byId.get(e.target),offset:(i*.381966)%1}));
const hiddenLabels=new Set(), links=new Map(nodes.map(n=>[n.id,[]]));
edges.forEach(e=>{links.get(e.s.id).push(e);links.get(e.t.id).push(e)});
let W=0,H=0, cam={x:0,y:0,s:.8}, running=!motion.matches, alphaSim=1, pulses=false, visible=true, frame=0;
let selected=null,hovered=null,dragging=null,last=null;
function request(){if(!frame&&visible&&!document.hidden)frame=requestAnimationFrame(draw)}
function fit(){
 const shown=nodes.filter(n=>!hiddenLabels.has(n.label));
 const xs=shown.map(n=>n.x),ys=shown.map(n=>n.y);
 const xmin=Math.min(0,...xs),xmax=Math.max(0,...xs),ymin=Math.min(0,...ys),ymax=Math.max(0,...ys);
 cam={x:-(xmin+xmax)/2,y:-(ymin+ymax)/2,s:Math.max(.18,Math.min(1.8,(W-45)/(xmax-xmin+40),(H-40)/(ymax-ymin+40)))};
 request();
}
function resize(){
 const r=canvas.getBoundingClientRect(),ratio=Math.min(devicePixelRatio||1,2);
 W=r.width;H=r.height;canvas.width=Math.round(W*ratio);canvas.height=Math.round(H*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);fit();
}
function note(tag,cls,txt){const el=document.createElement(tag);el.className=cls;el.textContent=txt;return el}
const inspector=$('inspector'), picker=$('nodepick'),search=$('search');
function select(n){
 selected=n;picker.value=n?n.id:'';inspector.replaceChildren();
 if(!n){inspector.append(note('p','hint','选择节点查看关系与原文。拖动图面平移，滚轮缩放。'));request();return}
 inspector.append(note('b','ins-head',n.label_zh+' · '+n.degree+' 条关联'),note('div','ins-name',n.name),note('code','ins-sub',n.id));
 if(n.aliases.length>1)inspector.append(note('p','ins-sub',n.aliases.join(' / ')));
 const rels=links.get(n.id);
 for(const e of rels.slice(0,6)){
  const other=e.s===n?e.t:e.s, box=note('div','ins-quote','');
  box.append(note('div','ins-rel',(e.s===n?'→ ':'← ')+other.short+' · '+e.type),
             note('small','muted',e.resume_id+' · 第 '+(e.page_num||'?')+' 页'),note('p','',e.quote||''));
  inspector.append(box);
 }
 request();
}
function options(){
 const term=search.value.trim().toLowerCase();
 const available=nodes.filter(n=>!hiddenLabels.has(n.label)&&(!term||(n.name+' '+n.id).toLowerCase().includes(term)));
 picker.replaceChildren(new Option(available.length?'选择节点':'没有匹配节点',''));
 for(const n of available)picker.add(new Option(n.label_zh+' · '+n.name,n.id));
 if(selected&&available.includes(selected))picker.value=selected.id;
 return available;
}
picker.onchange=()=>select(byId.get(picker.value)||null);
search.oninput=()=>{const matches=options();select(search.value.trim()?matches[0]||null:null)};
const counts={};
for(const n of nodes)counts[n.label]=(counts[n.label]||0)+1;
for(const label of Object.keys(counts)){
 const btn=note('button','leg-item',''),dot=document.createElement('i');dot.style.background=RAW.colors[label];
 btn.append(dot,document.createTextNode(RAW.labels_zh[label]+' '+counts[label]));btn.setAttribute('aria-pressed','true');
 btn.onclick=()=>{if(hiddenLabels.has(label))hiddenLabels.delete(label);else hiddenLabels.add(label);
  const on=!hiddenLabels.has(label);btn.classList.toggle('off',!on);btn.setAttribute('aria-pressed',String(on));
  if(selected?.label===label&&!on)select(null);hovered=null;options();request()};
 $('legend').append(btn);
}
$('counter').textContent=nodes.length+' 个节点 · '+edges.length+' 条关系';
function xy(e){const r=canvas.getBoundingClientRect();return [(e.clientX-r.left-W/2)/cam.s-cam.x,(e.clientY-r.top-H/2)/cam.s-cam.y]}
function hit(x,y){return nodes.find(n=>!hiddenLabels.has(n.label)&&Math.hypot(n.x-x,n.y-y)<n.r+4/cam.s)}
canvas.onpointerdown=e=>{const [x,y]=xy(e);dragging=hit(x,y);if(dragging)select(dragging);last=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId)};
canvas.onpointermove=e=>{const [x,y]=xy(e);
 if(last){if(dragging){dragging.x=x;dragging.y=y;dragging.vx=dragging.vy=0}else{cam.x+=(e.clientX-last[0])/cam.s;cam.y+=(e.clientY-last[1])/cam.s}last=[e.clientX,e.clientY]}
 else hovered=hit(x,y);request()};
canvas.onpointerleave=()=>{hovered=null;request()};canvas.onpointerup=canvas.onpointercancel=()=>{dragging=null;last=null};
function zoom(f){cam.s=Math.max(.16,Math.min(4,cam.s*f));request()}
canvas.addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY<0?1.12:.89)},{passive:false});
canvas.onkeydown=e=>{
 if(e.key==='Escape')select(null);
 else if(['+','=','-'].includes(e.key))zoom(e.key==='-'?.89:1.12);
 else if(e.key.startsWith('Arrow')){const d=22/cam.s;if(e.key==='ArrowLeft')cam.x+=d;if(e.key==='ArrowRight')cam.x-=d;if(e.key==='ArrowUp')cam.y+=d;if(e.key==='ArrowDown')cam.y-=d;request()}
 else return;e.preventDefault();
};
canvas.ondblclick=()=>select(null);
function motionButtons(){$('pauseBtn').textContent=running?'暂停布局':'继续布局';$('pauseBtn').setAttribute('aria-pressed',String(!running));$('pulseBtn').setAttribute('aria-pressed',String(pulses));request()}
$('pulseBtn').onclick=()=>{pulses=!pulses;motionButtons()};
$('pauseBtn').onclick=()=>{running=!running;if(running)alphaSim=Math.max(.18,alphaSim);else pulses=false;motionButtons()};
$('reheatBtn').onclick=()=>{nodes.forEach((n,i)=>{n.vx=Math.cos(i)*5;n.vy=Math.sin(i)*5});alphaSim=1;running=true;motionButtons()};
$('resetBtn').onclick=()=>{search.value='';options();select(null);fit()};
motion.addEventListener('change',()=>{if(motion.matches){pulses=false;running=false;motionButtons()}});
function stepPhysics() {
  if (!running || alphaSim < 0.008) return;
  const repulse = RAW.focus_mode ? 2400 : 1250;
  const springK = RAW.focus_mode ? 0.032 : 0.022;
  const targetLen = RAW.focus_mode ? 98 : 68;
  const gravity = 0.012;

  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i];
    if (hiddenLabels.has(a.label)) continue;
    // Center gravity
    a.vx -= a.x * gravity * alphaSim;
    a.vy -= a.y * gravity * alphaSim;
    for (let j = i + 1; j < nodes.length; j++) {
      const b = nodes[j];
      if (hiddenLabels.has(b.label)) continue;
      let dx = a.x - b.x, dy = a.y - b.y;
      let d2 = dx * dx + dy * dy + 25;
      if (d2 > 68000) continue;
      const f = (repulse / d2) * alphaSim;
      const inv = 1 / Math.sqrt(d2);
      const fx = dx * inv * f, fy = dy * inv * f;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }
  }
  for (let i = 0; i < edges.length; i++) {
    const e = edges[i];
    if (hiddenLabels.has(e.s.label) || hiddenLabels.has(e.t.label)) continue;
    const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const f = (dist - targetLen) * springK * alphaSim;
    const fx = (dx / dist) * f, fy = (dy / dist) * f;
    e.s.vx += fx; e.s.vy += fy;
    e.t.vx -= fx; e.t.vy -= fy;
  }
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i];
    if (n === dragging) continue;
    if (n.is_center) { n.x *= 0.85; n.y *= 0.85; n.vx = 0; n.vy = 0; continue; }
    n.vx *= 0.84; n.vy *= 0.84;
    n.x += Math.max(-14, Math.min(14, n.vx));
    n.y += Math.max(-14, Math.min(14, n.vy));
  }
  alphaSim *= 0.992;
}


function draw(now){
 frame=0;if(!visible||document.hidden)return;
 stepPhysics();ctx.clearRect(0,0,W,H);ctx.save();ctx.translate(W/2,H/2);ctx.scale(cam.s,cam.s);ctx.translate(cam.x,cam.y);
 const active=selected||hovered,near=new Set(active?[active.id]:[]);
 for(const e of edges){
  if(hiddenLabels.has(e.s.label)||hiddenLabels.has(e.t.label))continue;
  const link=active&&(e.s===active||e.t===active);if(link){near.add(e.s.id);near.add(e.t.id)}
  ctx.lineWidth=(link?1.7:.75)/cam.s;ctx.strokeStyle=link?'#62836d':active?'#e4e9e1':'#b2c2b3';
  ctx.beginPath();ctx.moveTo(e.s.x,e.s.y);ctx.lineTo(e.t.x,e.t.y);ctx.stroke();
  if(pulses&&(!active||link)){const t=(now/2700+e.offset)%1;ctx.beginPath();ctx.arc(e.s.x+(e.t.x-e.s.x)*t,e.s.y+(e.t.y-e.s.y)*t,2/cam.s,0,Math.PI*2);ctx.fillStyle='#235a46';ctx.fill()}
  if(link&&cam.s>1.1){ctx.fillStyle='#476153';ctx.font='10px monospace';ctx.textAlign='center';ctx.fillText(e.type,(e.s.x+e.t.x)/2,(e.s.y+e.t.y)/2-3)}
 }
 const labels=[];
 for(const n of nodes){
  if(hiddenLabels.has(n.label))continue;const dim=active&&!near.has(n.id);ctx.globalAlpha=dim?.32:1;
  ctx.beginPath();ctx.arc(n.x,n.y,n.r,0,Math.PI*2);ctx.fillStyle=n.color;ctx.fill();ctx.strokeStyle=n===active?'#182d21':'#fff';ctx.lineWidth=(n===active?2.5:1.1)/cam.s;ctx.stroke();
  if(!dim&&(n===active||n.is_center||(!active&&n.degree>=10)||cam.s>1.8||(active&&near.has(n.id)&&near.size<12)))labels.push(n);
  ctx.globalAlpha=1;
 }
 // Give the selected node and hubs first choice of an uncluttered label.
 labels.sort((a,b)=>Number(b===active)-Number(a===active)||Number(b.is_center)-Number(a.is_center)||b.degree-a.degree);
 const areas=[],font=11/cam.s;
 ctx.font='600 '+font+'px sans-serif';ctx.textAlign='center';ctx.lineWidth=3/cam.s;
 for(const n of labels){
  const half=ctx.measureText(n.short).width/2+3/cam.s,y=n.y+n.r+font;
  const box={left:n.x-half,right:n.x+half,top:y-font-2/cam.s,bottom:y+3/cam.s};
  if(areas.some(a=>a.left<box.right&&a.right>box.left&&a.top<box.bottom&&a.bottom>box.top))continue;
  areas.push(box);ctx.strokeStyle='#fbfcf9';ctx.strokeText(n.short,n.x,y);ctx.fillStyle='#24332b';ctx.fillText(n.short,n.x,y);
 }
 ctx.restore();if((running&&alphaSim>=.008)||pulses)request();
}
resize();new ResizeObserver(resize).observe(canvas.parentElement);
new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(visible)request()}).observe(canvas);
document.addEventListener('visibilitychange',request);options();select(nodes.find(n=>n.is_center)||null);motionButtons();
'''


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
