"""运行方式：.venv/bin/streamlit run app.py"""
from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd
import streamlit as st
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired

from src.stage3_neo4j import get_driver, graph_stats
from src.stage4_rules import group_rule_evidence
from src.stage5_query import (
    DEGREE_NAMES,
    DIMS,
    MAIN_QUERY,
    ZERO_QUERY,
    comparison_conclusion,
    comparison_rows,
    execute_query,
    recommendation,
)
from src.ui_theme import evidence_card_html, hero_banner_html, highlighted_record_html, theme_css
from src.ui_visuals import (
    render_coref_merge_animator_html,
    render_disambiguation_animator_html,
    render_force_graph_html,
    render_funnel_html,
    render_interactive_radar_html,
    render_sync_morph_html,
)

ROOT = Path(__file__).resolve().parent
PROCESSED = ROOT / "data/processed"

st.set_page_config(
    page_title="简历知识图谱 · 研究工作台",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="auto",
)


@st.cache_data(show_spinner=False)
def _read_json(path: str, modified: int):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def artifact(path: Path) -> dict:
    if not path.exists():
        return {}
    return _read_json(str(path), path.stat().st_mtime_ns)


@st.cache_resource(show_spinner=False)
def connection():
    return get_driver()


def render_canvas(markup: str, height: int):
    if hasattr(st, "iframe"):
        st.iframe(markup, width="stretch", height=height)
    else:
        import streamlit.components.v1 as components

        components.html(markup, height=height, scrolling=False)


def section_header(title: str, subtitle: str = ""):
    sub = f'<p>{html.escape(subtitle)}</p>' if subtitle else ""
    st.markdown(f'<header class="kg-section"><h2>{html.escape(title)}</h2>{sub}</header>',
                unsafe_allow_html=True)


def read_pdf_link(doc: dict, key: str):
    path = ROOT / doc["pdf_path"]
    if path.is_file():
        st.download_button(
            "下载原始 PDF",
            path.read_bytes(),
            icon=":material/download:",
            file_name=path.name,
            mime="application/pdf",
            key=key,
        )



def show_evidence_card(e: dict):
    st.markdown(evidence_card_html(e), unsafe_allow_html=True)


def collection_tab(doc: dict | None, manifest: dict):
    if not manifest or not doc:
        st.info("运行采集阶段后即可浏览固定快照。")
        return
    total = manifest.get("corpus_counts", {}).get("pdf_files")
    section_header("数据采集与去重", f"从 {total:,} 份英文简历中筛选研究样本，保留逐页原文以供核查。" if total else "逐页查看原文，核对样本的去重与划分。")
    render_canvas(render_funnel_html(manifest), height=290)

    left, right = st.columns([1.6, 1], gap="large")
    with left:
        st.markdown('<h3 class="kg-subhead">原文阅读</h3>', unsafe_allow_html=True)
        pages = doc["pages"]
        page_col, download_col = st.columns([1.2, 1], vertical_alignment="bottom")
        page_index = page_col.selectbox(
            "简历页码", range(len(pages)),
            format_func=lambda i: f"第 {pages[i]['page_num']} 页 / 共 {len(pages)} 页",
            key="tab1_page_sel",
        )
        with download_col:
            read_pdf_link(doc, f"collect-pdf-{doc['resume_id']}")
        page = pages[page_index]
        st.caption(f"{doc['resume_id']}　·　{len(page['text']):,} 字符　·　全文偏移 {page['char_start']:,}–{page['char_end']:,}")
        st.markdown(
            f'<div class="qz-record-box" tabindex="0" aria-label="本页简历原文" style="max-height:385px">{html.escape(page["text"])}</div>',
            unsafe_allow_html=True,
        )
    with right:
        st.markdown('<h3 class="kg-subhead">去重审计</h3>', unsafe_allow_html=True)
        counts = manifest.get("corpus_counts", {})
        rows = [
            ("文件内容相同", counts.get("duplicate_file", 0)),
            ("规范化文本相同", counts.get("duplicate_text", 0)),
            ("近重复版本", sum(len(g["excluded"]) for g in manifest.get("near_duplicate_groups", []))),
        ]
        entries = "".join(f"<div><dt>{label}</dt><dd>{value:,} 份</dd></div>" for label, value in rows)
        st.markdown(f'<dl class="kg-audit-list">{entries}</dl>', unsafe_allow_html=True)
        with st.expander("查看快照与文件指纹"):
            for label, value in (("队列 SHA-256", manifest["cohort_hash"]), ("文件 SHA-256", doc["file_hash"]), ("文本 SHA-256", doc["text_hash"])):
                st.caption(label)
                st.code(value, language=None, wrap_lines=True)
            st.caption(doc["pdf_path"])
        for label, filename in (("12 份试点复核记录", "pilot_review_notes.md"), ("试点逐记录明细", "pilot_audit.md")):
            path = PROCESSED / filename
            if path.exists():
                with st.expander(label):
                    st.markdown(path.read_text(encoding="utf-8"))


