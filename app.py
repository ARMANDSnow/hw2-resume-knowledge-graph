"""运行方式：.venv/bin/streamlit run app.py"""
import streamlit as st
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired

from src.pages_ import extract, graph, home, rules, search, source
from src.stage3_neo4j import get_driver, graph_stats
from src.ui_copy import STAGES
from src.ui_layout import PROCESSED, ROOT, artifact, page_footer, page_header
from src.ui_theme import theme_css

st.set_page_config(page_title="简历图谱 · Resume KG", page_icon=":material/hub:", layout="wide")


@st.cache_resource(show_spinner=False)
def connection():
    return get_driver()


@st.cache_data(ttl=15, show_spinner=False)
def database_status():
    try:
        return True, graph_stats(connection())
    except (ServiceUnavailable, SessionExpired, Neo4jError, OSError):
        return False, {}


def main():
    st.html(theme_css())
    manifest = artifact(ROOT / "data/extracted_txt/manifest.json")
    docs = {doc["resume_id"]: doc for doc in manifest.get("documents", [])}
    acceptance = artifact(PROCESSED / "acceptance_report.json")
    online, stats = database_status()
    if not online:
        stats = acceptance.get("checks", {}).get("AC-4", {}).get("metrics", {})

    def overview():
        home.render(manifest, stats, acceptance, pages)

    def render_stage(stage, number):
        def render():
            doc = page_header(stage, number, docs)
            if stage.path == "source":
                source.render(doc, manifest)
            elif stage.path == "extract":
                extract.render(doc, artifact(PROCESSED / "resolved_kg.json"))
            elif stage.path == "graph":
                graph.render(stats, artifact(PROCESSED / "resolved_kg.json"))
            elif stage.path == "rules":
                rules.render()
            else:
                search.render(connection() if online else None, docs)
            page_footer(list(pages), pages, stage.path)
        return render

    pages = {"home": st.Page(overview, title="概览", icon=":material/space_dashboard:", default=True)}
    for i, stage in enumerate(STAGES, start=1):
        pages[stage.path] = st.Page(render_stage(stage, i), title=f"{stage.mark} · {stage.name}",
                                    icon=f":material/{stage.icon}:", url_path=stage.path)
    page = st.navigation(list(pages.values()), position="hidden")
    st.session_state["kg_pages"] = pages
    st.html(f'''<style>[data-testid="stSidebar"] a[href="{page.url_path}"] {{
        background:var(--accent-soft);color:var(--accent-dark);
    }} [data-testid="stSidebar"] a[href="{page.url_path}"] [data-testid="stIconMaterial"] {{
        color:var(--accent-dark);
    }}</style>''')

    with st.sidebar, st.container(key="sidebar_body"):
        st.html('<div class="kg-brand"><span class="kg-mark" aria-hidden="true"><i></i><i></i><i></i></span>'
                '<div><strong>简历图谱</strong><small>Resume KG</small></div></div>')
        st.page_link(pages["home"], width="stretch")
        st.html('<div class="kg-nav-heading">研究流程</div>')
        for stage in STAGES:
            st.page_link(pages[stage.path], label=f"**{stage.mark} · {stage.name}**  \n{stage.description}", width="stretch")
        with st.container(key="connection_status"):
            status = "Neo4j 已连接" if online else "Neo4j 离线 · 已保存的快照"
            style = "online" if online else "offline"
            st.html(f'<div class="kg-status {style}">{status}</div>')
            if online:
                st.link_button("打开 Neo4j Browser", "http://localhost:7474", icon=":material/open_in_new:")
    page.run()


if __name__ == "__main__":
    main()
