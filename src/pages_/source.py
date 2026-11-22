import html

import streamlit as st

from src.ui_layout import PROCESSED, read_pdf_link, render_canvas
from src.ui_visuals import render_funnel_html


def render(doc: dict | None, manifest: dict):
    if not manifest or not doc:
        st.info("完成采集后，就可以在这里翻阅样本。")
        return
    render_canvas(render_funnel_html(manifest), height=320)

    left, right = st.columns([1.6, 1], gap="large")
    with left:
        st.markdown('<h3 class="kg-subhead">原文阅读</h3>', unsafe_allow_html=True)
        pages = doc["pages"]
        if not pages:
            st.info("这份简历尚未保存逐页原文。")
            return
        page_col, download_col = st.columns([1.2, 1], vertical_alignment="bottom")
        page_index = page_col.selectbox(
            "简历页码", range(len(pages)),
            format_func=lambda i: f"第 {pages[i]['page_num']} 页 / 共 {len(pages)} 页",
            key=f"source_page_{doc['resume_id']}", persist_state="session",
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
        st.markdown('<h3 class="kg-subhead">重复简历排查</h3>', unsafe_allow_html=True)
        counts = manifest.get("corpus_counts", {})
        rows = [
            ("文件内容相同", counts.get("duplicate_file", 0)),
            ("规范化文本相同", counts.get("duplicate_text", 0)),
            ("近重复版本", sum(len(g["excluded"]) for g in manifest.get("near_duplicate_groups", []))),
        ]
        entries = "".join(f"<div><dt>{label}</dt><dd>{value:,} 份</dd></div>" for label, value in rows)
        st.markdown(f'<dl class="kg-audit-list">{entries}</dl>', unsafe_allow_html=True)
        with st.expander("查看快照与文件指纹"):
            for label, value in (("样本 SHA-256", manifest["cohort_hash"]), ("文件 SHA-256", doc["file_hash"]), ("文本 SHA-256", doc["text_hash"])):
                st.caption(label)
                st.code(value, language=None, wrap_lines=True)
            st.caption(doc["pdf_path"])
        for label, filename in (("试点简历复核", "pilot_review_notes.md"), ("试点核对明细", "pilot_audit.md")):
            path = PROCESSED / filename
            if path.exists():
                with st.expander(label):
                    st.markdown(path.read_text(encoding="utf-8").replace("消岐", "消歧"))
