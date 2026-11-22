"""多页面共用的数据读取、上下文和导航组件。"""
from __future__ import annotations

import html
import json
from pathlib import Path

import streamlit as st

from src.ui_theme import evidence_card_html

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data/processed"


@st.cache_data(show_spinner=False)
def _read_json(path: str, modified: int):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def artifact(path: Path) -> dict:
    if not path.is_file():
        return {}
    return _read_json(str(path), path.stat().st_mtime_ns)


def render_canvas(markup: str, height: int):
    st.iframe(markup, width="stretch", height=height)


def read_pdf_link(doc: dict, key: str):
    path = ROOT / doc["pdf_path"]
    if path.is_file():
        st.download_button("下载 PDF", path.read_bytes(), file_name=path.name,
                           mime="application/pdf", icon=":material/download:", key=key)


def show_evidence_card(e: dict):
    st.html(evidence_card_html(e))


def open_source(resume_id: str):
    st.session_state["selected_resume"] = resume_id
    st.switch_page(st.session_state["kg_pages"]["source"])


def resume_picker(docs: dict, current_page: str):
    if not docs:
        return None
    ids = list(docs)
    selected = st.session_state.get("selected_resume", "cv-486c4ba1bcae")
    key = f"resume_picker_{current_page}"
    # 跳转目标优先于上次停留在本页时的控件值。
    if selected not in docs:
        selected = ids[0]
    st.session_state[key] = selected

    def remember():
        st.session_state["selected_resume"] = st.session_state[key]

    rid = st.selectbox("当前简历", ids, key=key, on_change=remember,
                       format_func=lambda r: f"{r} · {'测试集' if docs[r]['split'] == 'test' else '训练集'}")
    st.session_state["selected_resume"] = rid
    return docs[rid]


def page_header(stage, number: int, docs: dict):
    if stage.path in {"source", "extract"}:
        title_area, picker_area = st.columns([1.75, 1], vertical_alignment="center", gap="medium")
    else:
        title_area, picker_area = st.container(), None
    with title_area:
        st.html(f'<header class="kg-section"><div class="kg-eyebrow">步骤 {number:02d} / 05'
                f'<span></span>{stage.mark} · {stage.name}</div><h1>{stage.title}</h1>'
                f'<p>{stage.subtitle}</p></header>')
    if picker_area is not None:
        with picker_area:
            return resume_picker(docs, stage.path)
    return None


def page_footer(order, pages, current):
    i = order.index(current)
    st.divider()
    with st.container(key="stage_footer", horizontal=True, horizontal_alignment="distribute"):
        prev = order[i-1]
        st.page_link(pages[prev], label=f"上一步 · {pages[prev].title}", icon=":material/arrow_back:")
        following = order[i+1] if i < len(order)-1 else "home"
        label = f"下一步 · {pages[following].title}" if following != "home" else "返回概览"
        st.page_link(pages[following], label=label, icon=":material/arrow_forward:", icon_position="right")


def metric_strip(items):
    cells = []
    for label, value in items:
        text = "—" if value is None else f"{value:,}" if isinstance(value, int) else str(value)
        cells.append(f'<div><dt>{html.escape(label)}</dt><dd>{html.escape(text)}</dd></div>')
    st.html('<dl class="kg-facts">' + "".join(cells) + '</dl>')
