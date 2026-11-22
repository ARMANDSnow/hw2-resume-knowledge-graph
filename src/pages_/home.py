"""工作台概览和跨页入口。"""
import html

import streamlit as st

from src.ui_copy import STAGES
from src.ui_layout import PROCESSED, artifact, metric_strip, open_source


def render(manifest, stats, acceptance, pages):
    docs = manifest.get("documents", [])
    checks = {k: v.get("metrics", {}) for k, v in acceptance.get("checks", {}).items()}
    report = artifact(PROCESSED / "query_reports/main.json")
    example = next(((c, e) for c in report.get("strict_matches", [])
                    for e in c.get("skill_evidence", [])
                    if e.get("source") == "work_verified" and e.get("evidence_quote") and e.get("skill")), None)

    left, right = st.columns([1.5, 1], gap="large", vertical_alignment="center")
    with left:
        intro = f'从 {len(docs)} 份英文简历出发' if docs else '从英文简历出发'
        st.html(f'<header class="kg-home-title"><div class="kg-eyebrow"><span></span>工作台概览</div>'
                f'<h1>从简历原文，<br>到可追溯的<em>人才画像。</em></h1>'
                f'<p>{intro}，查阅经历与技能，核对每个判断背后的原句。</p></header>')
    if example:
        candidate, evidence = example
        with right, st.container(key="specimen"):
            skill = html.escape(str(evidence["skill"]))
            quote = html.escape(evidence["evidence_quote"])
            st.html(f'<div class="kg-specimen"><div class="kg-spec-label"><i></i>工作经历原文'
                    f'<span>PDF · P.{int(evidence["page_num"]):02}</span></div>'
                    f'<blockquote lang="en">{quote}</blockquote>'
                    f'<div class="kg-trace"><span>工作经历</span><i></i><b>{skill}</b></div></div>')
            if any(doc["resume_id"] == candidate["resume_id"] for doc in docs):
                st.button("查看这份原文", key="open_specimen", type="tertiary", icon=":material/arrow_outward:",
                          on_click=open_source, args=(candidate["resume_id"],))

    graph = stats.get("all", {})
    valid = checks.get("AC-3", {}).get("quote_valid_rate")
    rule_count = checks.get("AC-6", {}).get("live_rules")
    metric_strip([("图谱节点", graph.get("node_count")), ("实体关系", graph.get("relationship_count")),
                  ("引文核验率", f"{valid:.0%}" if valid is not None else None), ("评分规则", rule_count)])

    st.markdown("### 按岗位找人")
    with st.form("quick_search", border=False):
        query_area, submit_area = st.columns([4.5, 1.2], vertical_alignment="bottom", gap="small")
        query = query_area.text_input("岗位需求", placeholder="描述你要招的人，例如：本科及以上，掌握 Python 或 SQL",
                                      max_chars=100, label_visibility="collapsed")
        submitted = submit_area.form_submit_button("开始检索", type="primary", icon=":material/arrow_forward:",
                                                   icon_position="right", width="stretch")
    if submitted:
        if query.strip():
            st.session_state.update(submitted_query=query.strip(), search_draft=query.strip())
            st.switch_page(pages["search"])
        else:
            st.info("先写下一个岗位条件，例如「掌握 Python」。")

    st.markdown("### 五步研究流程")
    train = sum(d["split"] == "train" for d in docs)
    test = sum(d["split"] == "test" for d in docs)
    records = checks.get("AC-3", {}).get("records")
    groups = checks.get("AC-5", {}).get("verified_groups")
    facts = [f"{len(docs)} 份样本", f"{records:,} 段原文" if records is not None else "经历与技能",
             f"{groups} 组消歧案例" if groups is not None else "实体与关系",
             f"{rule_count} 条评分规则" if rule_count is not None else "候选人评分", f"{test} 位测试候选人"]
    for col, stage, fact in zip(st.columns(5, gap="small"), STAGES, facts):
        with col, st.container(key=f"flow_{stage.path}"):
            st.page_link(pages[stage.path], label=stage.name, icon=f":material/{stage.icon}:", width="stretch")
            st.html(f'<div class="kg-flow-info">{stage.description}<small>{fact}</small></div>')

    with st.expander("训练集与测试集"):
        for scope, label, count in (("train", "训练集", train), ("test", "测试集", test)):
            data = stats.get(scope, {})
            numbers = (f"{data['node_count']:,} 个节点 · {data['relationship_count']:,} 条关系"
                       if "node_count" in data and "relationship_count" in data else "暂无图谱统计")
            st.write(f"**{label}**　{count} 份简历　·　{numbers}")
