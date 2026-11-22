"""Persist this project's eight domain labels and count directed candidate subgraphs."""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
import hashlib
import json
import os
from uuid import uuid4

from neo4j import GraphDatabase

from .config import PROCESSED

OWNER = "ism2026hw2_resume_graph"
LABELS = {
    "Candidate", "WorkExperience", "Company", "JobTitle", "Education",
    "University", "Skill", "Project",
}
SCHEMA = {
    "HAS_EXPERIENCE": ("Candidate", "WorkExperience"),
    "AT_COMPANY": ("WorkExperience", "Company"),
    "HELD_ROLE": ("WorkExperience", "JobTitle"),
    "USED_SKILL": ("WorkExperience", "Skill"),
    "HAS_EDUCATION": ("Candidate", "Education"),
    "AT_UNIVERSITY": ("Education", "University"),
    "HAS_SKILL": ("Candidate", "Skill"),
    "WORKED_ON": ("Candidate", "Project"),
    "APPLIED_SKILL": ("Project", "Skill"),
}


def get_driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password123")),
        connection_timeout=8,
    )


@contextmanager
def connection(driver=None):
    if driver is None:
        with get_driver() as owned:
            yield owned
    else:
        yield driver


def properties(entry):
    return entry.get("properties", entry.get("props", {}))


def _graph_batches(graph):
    by_label, by_type, labels = defaultdict(list), defaultdict(list), {}
    for node in graph["nodes"]:
        key, label = node["id"], node["label"]
        if key in labels or label not in LABELS or not key:
            raise ValueError(f"Unexpected label or duplicate node: {label} {key}")
        labels[key] = label
        by_label[label].append({"id": key, "props": properties(node)})
    for edge in graph["edges"]:
        src = edge.get("source", edge.get("src"))
        dst = edge.get("target", edge.get("dst"))
        rel, props = edge["type"], properties(edge)
        if rel not in SCHEMA or (labels.get(src), labels.get(dst)) != SCHEMA[rel]:
            raise ValueError(f"Invalid edge: {src} {rel} {dst}")
        # Distinct occurrences remain individually addressable across reruns.
        evidence_key = [src, rel, dst, props]
        content = json.dumps(evidence_key, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        by_type[rel].append({"src": src, "dst": dst, "props": props,
                             "key": hashlib.sha256(content.encode()).hexdigest()})
    if not by_label["Candidate"]:
        raise ValueError("Empty cohort: refusing to replace the project graph")
    return by_label, by_type


def _replace(tx, nodes, edges, token):
    # The lock serializes complete snapshot replacements. It is outside the domain graph.
    tx.run("MERGE (l:ResumeKGWriteLock {id:$owner}) SET l.token=$token",
           owner=OWNER, token=token).consume()
    foreign = tx.run("""
        UNWIND $ids AS id MATCH (n:ResumeKG {id:id})
        WHERE n.kg_owner IS NULL OR n.kg_owner <> $owner
        RETURN n.id LIMIT 1
        """, ids=[row["id"] for group in nodes.values() for row in group], owner=OWNER).single()
    if foreign is not None:
        raise ValueError("A foreign graph already uses a required ResumeKG identifier")
    for label, rows in nodes.items():
        # Record indices may change domain type after improved segmentation.
        obsolete_labels = ":".join(sorted(LABELS - {label}))
        for i in range(0, len(rows), 500):
            tx.run(f"""
                UNWIND $rows AS row MERGE (n:ResumeKG {{id:row.id}})
                REMOVE n:{obsolete_labels}
                SET n:{label}, n = row.props, n.id=row.id, n.kg_owner=$owner, n.kg_snapshot=$token
                """, rows=rows[i:i+500], owner=OWNER, token=token).consume()
    for rel, rows in edges.items():
        for i in range(0, len(rows), 500):
            tx.run(f"""
                UNWIND $rows AS row
                MATCH (a:ResumeKG {{id:row.src}}), (b:ResumeKG {{id:row.dst}})
                MERGE (a)-[r:{rel} {{kg_key:row.key}}]->(b)
                SET r = row.props, r.kg_key=row.key, r.kg_owner=$owner, r.kg_snapshot=$token
                """, rows=rows[i:i+500], owner=OWNER, token=token).consume()
    tx.run("MATCH (:ResumeKG)-[r]->(:ResumeKG) WHERE r.kg_owner=$owner "
           "AND r.kg_snapshot <> $token DELETE r", owner=OWNER, token=token).consume()
    # DELETE (without DETACH) deliberately rolls back if a foreign relationship
    # points to a stale project node.
    tx.run("MATCH (n:ResumeKG) WHERE n.kg_owner=$owner AND n.kg_snapshot <> $token DELETE n",
           owner=OWNER, token=token).consume()


def load_graph(driver=None, graph=None):
    if graph is None:
        graph = json.loads((PROCESSED / "resolved_kg.json").read_text())
    nodes, edges = _graph_batches(graph)
    with connection(driver) as db, db.session() as session:
        session.run("CREATE CONSTRAINT resume_kg_id IF NOT EXISTS "
                    "FOR (n:ResumeKG) REQUIRE n.id IS UNIQUE").consume()
        session.run("CREATE CONSTRAINT resume_kg_lock IF NOT EXISTS "
                    "FOR (n:ResumeKGWriteLock) REQUIRE n.id IS UNIQUE").consume()
        session.run("CREATE INDEX resume_kg_split IF NOT EXISTS FOR (n:Candidate) ON (n.split)").consume()
        session.execute_write(_replace, nodes, edges, uuid4().hex)
        return graph_stats(db)


def graph_stats(driver=None):
    """All scope counts the union; shared skills and employers count once per scope."""
    out = {}
    rel_types = "|".join(SCHEMA)
    with connection(driver) as db, db.session() as session:
        for scope in ("train", "test", "all"):
            candidates = "MATCH (c:ResumeKG:Candidate {kg_owner:$owner}) "
            if scope != "all":
                candidates += "WHERE c.split=$scope "
            params = {"scope": scope, "owner": OWNER}
            def grouped(query):
                return {r["kind"]: r["n"] for r in session.run(candidates + query, **params)}
            nodes = grouped(f"""
                MATCH p=(c)-[:{rel_types}*0..2]->(n:ResumeKG)
                WHERE ALL(e IN relationships(p) WHERE e.kg_owner=$owner)
                WITH DISTINCT n UNWIND [k IN labels(n) WHERE k <> 'ResumeKG'] AS kind
                RETURN kind,count(*) AS n ORDER BY kind
                """)
            edges = grouped(f"""
                MATCH p=(c)-[:{rel_types}*1..2]->(:ResumeKG)
                WHERE ALL(e IN relationships(p) WHERE e.kg_owner=$owner)
                UNWIND relationships(p) AS r
                RETURN type(r) AS kind,count(DISTINCT r) AS n ORDER BY kind
                """)
            out[scope] = dict(node_count=sum(nodes.values()), relationship_count=sum(edges.values()),
                              nodes=nodes, relationships=edges)
    return out
