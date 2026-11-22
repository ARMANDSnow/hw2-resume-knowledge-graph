"""按岗位需求检索测试集简历。"""
from __future__ import annotations

import html
from collections import Counter

import streamlit as st
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired

from src.stage5_query import (
    DEGREE_NAMES,
    MAIN_QUERY,
    ZERO_QUERY,
    comparison_conclusion,
    comparison_rows,
    execute_query,
    recommendation,
)
from src.ui_layout import PROCESSED, artifact, open_source, read_pdf_link, render_canvas, show_evidence_card
from src.ui_visuals import render_interactive_radar_html


EXAMPLES = {
    "常规技术岗": MAIN_QUERY,
    "高门槛岗位": ZERO_QUERY,
    "数据工程师": "招聘数据工程师，掌握 SQL，至少 2 年工作经验，熟悉 Python 优先。",
}
SNAPSHOTS = {MAIN_QUERY: "main.json", ZERO_QUERY: "zero.json"}


def _fill_example(query):
    st.session_state["search_draft"] = query
    st.session_state["_search_editor"] = query


def _save_draft():
    st.session_state["search_draft"] = st.session_state["_search_editor"]


def _composer(online):
    state = st.session_state
    if "_search_editor" not in state:
        state["_search_editor"] = state.get("search_draft", state.get("submitted_query", ""))

    with st.container(border=True, key="search_composer"):
        draft = st.text_area(
            "岗位需求",
            key="_search_editor",
            on_change=_save_draft,
            max_chars=100,
            height=100,
            label_visibility="collapsed",
            placeholder="描述你要招的人，例如：本科及以上，掌握 Python，有项目经验优先。",
        )
        with st.container(horizontal=True, vertical_alignment="center", horizontal_alignment="right"):
            search = st.button("检索候选人", type="primary", icon=":material/arrow_upward:")
    with st.container(horizontal=True, key="search_examples", vertical_alignment="center"):
        st.caption("试试示例", width="content")
        for label, query in EXAMPLES.items():
            st.button(label, on_click=_fill_example, args=(query,))

    if search:
        if draft.strip():
            state["submitted_query"] = draft.strip()
            state.pop("search_report", None)
        else:
            st.warning("先写一句岗位需求，或点一个示例填入。")
    if not online:
        st.caption("离线时可查看「常规技术岗」和「高门槛岗位」的已保存结果。")


def _report_for(query, driver):
    # Keep a submitted result stable while a reader explores its candidates.
    online = driver is not None
    saved = st.session_state.get("search_report")
    if saved and saved["query"] == query and saved["online"] == online:
        return saved["report"], saved["snapshot"]

    report = None
    if online:
        try:
            report = execute_query(query, driver)
        except ValueError as exc:
            st.warning(str(exc))
            return None, False
        except (ServiceUnavailable, SessionExpired, Neo4jError, OSError):
            st.warning("数据库暂时无法完成检索，可重新提交需求再试。")
    snapshot = report is None
    if snapshot:
        name = SNAPSHOTS.get(query)
        if not name:
            st.info("这条需求需要连接 Neo4j 才能检索。也可以试试上方两个有保存结果的示例。")
            return None, False
        report = artifact(PROCESSED / "query_reports" / name)
        if not report or report.get("query") != query:
            st.info("尚未找到这条需求的已保存结果。")
            return None, False
    st.session_state["search_report"] = dict(query=query, online=online, report=report, snapshot=snapshot)
    return report, snapshot


def _summary(hits, near):
    total = len(hits) + len(near)
    summary = f"在 {total} 位测试候选人中，{len(hits)} 位完全符合。"
    gaps = Counter(len(c["missing_conditions"]) for c in near)
    if gaps:
        summary += "另有 " + "，".join(f"{gaps[n]} 位差 {n} 项" for n in sorted(gaps)) + "。"
    return summary


def _requirements(ir):
    required = [" 或 ".join(group) for group in ir["must_skills"]]
    if ir["min_degree_level"]:
        required.append(f'{DEGREE_NAMES[ir["min_degree_level"]]}及以上')
    if ir["min_exp_years"]:
        required.append(f'至少 {ir["min_exp_years"]:g} 年工作经验')
    preferred = list(ir["prefer_skills"])
    signals = {"project_experience": "有项目经验", "verified_skill_ratio": "有经历支撑的技能占比高"}
    preferred.extend(signals.get(signal, signal) for signal in ir["prefer_signals"])
    for label, items, kind in (("必须满足", required, "slate"), ("优先考虑", preferred, "terra")):
        chips = "".join(f'<span class="qz-pill {kind}">{html.escape(item)}</span>' for item in items)
        st.markdown(f'<div class="qz-quote-meta"><b>{label}</b> {chips or "未指定"}</div>', unsafe_allow_html=True)