def extraction_tab(doc: dict | None, resolved: dict):
    section_header(
        "从简历记录核对图谱关系",
        "选择一段经历，核对识别出的实体、关系和 PDF 原句。",
    )
    data = artifact(PROCESSED / "extractions.json")
    if not data or not doc:
        st.info("请先运行阶段二以查看结构化抽取结果。")
        return

    rid = doc["resume_id"]
    extracted = next((d for d in data["documents"] if d["resume_id"] == rid), None)
    if not extracted:
        st.info("当前简历尚无抽取记录。")
        return

    records = extracted["records"]
    edges = [e for e in data["edges"] if e["properties"].get("resume_id") == rid]

    st.caption(f"当前简历　{rid}")
    c1, c2, c3 = st.columns(3)
    c1.metric("抽取记录", len(records))
    c2.metric("实体提及", sum(len(r.get("entities", [])) for r in records))
    c3.metric("带引文关系", len(edges))

    if resolved:
        st.markdown("#### 简历关系图")
        st.caption("图中节点来自本次抽取快照。点击节点可查看关联证据。")
        render_canvas(
            render_force_graph_html(resolved, scope="all", max_nodes=120, focus_resume=rid, height=470),
            height=480,
        )

    left, right = st.columns([1.2, 1], gap="large")
    with left:
        st.markdown("#### 记录原文")
        record = None
        if records:
            idx = st.selectbox(
                "选择原子记录",
                range(len(records)),
                format_func=lambda i: f"第 {records[i]['page_num']} 页 · {records[i]['kind']} · 记录 {i+1}",
                key="tab2_rec_sel",
            )
            record = records[idx]
            st.markdown(highlighted_record_html(record), unsafe_allow_html=True)
            with st.expander(f"实体识别明细（{len(record.get('entities', []))} 处）", expanded=False):
                st.caption(f"记录编号　{record['record_id']}　·　识别模型 GLiNER")
                ents = record.get("entities", [])
                if ents:
                    st.dataframe(ents, hide_index=True, width="stretch")
                else:
                    st.caption("本条记录没有通过置信度门槛的实体。")

        else:
            st.info("这份简历未提取到独立记录。")

    with right:
        st.markdown("#### 关系与引文")
        scope = st.radio("证据范围", ["当前记录", "整份简历"], horizontal=True, key="tab2_evidence_scope")
        visible = edges if scope == "整份简历" else [
            e for e in edges if record and e["properties"].get("record_id") == record["record_id"]
        ]
        rel_types = ["全部"] + sorted({e["type"] for e in visible})
        chosen_rel = st.selectbox("按关系类型筛选", rel_types, key="tab2_rel_filter")
        filtered = [e for e in visible if chosen_rel == "全部" or e["type"] == chosen_rel]
        if not filtered:
            st.caption("当前范围没有符合筛选条件的关系。可切换到整份简历或选择其他记录。")
            return
        st.caption(f"{len(filtered)} 条关系，其中 {sum(bool(e['properties'].get('evidence_valid')) for e in filtered)} 条引文通过页内匹配。")
        st.dataframe(
            [
                {
                    "关系": e["type"],
                    "终点": e["target"],
                    "来源": e["properties"].get("source", "-"),
                    "页码": e["properties"].get("page_num"),
                    "校验": "通过" if e["properties"].get("evidence_valid") else "未通过",
                    "原文引文": e["properties"].get("evidence_quote") or "",
                }
                for e in filtered
            ],
            hide_index=True,
            width="stretch",
            height=360,
        )


