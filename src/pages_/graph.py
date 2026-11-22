"""Browse the resume graph and inspect the evidence behind entity resolution."""
import pandas as pd
import streamlit as st

from src.ui_graph import render_force_graph_html
from src.ui_layout import render_canvas
from src.ui_visuals import render_coref_merge_animator_html, render_disambiguation_animator_html


SCOPES = {"train": "训练集", "test": "测试集", "all": "全部简历"}


def _scope_selector():
    return st.segmented_control(
        "简历范围", SCOPES.keys(), format_func=SCOPES.get, default="train",
        required=True, key="graph_scope", persist_state="session",
    )


def _canvas(stats, resolved):
    controls, limit = st.columns([1.2, 1])
    with controls:
        scope = _scope_selector()
    max_nodes = limit.slider("画布最多显示", 70, 240, 150, step=10, format="%d 个节点", key="graph_density", persist_state="session")
    data = stats.get(scope, {})
    if data:
        st.caption(f"{SCOPES[scope]}共有 {data['node_count']:,} 个节点、{data['relationship_count']:,} 条关系。点选节点可查看相邻关系和简历原句。")
    render_canvas(render_force_graph_html(resolved, scope=scope, max_nodes=max_nodes, height=510), height=515)
    with st.expander("在 Neo4j Browser 复核关系"):
        st.code(
            "// 训练集候选人的工作经历和用过的技能\n"
            "MATCH p=(c:ResumeKG:Candidate {split:'train'})-[:HAS_EXPERIENCE]->(w:WorkExperience)-[:USED_SKILL]->(s:Skill)\n"
            "RETURN p LIMIT 60\n\n"
            "// 项目中用过的技能\n"
            "MATCH p=(c:ResumeKG:Candidate)-[:WORKED_ON]->(pr:Project)-[:APPLIED_SKILL]->(s:Skill)\n"
            "RETURN p LIMIT 60", language="cypher",
        )


def _distribution(stats, resolved, audit):
    scope = _scope_selector()
    data = stats.get(scope, {})
    for col, field, title, color in zip(
        st.columns(2, gap="large"),
        ("nodes", "relationships"), ("节点类型", "关系类型"), ("#AF634A", "#738377"),
    ):
        with col:
            st.markdown(f"#### {title}分布")
            if data.get(field):
                counts = pd.Series(data[field], name="数量").rename_axis(title)
                st.bar_chart(counts, horizontal=True, color=color)
            else:
                st.caption("当前范围尚无统计。")

    for title, rows in (
        ("不同简历中出现的别名", [
            {"统一名称": group["canonical_name"], "不同写法": " / ".join(group.get("aliases", [])),
             "简历出处": "、".join(f"{e['alias']}（{e['resume_id']} · 第 {e['page_num']} 页）"
                                for e in group.get("examples", [])[:2])}
            for group in audit.get("cross_document_groups", [])
        ]),
        ("保留为不同实体的相似名称", [
            {"名称": " / ".join(pair["names"]), "相似度": pair.get("similarity"), "保留原因": pair.get("reason")}
            for pair in audit.get("negative_controls", [])
        ]),
        ("同一份简历中的指代", [
            {"简历": item["resume_id"], "页码": item["page_num"], "指代词": item["surface"],
             "指向": item["canonical_name"], "原句": item["evidence_quote"]}
            for item in audit.get("within_document_chains", [])
        ]),
    ):
        with st.expander(f"{title}（{len(rows)}）"):
            if rows:
                st.dataframe(rows, hide_index=True, width="stretch")
            else:
                st.caption("当前没有记录。")
    noise = resolved.get("noise_pruned_mentions", [])
    with st.expander(f"抽取时过滤的词（{len(noise)}）"):
        st.json(noise, expanded=False)


def render(stats: dict, resolved: dict):
    if not resolved:
        st.info("图谱还未生成。完成简历抽取和实体整理后，即可在这里探索关系。")
        return
    graph, senses, aliases, distribution = st.tabs(
        ["图谱", "消歧", "归并", "分布与审计"], key="graph_view", on_change="rerun",
    )
    audit = resolved.get("coref_audit", {})
    if graph.open:
        with graph:
            _canvas(stats, resolved)
    elif senses.open:
        with senses:
            groups = resolved.get("disambiguation_groups", [])
            st.markdown("#### 同一个词，两种意思")
            st.caption(f"选一个词，并排核对它在两段原文中的用法。共有 {len(groups)} 组消歧案例。")
            render_canvas(render_disambiguation_animator_html(groups), height=535)
            with st.expander("怎样判断一个词的含义"):
                st.write("前后用词占 50%，所在段落占 30%，同一段经历里出现的其他实体占 20%。每种含义都能找到原句和对应的图谱关系。")
    elif aliases.open:
        with aliases:
            st.markdown("#### 不同写法指向同一个实体")
            st.caption(f"在不同简历中找到 {len(audit.get('cross_document_groups', []))} 组别名。归并后，节点数量减少 {audit.get('compression_ratio', 0):.1%}。")
            render_canvas(render_coref_merge_animator_html(audit), height=330)
    else:
        with distribution:
            _distribution(stats, resolved, audit)
