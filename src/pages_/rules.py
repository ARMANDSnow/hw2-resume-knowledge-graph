"""Show the rules and the resume evidence used to compute each score."""
import html

import streamlit as st

from src.stage4_rules import group_rule_evidence
from src.stage5_query import DIMS
from src.ui_layout import PROCESSED, artifact, render_canvas, show_evidence_card
from src.ui_theme import evidence_card_html
from src.ui_visuals import render_interactive_radar_html, render_sync_morph_html


_RULE_STYLES = """
<style>
.kg-rule {border-top:1px solid var(--line, #e8e6dc);color:var(--ink, #1f1e1d)}
.kg-rule:last-of-type {border-bottom:1px solid var(--line, #e8e6dc)}
.kg-rule summary {display:flex;align-items:center;gap:.8rem;list-style:none;cursor:pointer;padding:.68rem 0;font-size:.9rem}
.kg-rule summary::-webkit-details-marker {display:none}
.kg-rule summary strong {flex:1;font-weight:550}
.kg-rule summary small {color:var(--ink-2, #5e5d59);font-size:.78rem;font-variant-numeric:tabular-nums}
.kg-rule summary::after {content:"⌄";width:1rem;text-align:center;color:var(--ink-2, #5e5d59)}
.kg-rule[open] summary::after {transform:rotate(180deg)}
.kg-rule .rate {width:clamp(30px,7vw,75px);height:4px;border-radius:4px;background:var(--line, #e8e6dc);overflow:hidden}
.kg-rule .rate i {display:block;height:100%;background:var(--accent, #c96442)}
.kg-rule .rate-number {min-width:3.1rem;text-align:right}
.kg-rule-body {padding:.15rem 0 1rem}
.kg-rule-body p {margin-bottom:.4rem}
.kg-rule-body pre {white-space:pre-wrap;overflow-wrap:anywhere}
</style>
"""


def _rule_row(rule, train_size):
    rate = rule["train_hit_rate"]
    title = html.escape(rule["title"].replace("实证技能", "经历中用过的技能"))
    summary = (
        f'<summary><strong>{title}</strong><small>+{rule["points"]} 分</small>'
        f'<span class="rate" aria-hidden="true"><i style="width:{rate:.2%}"></i></span>'
        f'<small class="rate-number" aria-label="训练集命中率 {rate:.1%}">{rate:.1%}</small></summary>'
    )
    evidence = "".join(evidence_card_html(example) for example in rule.get("sample_hit_resumes", [])[:4])
    return (
        f'<details class="kg-rule">{summary}<div class="kg-rule-body">'
        f'<p>{html.escape(rule["business_meaning"])}</p><p>训练样本中有 {rule["train_hit_count"]} / '
        f'{train_size} 人达到这条规则的门槛。</p><p>{html.escape(rule["threshold_formula"])}</p>'
        f'<pre><code>{html.escape(rule["cypher_predicate"])}</code></pre>{evidence}</div></details>'
    )


def _profile():
    paths = sorted((PROCESSED / "focus_profiles").glob("*.json"))
    if not paths:
        st.info("尚未生成重点简历的评分报告。")
        return
    path = st.selectbox(
        "选择候选人", paths, format_func=lambda item: item.stem,
        key="rules_profile", persist_state="session",
    )
    profile = artifact(path)
    chart, description = st.columns([1, 1.25], gap="large")
    with chart:
        series = [{"name": profile["resume_id"], "scores": profile["scores"],
                   "grades": profile["grades"], "color": "#AF634A"}]
        render_canvas(render_interactive_radar_html(series, title="四个维度的得分", height=335), height=340)
    with description:
        for col, (dimension, label) in zip(st.columns(4), DIMS.items()):
            col.metric(f"{label} · {profile['grades'][dimension]} 级", profile["scores"][dimension])
        for insight in profile.get("analysis", []):
            st.markdown(f"- {insight}")
        report = path.with_suffix(".md")
        if report.is_file():
            st.download_button("下载评分报告", report.read_bytes(), file_name=report.name,
                               key=f"download-profile-{profile['resume_id']}")
    st.markdown("#### 得分对应的原句")
    for rule_id, examples in profile.get("rule_evidence", {}).items():
        grouped = group_rule_evidence(examples)
        with st.expander(f"{rule_id} · {len(grouped)} 条原文"):
            if len(grouped) > 12:
                st.caption("这里列出前 12 条，其余原句可在评分报告中阅读。")
            for evidence in grouped[:12]:
                card = dict(evidence)
                if card.get("skills"):
                    card["skill"] = " / ".join(card["skills"])
                show_evidence_card(card)


def render():
    model = artifact(PROCESSED / "rules_model.json")
    if not model:
        st.info("评分规则还未生成。完成训练集规则计算后，即可查看各维度的门槛。")
        return

    dimension = st.pills("评估维度", list(DIMS), format_func=DIMS.get, default="EDU", required=True,
                         key="rules_dimension", persist_state="session")
    st.caption("每行右侧显示训练样本达到该规则的比例。展开可查看门槛和简历原句。")
    rows = "".join(_rule_row(rule, model["train_size"]) for rule in model["rules"]
                   if rule["rule_id"].startswith(f"R-{dimension}-"))
    st.html(_RULE_STYLES + rows)

    snapshot, profile = st.tabs(["训练快照对比", "重点简历画像"], key="rules_view", on_change="rerun")
    if snapshot.open:
        with snapshot:
            sync = artifact(PROCESSED / "sync_check_report.json")
            if sync:
                st.caption(f"切换两批训练样本，可以查看 {len(sync.get('threshold_changes', []))} 条规则的门槛变化，以及同一批候选人重新评分的结果。")
                render_canvas(render_sync_morph_html(sync), height=410)
            else:
                st.info("尚未保存两批训练样本的对比结果。")
    else:
        with profile:
            _profile()