def graph_tab(stats: dict, resolved: dict):
    section_header(
        "图谱范围与实体归并",
        "切换数据范围浏览关系图，再查看同名实体如何区分、不同写法如何归并。",
    )
    if not resolved:
        st.info("实体消岐与共指审计尚未生成。")
        return

    ctrl1, ctrl2, ctrl3 = st.columns([1.2, 1.4, 1.4])
    scope_names = {"train": "训练集", "test": "测试集", "all": "全图"}
    scope = ctrl1.radio("图谱范围", list(scope_names), format_func=scope_names.get, horizontal=True, key="tab3_scope")
    max_nodes = ctrl2.slider("图中最多显示的节点数", min_value=70, max_value=240, value=150, step=10, key="tab3_density")
    if stats and scope in stats:
        vol = stats[scope]
        ctrl3.markdown(
            f'<div class="qz-callout teal" style="color:var(--ink-body)">'
            f'{scope_names[scope]}共 <b>{vol["node_count"]:,}</b> 个节点、'
            f'<b>{vol["relationship_count"]:,}</b> 条关系。'
            f'</div>',
            unsafe_allow_html=True,
        )

    render_canvas(
        render_force_graph_html(resolved, scope=scope, max_nodes=max_nodes, height=600),
        height=610,
    )

    st.caption("上图从已保存的图谱快照中选取节点，上限仅影响绘制数量。")
    audit = resolved.get("coref_audit", {})
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("双边消岐组", len(resolved.get("disambiguation_groups", [])))
    k2.metric("跨文档别名簇", len(audit.get("cross_document_groups", [])))
    k3.metric("文档内指代链", len(audit.get("within_document_chains", [])))
    k4.metric("防误并反例", f"{len(audit.get('negative_controls', []))} 对")
    st.markdown("#### 同一写法的两种含义")
    with st.expander("消岐分数如何计算"):
        st.write("局部上下文相似度占 50%，所在段落占 30%，同记录内的实体共现占 20%。两种含义各自有原句和独立的图谱关系时，计入一组。")
    render_canvas(
        render_disambiguation_animator_html(resolved.get("disambiguation_groups", [])),
        height=535,
    )

    st.markdown("#### 别名归并与例外")
    st.caption(f"归并前后节点压缩率 {audit.get('compression_ratio', 0):.2%}。选择示例查看归并结果和保留独立节点的依据。")
    render_canvas(render_coref_merge_animator_html(audit), height=330)

    # Distribution & Governance Audit
    if stats and scope in stats:
        data = stats[scope]
        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.markdown(f"#### {scope_names[scope]}节点分布")
            if data.get("nodes"):
                df_n = pd.DataFrame(list(data["nodes"].items()), columns=["节点类型", "数量"]).set_index("节点类型")
                st.bar_chart(df_n, horizontal=True, color="#284B63")
        with c2:
            st.markdown(f"#### {scope_names[scope]}关系分布")
            if data.get("relationships"):
                df_r = pd.DataFrame(list(data["relationships"].items()), columns=["关系类型", "数量"]).set_index("关系类型")
                st.bar_chart(df_r, horizontal=True, color="#247A6E")

    a1, a2 = st.columns(2)
    with a1:
        with st.expander(f"跨文档别名（{len(audit.get('cross_document_groups', []))} 组）"):
            rows = []
            for g in audit.get("cross_document_groups", []):
                exs = g.get("examples", [])
                rows.append({
                    "规范实体": g["canonical_name"],
                    "归并别名": " / ".join(g.get("aliases", [])),
                    "异名证据 A": f"{exs[0]['alias']} ({exs[0]['resume_id']} p.{exs[0]['page_num']})" if len(exs) > 0 else "",
                    "异名证据 B": f"{exs[1]['alias']} ({exs[1]['resume_id']} p.{exs[1]['page_num']})" if len(exs) > 1 else "",
                })
            st.dataframe(rows, hide_index=True, width="stretch")
        with st.expander(f"已过滤的噪声（{len(resolved.get('noise_pruned_mentions', []))} 处）"):
            st.json(resolved.get("noise_pruned_mentions", []), expanded=False)
    with a2:
        with st.expander(f"保留独立节点的反例（{len(audit.get('negative_controls', []))} 对）"):
            st.dataframe(
                [
                    {
                        "反例对": " vs ".join(c["names"]),
                        "字符相似度": c.get("similarity"),
                        "保护依据": c.get("reason"),
                    }
                    for c in audit.get("negative_controls", [])
                ],
                hide_index=True,
                width="stretch",
            )
        with st.expander(f"文档内指代（{len(audit.get('within_document_chains', []))} 处）"):
            st.dataframe(
                [
                    {
                        "简历": ch["resume_id"],
                        "页码": ch["page_num"],
                        "指代词": ch["surface"],
                        "先行实体": ch["canonical_name"],
                        "原句": ch["evidence_quote"],
                    }
                    for ch in audit.get("within_document_chains", [])
                ],
                hide_index=True,
                width="stretch",
            )

    with st.expander("Neo4j Browser 查询示例"):
        st.caption("在本机 Neo4j Browser（localhost:7474）中分别运行以下语句。")
        st.code(
            "// 查看训练集候选人-工作经历-实证技能二跳子图\n"
            "MATCH p=(c:ResumeKG:Candidate {split:'train'})-[:HAS_EXPERIENCE]->(w:WorkExperience)-[:USED_SKILL]->(s:Skill)\n"
            "RETURN p LIMIT 60\n\n"
            "// 查看项目实证技能网络\n"
            "MATCH p=(c:ResumeKG:Candidate)-[:WORKED_ON]->(pr:Project)-[:APPLIED_SKILL]->(s:Skill)\n"
            "RETURN p LIMIT 60",
            language="cypher",
        )


