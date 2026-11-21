"""运行方式：.venv/bin/streamlit run app.py"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired

from src.stage3_neo4j import get_driver, graph_stats
from src.stage5_query import (
    DEGREE_NAMES, DIMS, MAIN_QUERY, ZERO_QUERY, comparison_conclusion, comparison_rows,
    execute_query, recommendation,
)

ROOT = Path(__file__).resolve().parent
PROCESSED = ROOT / "data/processed"
st.set_page_config(page_title="简历知识图谱", page_icon="◈", layout="wide")

@st.cache_data(show_spinner=False)
def _read_json(path, modified):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def artifact(path):
    if not path.exists():
        return {}
    return _read_json(str(path), path.stat().st_mtime_ns)

@st.cache_resource(show_spinner=False)
def connection():
    return get_driver()

def read_pdf_link(doc, key):
    path = ROOT / doc["pdf_path"]
    if path.is_file():
        st.download_button("下载原始 PDF", path.read_bytes(), file_name=path.name,
                           mime="application/pdf", key=key)
    st.caption(doc["pdf_path"])

def show_evidence(e):
    rid = e.get("resume_id", "")
    page = e.get("page_num", "?")
    label = " · ".join(str(x) for x in (rid, f"第 {page} 页", e.get("skill"), e.get("source")) if x)
    st.caption(label)
    st.text(e.get("evidence_quote") or "缺少引文")

def collection(doc, manifest):
    st.header("数据准备与固定划分")
    if not doc:
        st.info("请运行阶段一以查看固定快照。")
        return
    docs = manifest["documents"]
    cols = st.columns(3)
    cols[0].metric("训练样本", sum(d["split"] == "train" for d in docs))
    cols[1].metric("测试样本", sum(d["split"] == "test" for d in docs))
    cols[2].metric("两级哈希去重剔除", manifest["dedup_removed_count"])
    with st.expander("快照与哈希"):
        st.code(manifest["cohort_hash"])
        st.json({k: v for k, v in manifest.items()
                 if ("dedup" in k or "duplicate" in k or "removed" in k) and k != "documents"})
        st.json({k: doc[k] for k in ("resume_id", "source_name", "split", "file_hash", "text_hash")})
    st.subheader("原始简历")
    pages = doc["pages"]
    page_index = st.selectbox("原文页码", range(len(pages)), format_func=lambda i: f"第 {pages[i]['page_num']} 页")
    page = pages[page_index]
    st.caption(f"{doc['source_name']} · 字符偏移 [{page['char_start']}, {page['char_end']})")
    st.text(page["text"])
    read_pdf_link(doc, "collect-pdf")
    audit = PROCESSED / "pilot_audit.md"
    if audit.exists():
        with st.expander("12 份试点抽检记录"):
            st.markdown(audit.read_text())

def extraction(doc):
    st.header("记录切分与原文证据")
    data = artifact(PROCESSED / "extractions.json")
    if not data or not doc:
        st.info("请先运行阶段二。")
        return
    rid = doc["resume_id"]
    extracted = next((d for d in data["documents"] if d["resume_id"] == rid), None)
    if not extracted:
        st.info("当前简历尚无抽取记录。")
        return
    records = extracted["records"]
    edges = [e for e in data["edges"] if e["properties"].get("resume_id") == rid]
    st.caption(f"{rid} · {len(records)} 条记录 · {len(edges)} 条带出处的关系")
    if records:
        index = st.selectbox("抽取记录", range(len(records)), format_func=lambda i:
                             f"{records[i]['kind']} · 第 {records[i]['page_num']} 页 · {records[i]['record_id']}")
        record = records[index]
        st.text(record["record_text"])
        with st.expander("模型识别出的实体", expanded=True):
            entities = record.get("entities", [])
            if entities:
                st.dataframe(entities, hide_index=True, use_container_width=True)
            else:
                st.caption("本条记录没有通过模型置信度门槛的实体。")
    with st.expander("全部关系与页码", expanded=True):
        st.dataframe([{"关系": e["type"], "起点": e["source"], "终点": e["target"],
                       **{k: e["properties"].get(k) for k in
                          ("record_id", "page_num", "evidence_quote", "evidence_valid")}} for e in edges],
                     hide_index=True, use_container_width=True)

def graph_tab(stats):
    st.header("图谱规模与实体归并")
    if stats:
        scope = st.radio("子图范围", ["train", "test", "all"], horizontal=True)
        data = stats[scope]
        cols = st.columns(2)
        for col, metric, label in zip(cols, ("nodes", "relationships"), ("领域节点", "关系类型")):
            col.subheader(label)
            if not data[metric]:
                col.caption("当前范围内尚无数据。")
                continue
            counts = pd.DataFrame(list(data[metric].items()), columns=["类型", "数量"]).set_index("类型")
            col.bar_chart(counts, horizontal=True, color="#287687" if metric == "nodes" else "#A64F36")
    resolved = artifact(PROCESSED / "resolved_kg.json")
    if not resolved:
        st.info("实体消岐与共指审计尚未生成。")
        return
    st.subheader("同一写法的两个真实义项")
    for g in resolved["disambiguation_groups"]:
        with st.expander(str(g["surface"])):
            for e in g["senses"]:
                st.markdown(f"**{e['label']} · {e['name']}**")
                st.code(f"{e['edge_source']} —[{e['edge_type']}]→ {e['node_id']}", language=None)
                show_evidence(e)
                st.json(e["scores"], expanded=False)
    with st.expander(f"噪声过滤（{len(resolved['noise_pruned_mentions'])} 处）"):
        st.json(resolved["noise_pruned_mentions"], expanded=False)
    audit = resolved["coref_audit"]
    st.subheader("共指消解")
    st.metric("归并压缩率", f"{audit['compression_ratio']:.1%}")
    for key, title in (("within_document_chains", "文档内指代链"),
                       ("cross_document_groups", "跨文档别名"),
                       ("negative_controls", "保持分离的反例")):
        with st.expander(f"{title}（{len(audit[key])} 组）"):
            st.json(audit[key], expanded=False)
    with st.expander("在 Neo4j Browser 中浏览训练图谱"):
        st.code("MATCH p=(c:ResumeKG:Candidate {split:'train'})-[*1..2]->(n:ResumeKG)\nRETURN p LIMIT 100",
                language="cypher")

def rules_tab():
    st.header("规则覆盖与候选人画像")
    model = artifact(PROCESSED / "rules_model.json")
    if not model:
        st.info("请运行阶段四以查看按训练集标定的规则。")
        return
    dimension = st.radio("评估维度", list(DIMS), format_func=DIMS.get, horizontal=True)
    for rule in model["rules"]:
        if not rule["rule_id"].startswith(f"R-{dimension}-"):
            continue
        with st.expander(f"{rule['rule_id']}  {rule['title']} · 命中 {rule['train_hit_count']} 人"):
            st.write(rule["business_meaning"])
            st.write(f"{rule['threshold_formula']} · 训练覆盖率 {rule['train_hit_rate']:.1%} · {rule['points']} 分")
            st.code(rule["cypher_predicate"], language="cypher")
            st.json(rule["sample_hit_resumes"], expanded=False)
    sync = artifact(PROCESSED / "sync_check_report.json")
    if sync:
        st.subheader("固定测试候选人的两次评估")
        st.dataframe([{"训练快照": k[-1].upper(), "训练人数": sync[k]["train_size"],
                       "快照哈希": sync[k]["cohort_hash"]} for k in ("snapshot_a", "snapshot_b")],
                     hide_index=True, use_container_width=True)
        st.dataframe(sync["threshold_changes"], hide_index=True, use_container_width=True)
        for anchor in sync["anchors"]:
            with st.expander(f"锚点简历 {anchor['resume_id']}"):
                rows = [{"训练快照": name.upper(), "维度": label, "得分": anchor[name]["scores"][dim],
                         "等级": anchor[name]["grades"][dim]} for dim, label in DIMS.items() for name in ("a", "b")]
                st.dataframe(rows, hide_index=True)
                st.json({k: anchor[k]["hit_rules"] for k in ("a", "b")})
    focus = PROCESSED / "focus_profiles"
    paths = sorted(focus.glob("*.json"))
    if paths:
        st.subheader("重点简历画像")
        path = st.selectbox("画像简历", paths, format_func=lambda p: p.stem)
        profile = artifact(path)
        left, right = st.columns([1, 1])
        if path.with_suffix(".png").is_file():
            left.image(str(path.with_suffix(".png")))
        with right:
            st.dataframe([{"维度": name, "得分": profile["scores"][dim], "等级": profile["grades"][dim]}
                          for dim, name in DIMS.items()], hide_index=True)
            for insight in profile["analysis"]:
                st.write(insight)
        for rule, examples in profile["rule_evidence"].items():
            with st.expander(f"{rule} · 原文证据"):
                for e in examples:
                    show_evidence(e)
        if path.with_suffix(".md").exists():
            st.download_button("下载完整评估报告", path.with_suffix(".md").read_bytes(), file_name=path.with_suffix(".md").name)

def query_tab(driver, docs):
    st.header("测试集岗位检索")
    mode = st.radio("岗位需求", ["主展示查询", "零命中边界", "自定义"], horizontal=True)
    if mode == "自定义":
        query = st.text_input("百字内中文需求", value=MAIN_QUERY, max_chars=100)
        st.caption("可写技能、最低学历、最低工作年限，以及项目经验、实证技能占比或加分技能偏好。多条条件用逗号分隔。")
    else:
        query = MAIN_QUERY if mode == "主展示查询" else ZERO_QUERY
        st.write(query)
    st.caption(f"{len(query)} / 100 字")
    if not driver or not docs:
        st.info("请先连接 Neo4j 并完成数据入库与规则评估。")
        return
    try:
        report = execute_query(query, driver)
    except (ValueError, ServiceUnavailable, SessionExpired, Neo4jError) as exc:
        st.warning(str(exc))
        return
    with st.expander("硬条件、排序偏好与可执行 Cypher"):
        ir = report["ir"]
        st.caption("每个必选技能组至少命中一项，所有组和最低学历、净工龄均须满足。")
        st.json({"MUST": {k: ir[k] for k in ("must_skills", "min_degree_level", "min_exp_years")},
                 "PREFER": {k: ir[k] for k in ("prefer_signals", "prefer_skills")}})
        st.code(report["browser_cypher"], language="cypher")
    hits, near = report["strict_matches"], report["near_misses"]
    st.subheader(f"严格命中 · {len(hits)} 人")
    if hits:
        chosen = st.selectbox("查看命中候选人", hits, format_func=lambda c: c["resume_id"])
        doc = docs[chosen["resume_id"]]
        st.write(f"{DEGREE_NAMES[chosen['degree_level']]} · 净工龄 {chosen['merged_exp_months']} 个月 · "
                 f"{chosen['project_count']} 段项目 · 实证技能占比 {chosen['verified_skill_ratio']:.1%}")
        read_pdf_link(chosen, "match-pdf")
        with st.expander("硬条件与加分项原文"):
            for e in chosen["skill_evidence"]:
                show_evidence(e)
            for items in chosen.get("threshold_evidence", {}).values():
                for e in items:
                    show_evidence(e)
        with st.expander("逐页原文"):
            for page in doc["pages"]:
                st.caption(f"第 {page['page_num']} 页")
                st.text(page["text"])
    else:
        st.info("测试集中没有同时满足全部硬条件的候选人。")
    st.subheader(f"近似候选 · {len(near)} 人")
    if near:
        st.dataframe([{"简历": c["resume_id"], "缺失硬条件": "；".join(c["missing_conditions"])}
                      for c in near], hide_index=True, use_container_width=True)
    if mode == "主展示查询" and len(hits) >= 3:
        st.subheader("前三位严格命中候选人")
        top = hits[:3]
        st.dataframe(comparison_rows(top), hide_index=True, use_container_width=True)
        st.write(comparison_conclusion(top))
        saved = artifact(PROCESSED / "query_reports/main.json")
        chart = PROCESSED / "query_reports/comparison.png"
        saved_scores = [(c["resume_id"], c["scores"]) for c in saved.get("strict_matches", [])[:3]]
        if chart.is_file() and saved_scores == [(c["resume_id"], c["scores"]) for c in top]:
            st.image(str(chart), width=510)
        for c in top:
            with st.expander(c["resume_id"] + " · 岗位适配与面试建议"):
                st.write(recommendation(c))
                for e in c["skill_evidence"][:2] + c["project_evidence"][:1]:
                    show_evidence(e)

def main():
    st.title("简历知识图谱")
    st.caption("从原始 PDF 到岗位检索 · 训练集标定与测试集评估")
    try:
        driver = connection()
        stats = graph_stats(driver)
    except (ServiceUnavailable, SessionExpired, Neo4jError, OSError) as exc:
        driver, stats = None, {}
        st.sidebar.error(f"Neo4j 无法连接 · {type(exc).__name__}")
    if stats:
        st.sidebar.success("Neo4j 已连接")
        for scope, name in (("train", "训练子图"), ("test", "测试子图")):
            volume = stats[scope]
            st.sidebar.metric(name + "节点", volume["node_count"])
            st.sidebar.caption(f"{volume['relationship_count']} 条关系")
    manifest = artifact(ROOT / "data/extracted_txt/manifest.json")
    docs = {d["resume_id"]: d for d in manifest.get("documents", [])}
    selected = st.sidebar.selectbox("原文与抽取记录", docs, format_func=lambda rid:
                                    f"{rid} · {docs[rid]['split']}") if docs else None
    tabs = st.tabs(["采 · 数据准备", "治 · 抽取与溯源", "存 · 图谱治理", "算 · 规则与画像", "用 · 岗位检索"])
    with tabs[0]:
        collection(docs.get(selected), manifest)
    with tabs[1]:
        extraction(docs.get(selected))
    with tabs[2]:
        graph_tab(stats)
    with tabs[3]:
        rules_tab()
    with tabs[4]:
        query_tab(driver, docs)

if __name__ == "__main__":
    main()