def _comparison(top):
    with st.expander("前三位候选人对比", expanded=True):
        palette = ["#A54E32", "#536D80", "#667C5D"]
        series = [
            {"name": c["resume_id"], "scores": c["scores"], "grades": c["grades"], "color": color}
            for c, color in zip(top, palette)
        ]
        chart, details = st.columns([1, 1.25], gap="large")
        with chart:
            render_canvas(render_interactive_radar_html(series, title="四项能力得分", height=355), height=365)
        with details:
            st.write(comparison_conclusion(top))
            st.dataframe(comparison_rows(top), hide_index=True, width="stretch")
    for c in top:
        with st.expander(f'{c["resume_id"]} · 面试追问与原句'):
            st.write(recommendation(c))
            for evidence in c["skill_evidence"][:2] + c["project_evidence"][:2]:
                show_evidence_card(evidence)


def _candidate(hits, docs):
    by_id = {c["resume_id"]: c for c in hits}
    st.markdown("#### 完全符合的候选人")
    rid = st.selectbox("选择候选人查看依据", list(by_id), key="search_candidate")
    c = by_id[rid]
    st.caption(
        f'{DEGREE_NAMES[c["degree_level"]]}　·　净工龄 {c["merged_exp_months"]} 个月　·　'
        f'{c["project_count"]} 段项目　·　岗位偏好分 {c["preference_score"]:g}　·　'
        f'有经历支撑的技能占比 {c["verified_skill_ratio"]:.0%}'
    )
    doc = docs.get(rid)
    if doc:
        with st.container(horizontal=True):
            if st.button("在原文页查看", icon=":material/article:"):
                open_source(rid)
            read_pdf_link(doc, f"match-pdf-{rid}")
    with st.expander("匹配依据与简历原句", expanded=True):
        for evidence in c["skill_evidence"][:6]:
            show_evidence_card(evidence)
        for records in c.get("threshold_evidence", {}).values():
            for evidence in records[:2]:
                show_evidence_card(evidence)
        if not c["skill_evidence"] and not any(c.get("threshold_evidence", {}).values()):
            st.caption("本次需求没有可单列的技能、学历或工龄引文。")
    if doc:
        with st.expander("逐页阅读简历"):
            for page in doc["pages"]:
                st.caption(f'第 {page["page_num"]} 页')
                st.markdown(
                    f'<div class="qz-record-box" tabindex="0" style="max-height:240px;">'
                    f'{html.escape(page["text"])}</div>', unsafe_allow_html=True,
                )


def render(driver, docs: dict):
    _composer(driver is not None)
    query = st.session_state.get("submitted_query")
    if not query:
        return
    if not docs:
        st.info("准备好简历样本并完成评分后，就可以按岗位需求检索。")
        return

    st.divider()
    st.markdown(
        f'<div class="qz-quote-meta"><b>已提交需求</b> {html.escape(query)}</div>',
        unsafe_allow_html=True,
    )
    report, snapshot = _report_for(query, driver)
    if not report:
        return
    if snapshot:
        st.caption("结果来源 · 上次保存的检索")
    hits, near = report["strict_matches"], report["near_misses"]
    st.subheader(_summary(hits, near), anchor=False)
    _requirements(report["ir"])
    with st.expander("查看条件解析与数据库查询"):
        st.json(report["ir"], expanded=False)
        st.code(report["browser_cypher"], language="cypher")

    if len(hits) >= 3:
        _comparison(hits[:3])
    if hits:
        _candidate(hits, docs)
    if near:
        with st.expander(f"查看 {len(near)} 位候选人还缺哪些条件", expanded=not hits):
            st.dataframe([
                {
                    "简历": c["resume_id"],
                    "尚缺条件": "；".join(c["missing_conditions"]),
                    "符合的技能": "、".join(c["matched_skills"]) or "无",
                    "学历": DEGREE_NAMES[c["degree_level"]],
                    "净工龄（月）": c["merged_exp_months"],
                }
                for c in near
            ], hide_index=True, width="stretch")