def rules_tab():
    section_header(
        "评估规则与候选人画像",
        "按维度查看训练集标定的阈值，再从候选人的得分追溯到简历原句。",
    )
    model = artifact(PROCESSED / "rules_model.json")
    if not model:
        st.info("请运行阶段四以查看按训练集标定的规则。")
        return

    st.markdown("#### 规则与覆盖人数")
    dimension = st.radio("选择评估维度", list(DIMS), format_func=lambda k: f"{DIMS[k]} ({k})", horizontal=True, key="tab4_dim")
    dim_rules = [r for r in model["rules"] if r["rule_id"].startswith(f"R-{dimension}-")]
    cols = st.columns(2, gap="medium")
    for idx, rule in enumerate(dim_rules):
        with cols[idx % 2]:
            rate_pct = round(rule["train_hit_rate"] * 100, 1)
            st.markdown(
                f'<div class="qz-rule-card" style="color:var(--ink-body)">'
                f'<div class="qz-quote-meta"><strong>{html.escape(rule["title"])}</strong>'
                f'<span class="qz-pill teal">+{rule["points"]} 分</span></div>'
                f'<div>{html.escape(rule["business_meaning"])}</div>'
                f'<div class="qz-bar-track"><div class="qz-bar-fill" style="width:{rate_pct}%;"></div></div>'
                f'<div>训练集命中 <b>{rule["train_hit_count"]} / {model["train_size"]}</b> 人（{rate_pct}%）</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            with st.expander(f"{rule['rule_id']} · 阈值、查询与命中原句"):
                st.write(rule["threshold_formula"])
                st.code(rule["cypher_predicate"], language="cypher")
                for ex in rule.get("sample_hit_resumes", [])[:4]:
                    show_evidence_card(ex)

    sync = artifact(PROCESSED / "sync_check_report.json")
    if sync:
        st.markdown("#### 训练集变化怎样影响评级")
        st.caption(f"比较两份已保存的训练快照：{len(sync.get('threshold_changes', []))} 条规则阈值发生变化。切换快照可核对同一测试候选人的评分。")
        render_canvas(render_sync_morph_html(sync), height=410)

    focus = PROCESSED / "focus_profiles"
    paths = sorted(focus.glob("*.json"))
    if paths:
        st.markdown("#### 重点简历画像")
        path = st.selectbox("选择重点评估简历", paths, format_func=lambda p: p.stem, key="tab4_focus_sel")
        profile = artifact(path)
        left, right = st.columns([1.05, 1.25], gap="large")
        with left:
            render_canvas(
                render_interactive_radar_html(
                    [{"name": profile["resume_id"], "scores": profile["scores"], "grades": profile["grades"], "color": "#247A6E"}],
                    title=f"{profile['resume_id']} · 四维得分",
                    height=355,
                ),
                height=365,
            )
        with right:
            gcols = st.columns(4)
            for col, (dim_k, dim_zh) in zip(gcols, DIMS.items()):
                sc = profile["scores"][dim_k]
                gr = profile["grades"][dim_k]
                col.markdown(
                    f'<div class="qz-kpi" style="text-align:center">'
                    f'<div class="qz-kpi-label">{dim_zh}</div>'
                    f'<div class="qz-kpi-val">{sc}</div>'
                    f'<span class="qz-grade qz-grade-{gr}">{gr}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            for insight in profile.get("analysis", []):
                st.markdown(f"- {insight}")
            if path.with_suffix(".md").exists():
                st.download_button(
                    "下载完整评估报告（Markdown）",
                    path.with_suffix(".md").read_bytes(),
                    file_name=path.with_suffix(".md").name,
                    key=f"dl-focus-{profile['resume_id']}",
                )

        st.markdown("#### 得分依据")
        for rule_id, examples in profile.get("rule_evidence", {}).items():
            grouped = group_rule_evidence(examples)
            with st.expander(f"{rule_id} · {len(grouped)} 条独立原文证据"):
                if len(grouped) > 12:
                    st.caption("预览前 12 条。完整引文可在评估报告中查看。")
                for e in grouped[:12]:
                    card_item = dict(e)
                    if e.get("skills"):
                        card_item["skill"] = " / ".join(e["skills"])
                    show_evidence_card(card_item)


def query_tab(driver, docs: dict):
    section_header(
        "按岗位需求检索候选人",
        "在测试集内匹配硬性条件。满足全部条件的候选人按岗位偏好排序。",
    )
    modes = {"主展示查询（严格命中 ≥3）": "主查询", "零命中边界（诚实返回 0）": "零命中示例", "自定义百字中文需求": "自定义需求"}
    mode = st.radio("岗位需求", list(modes), format_func=modes.get, horizontal=True, key="tab5_mode")
    if mode.startswith("自定义"):
        query = st.text_input("输入 100 字以内中文岗位需求", value=MAIN_QUERY, max_chars=100, key="tab5_custom_q")
        st.caption("可组合技能、学历、净工龄，并用“优先”指定项目经验、实证技能比例或加分技能。")
    else:
        query = MAIN_QUERY if mode.startswith("主展示") else ZERO_QUERY
        st.markdown(
            f'<div class="qz-callout teal" style="color:var(--ink-body)">'
            f'{html.escape(query)}</div>',
            unsafe_allow_html=True,
        )

    st.caption(f"{len(query)} / 100 字")

    if not docs:
        st.info("请先完成阶段一至阶段四的数据准备与规则评估。")
        return
    if not driver:
        fallback_name = "main.json" if mode.startswith("主展示") else "zero.json" if mode.startswith("零命中") else None
        report = artifact(PROCESSED / "query_reports" / fallback_name) if fallback_name else {}
        if not report:
            st.info("Neo4j 当前离线，请先启动容器后执行自定义中文查询。")
            return
        st.caption("Neo4j 离线，以下为上次保存的查询结果。")
    else:
        try:
            report = execute_query(query, driver)
        except (ValueError, ServiceUnavailable, SessionExpired, Neo4jError) as exc:
            st.warning(str(exc))
            return

    hits, near = report["strict_matches"], report["near_misses"]
    s1, s2, s3 = st.columns(3)
    s1.metric("严格命中", f"{len(hits)} 人")
    s2.metric("近似候选", f"{len(near)} 人")
    s3.metric("测试集", f"{sum(d['split'] == 'test' for d in docs.values())} 人")
    if not hits:
        st.info("当前测试集中无人同时满足全部硬性条件。下方列出了近似候选人及其缺失项。")

    ir = report["ir"]
    must_chips = []
    for grp in ir["must_skills"]:
        must_chips.append(f'<span class="qz-pill slate">技能　{html.escape(" 或 ".join(grp))}</span>')
    if ir["min_degree_level"]:
        must_chips.append(f'<span class="qz-pill slate">{DEGREE_NAMES[ir["min_degree_level"]]}及以上</span>')
    if ir["min_exp_years"]:
        must_chips.append(f'<span class="qz-pill slate">净工龄至少 {ir["min_exp_years"]} 年</span>')
    pref_chips = [f'<span class="qz-pill teal">{html.escape(s)} 优先</span>' for s in ir["prefer_skills"]]
    for sig in ir["prefer_signals"]:
        sig_zh = {"project_experience": "有项目经验优先", "verified_skill_ratio": "实证技能占比高优先"}.get(sig, sig)
        pref_chips.append(f'<span class="qz-pill teal">{html.escape(sig_zh)}</span>')

    st.markdown(
        f'<div class="qz-card" style="color:var(--ink-body)">'
        f'<div class="qz-quote-meta"><b>硬性条件</b> '
        f'{"".join(must_chips) or "无"}</div>'
        f'<div class="qz-quote-meta"><b style="color:var(--accent-teal)">排序偏好</b> '
        f'{"".join(pref_chips) or "无"}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    with st.expander("查看条件解析与 Cypher"):
        st.json(ir, expanded=False)
        st.code(report["browser_cypher"], language="cypher")

    if len(hits) >= 3:
        st.markdown("#### 排名前三的候选人")
        top = hits[:3]
        palette = ["#284B63", "#A24627", "#247A6E"]
        radar_series = [
            {"name": c["resume_id"], "scores": c["scores"], "grades": c["grades"], "color": palette[i]}
            for i, c in enumerate(top)
        ]
        cl, cr = st.columns([1.05, 1.35], gap="large")
        with cl:
            render_canvas(
                render_interactive_radar_html(radar_series, title="四维得分对比", height=370),
                height=380,
            )
        with cr:
            st.dataframe(comparison_rows(top), hide_index=True, width="stretch")
            st.markdown(
                f'<div class="qz-callout teal" style="color:var(--ink-body)">'
                f'<b style="color:var(--accent-teal)">面试排序建议</b>'
                f'<div>{html.escape(comparison_conclusion(top))}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            for c in top:
                with st.expander(f"{c['resume_id']} · {c['verified_skill_count']} 项实证技能与面试追问"):
                    st.write(recommendation(c))
                    for e in c["skill_evidence"][:2] + c["project_evidence"][:2]:
                        show_evidence_card(e)

    if hits:
        st.markdown("#### 候选人原始简历与命中依据")
        chosen = st.selectbox(
            "选择严格命中候选人查看原始 PDF 与证据",
            hits,
            format_func=lambda c: f"{c['resume_id']} · {DEGREE_NAMES[c['degree_level']]} · 净工龄 {c['merged_exp_months']} 月 · 项目 {c['project_count']} 段 · 偏好分 {c['preference_score']:.1f}",
            key="tab5_hit_sel",
        )
        doc = docs[chosen["resume_id"]]
        c_left, c_right = st.columns([1.15, 1], gap="large")
        with c_left:
            st.markdown(
                f'<div class="qz-quote-meta">'
                f'<span class="qz-pill slate">{html.escape(chosen["resume_id"])}</span> '
                f'<span class="qz-pill">{DEGREE_NAMES[chosen["degree_level"]]}</span> '
                f'<span class="qz-pill">净工龄 {chosen["merged_exp_months"]} 月</span> '
                f'<span class="qz-pill">{chosen["project_count"]} 段项目</span> '
                f'<span class="qz-pill teal">实证技能占比 {chosen["verified_skill_ratio"]:.1%}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            read_pdf_link(chosen, f"match-pdf-{chosen['resume_id']}")
            for e in chosen["skill_evidence"][:6]:
                show_evidence_card(e)
            for items in chosen.get("threshold_evidence", {}).values():
                for e in items[:2]:
                    show_evidence_card(e)
        with c_right:
            with st.expander("逐页查看 PDF 原文", expanded=True):
                for page in doc["pages"]:
                    st.caption(f"第 {page['page_num']} 页")
                    st.markdown(
                        f'<div class="qz-record-box" style="max-height:240px;">{html.escape(page["text"])}</div>',
                        unsafe_allow_html=True,
                    )
    st.markdown(f"#### 近似候选人的缺失条件（{len(near)} 人）")
    if near:
        st.dataframe(
            [
                {
                    "简历": c["resume_id"],
                    "学历": DEGREE_NAMES[c["degree_level"]],
                    "净工龄（月）": c["merged_exp_months"],
                    "已命中技能": "、".join(c["matched_skills"]) or "无",
                    "缺失硬性条件": "；".join(c["missing_conditions"]),
                }
                for c in near
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("测试集中没有近似候选人。")


def main():
    st.markdown(theme_css(), unsafe_allow_html=True)

    try:
        driver = connection()
        stats = graph_stats(driver)
        online = True
    except (ServiceUnavailable, SessionExpired, Neo4jError, OSError):
        driver, stats, online = None, {}, False

    acceptance = artifact(PROCESSED / "acceptance_report.json")
    manifest = artifact(ROOT / "data/extracted_txt/manifest.json")
    if not stats and acceptance:
        stats = acceptance.get("checks", {}).get("AC-4", {}).get("metrics", {})

    docs = {d["resume_id"]: d for d in manifest.get("documents", [])}

    with st.sidebar:
        st.markdown(
            '<div class="kg-brand"><span class="kg-mark" aria-hidden="true"><i></i><i></i><i></i></span>'
            '<div><b>图谱工作台</b><small>简历研究档案</small></div></div>',
            unsafe_allow_html=True,
        )
        if docs:
            ids = list(docs)
            default_idx = ids.index("cv-486c4ba1bcae") if "cv-486c4ba1bcae" in docs else 0
            selected = st.selectbox(
                "当前简历", ids, index=default_idx,
                format_func=lambda rid: f"{rid} · {'测试' if docs[rid]['split']=='test' else '训练'}",
                key="sidebar_doc_sel", help="联动「采集」的原文与「抽取」的记录和关系。",
            )
            st.caption(Path(docs[selected]["source_name"]).name + f"　·　{len(docs[selected]['pages'])} 页")
        else:
            selected = None
        st.divider()
        if docs:
            n_train = sum(d["split"] == "train" for d in docs.values())
            n_test = sum(d["split"] == "test" for d in docs.values())
            st.markdown(
                '<div class="kg-label">样本划分</div>'
                f'<div class="kg-split" aria-hidden="true"><i style="flex:{n_train}"></i><i style="flex:{n_test}"></i></div>'
                f'<div class="kg-split-legend"><span>训练　{n_train}</span><span>测试　{n_test}</span></div>',
                unsafe_allow_html=True,
            )
        if stats:
            stat_rows = []
            for key, label in (("train", "训练子图"), ("test", "测试子图")):
                data = stats.get(key, {})
                nodes, edges = data.get("node_count"), data.get("relationship_count")
                if nodes is not None and edges is not None:
                    stat_rows.append(f'<div><span>{label}</span><strong>{nodes:,} / {edges:,}</strong></div>')
            st.markdown('<div class="kg-label">节点数 / 关系数</div><div class="kg-side-stats">'+
                        "".join(stat_rows)+'</div>', unsafe_allow_html=True)
        if online:
            st.link_button("打开 Neo4j Browser", "http://localhost:7474", icon=":material/open_in_new:")
        else:
            st.caption("数据库离线，当前显示上次验收快照。")

    st.markdown(hero_banner_html(stats, acceptance, online), unsafe_allow_html=True)
    labels = ["采 · 数据采集", "治 · 记录抽取", "存 · 图谱探索", "算 · 规则画像", "用 · 岗位检索"]
    tabs = st.tabs(labels, key="stage", on_change="rerun")
    index = next(i for i, tab in enumerate(tabs) if tab.open)
    # Streamlit normally drops widgets from inactive views. Preserve their
    # filters while creating charts and running queries only for the open tab.
    for key in tuple(st.session_state):
        if key.startswith(("tab1_", "tab2_", "tab3_", "tab4_", "tab5_")) and not key.startswith(f"tab{index + 1}_"):
            st.session_state[key] = st.session_state[key]

    with tabs[index]:
        if index == 0:
            collection_tab(docs.get(selected), manifest)
        elif index == 1:
            extraction_tab(docs.get(selected), artifact(PROCESSED / "resolved_kg.json"))
        elif index == 2:
            graph_tab(stats, artifact(PROCESSED / "resolved_kg.json"))
        elif index == 3:
            rules_tab()
        else:
            query_tab(driver, docs)


if __name__ == "__main__":
    main()
