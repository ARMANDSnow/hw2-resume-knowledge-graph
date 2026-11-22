"""把当前简历的段落、图谱高亮和逐条引文放在同一上下文。"""
import streamlit as st

from src.ui_graph import render_force_graph_html
from src.ui_layout import PROCESSED, artifact, metric_strip, render_canvas
from src.ui_theme import highlighted_record_html

KINDS = {"WorkRecord": "工作经历", "EduRecord": "教育经历", "ProjectRecord": "项目经历",
         "PROFILE": "个人简介", "SKILLS": "技能清单", "OTHER": "其他段落", "CERTIFICATIONS": "资格证书"}


def render(doc, resolved):
    data = artifact(PROCESSED / "extractions.json")
    if not doc or not data:
        st.info("完成简历采集和抽取后，这里会显示段落和对应的引文。")
        return
    rid = doc["resume_id"]
    extracted = next((d for d in data["documents"] if d["resume_id"] == rid), {})
    records = extracted.get("records", [])
    edges = [e for e in data["edges"] if e["properties"].get("resume_id") == rid]
    metric_strip([("简历段落", len(records)), ("识别到的实体", sum(len(r.get("entities", [])) for r in records)),
                  ("有原句的关系", sum(bool(e["properties"].get("evidence_quote")) for e in edges))])

    if not records:
        st.info("这份简历暂时没有可供核对的段落。")
        return
    graph_area = st.container()
    left, right = st.columns([1, 2.35], gap="medium")
    with left:
        st.markdown("### 选择段落")
        def record_label(index):
            r = records[index]
            return f"{index+1:02}　{KINDS.get(r['kind'], r['kind'])} · 第 {r['page_num']} 页"

        with st.container(height=min(385, 50 + 40 * len(records)), key="record_list"):
            idx = st.radio("简历段落", range(len(records)), format_func=record_label,
                           label_visibility="collapsed", key=f"extract_record_{rid}", persist_state="session")
    record = records[idx]
    if resolved:
        with graph_area:
            st.markdown("### 这份简历的关系图")
            st.caption("实线表示技能在工作或项目中用过，虚线表示仅在技能清单中出现。选择下方段落，可在图中高亮对应记录。")
            render_canvas(render_force_graph_html(resolved, scope="all", max_nodes=120, focus_resume=rid,
                          height=500, active_record_id=record["record_id"]), height=510)
    with right:
        st.markdown(f"### 第 {record['page_num']} 页 · {KINDS.get(record['kind'], record['kind'])}")
        st.html(highlighted_record_html(record))
        entities = record.get("entities", [])
        if entities:
            with st.expander(f"识别到的实体 · {len(entities)} 处"):
                st.caption(f"记录 {record['record_id']} · 识别模型 GLiNER")
                st.dataframe(entities, hide_index=True, width="stretch")
        st.markdown("### 关系与引文")
        scope = st.pills("证据范围", ["当前段落", "整份简历"], default="当前段落", required=True, key="extract_scope")
        visible = edges if scope == "整份简历" else [e for e in edges if e["properties"].get("record_id") == record["record_id"]]
        relation = st.selectbox("按关系类型筛选", ["全部"] + sorted({e["type"] for e in visible}), key="extract_relation")
        filtered = [e for e in visible if relation == "全部" or e["type"] == relation]
        if not filtered:
            st.caption("这个范围内没有符合筛选条件的关系。换个段落，或查看整份简历。")
            return
        verified = sum(bool(e["properties"].get("evidence_valid")) for e in filtered)
        st.caption(f"{len(filtered)} 条关系，其中 {verified} 条引文可在对应页找到。")
        st.dataframe([{"关系": e["type"], "关联实体": e["target"], "页码": e["properties"].get("page_num"),
                       "来源": e["properties"].get("source", "—"),
                       "校验": "通过" if e["properties"].get("evidence_valid") else "未通过",
                       "原文引文": e["properties"].get("evidence_quote", "")} for e in filtered],
                     hide_index=True, width="stretch")
