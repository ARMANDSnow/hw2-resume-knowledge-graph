#!/usr/bin/env python3
"""Independent artifact and live graph checks. Exit nonzero if any criterion fails."""
import argparse
import json
import re
import subprocess
import sys
import zipfile
from collections import Counter
from functools import cached_property
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import MANIFEST, PROCESSED, ROOT, read_json, write_json
from src.provenance import normalize_text, sha256, validate_quote
from src.stage1_collect import pdf_pages, page_boundaries
from src.stage3_neo4j import OWNER, SCHEMA, get_driver, graph_stats

NAME = "ISM2026HW2-524031910745丁宇轩"
PACKAGE = ROOT / "dist" / (NAME + ".zip")
AC = PROCESSED / "acceptance_report.json"
DOC = ROOT / "docs/技术说明文档.md"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def png(path):
    from PIL import Image
    with Image.open(path) as im:
        require(im.format == "PNG" and min(im.size) >= 240, f"invalid figure {path.name}")
        im.verify()


class Audit:
    def __init__(self, driver):
        self.driver = driver

    def rows(self, query, **params):
        with self.driver.session() as session:
            return session.run(query, owner=OWNER, **params).data()

    @cached_property
    def manifest(self):
        return read_json(MANIFEST)

    @cached_property
    def docs(self):
        return {d["resume_id"]:d for d in self.manifest["documents"]}

    @cached_property
    def kg(self):
        return read_json(PROCESSED/"resolved_kg.json")

    @cached_property
    def edges(self):
        return self.rows("MATCH (a:ResumeKG)-[r]->(b:ResumeKG) WHERE r.kg_owner=$owner "
                         "RETURN a.id AS source, b.id AS target, type(r) AS type, properties(r) AS p")

    @cached_property
    def cand(self):
        return {c["p"]["resume_id"]:c["p"] for c in self.rows(
            "MATCH (c:ResumeKG:Candidate {kg_owner:$owner}) RETURN properties(c) AS p")}

    def quote_ok(self, e, rid=None):
        rid = e.get("resume_id", rid)
        page = e.get("page_num", 0)
        return (rid in self.docs and isinstance(page,int) and 1 <= page <= len(self.docs[rid]["pages"])
                and validate_quote(self.docs[rid]["pages"][page-1]["text"],e.get("evidence_quote")))

    def ac1(self):
        from src.cli import reviewed
        from src.pilot_audit import review_ready
        require(Path(sys.prefix).resolve() == (ROOT/".venv").resolve() and sys.version_info[:2] == (3,11),
                "请使用工程 .venv 的 Python 3.11")
        server = self.driver.get_server_info()
        require(server.agent.startswith("Neo4j/5."), server.agent)
        reviewed()
        manifest = read_json(PROCESSED/"pilot_manifest.json")
        graph = read_json(PROCESSED/"pilot_graph.json")
        review_ready(manifest, graph)
        return dict(python=sys.version.split()[0], database=server.agent, pilot_count=len(graph["documents"]),
                    pilot_layout_signatures=len({tuple(d["layout"]+[d["explicit_projects"]]) for d in manifest["documents"]}),
                    pilot_records=sum(len(d["records"]) for d in graph["documents"]), pilot_edges=len(graph["edges"]),
                    pilot_cohort_hash=manifest["cohort_hash"], model=graph["model"])

    def ac2(self):
        docs = self.manifest["documents"]
        n = Counter(d["split"] for d in docs)
        require(n == {"train":60, "test":20} and len(self.docs)==80, "固定快照并非 60/20")
        for d in docs:
            original = (ROOT/d["pdf_path"]).read_bytes()
            pages = pdf_pages(original)
            text = "\n".join(pages)
            require(page_boundaries(pages)==d["pages"] and (ROOT/d["text_path"]).read_bytes()==text.encode(),
                    "PDF 逐页原文或偏移不符 "+d["resume_id"])
            require(d["file_hash"] == sha256(original) and d["text_hash"] == sha256(normalize_text(text)),
                    "哈希不符 "+d["resume_id"])
        for key in ("text_hash","file_hash"):
            require(len({d[key] for d in docs})==len(docs), "重复 "+key)
        for split in n:
            require(self.manifest[split+"_hashes"] == [d["text_hash"] for d in docs if d["split"]==split], "哈希清单不符")
        require(self.manifest["cohort_hash"]==sha256("\n".join(d["split"]+":"+d["text_hash"] for d in docs)),"快照签名不符")
        return dict(**n, pages=sum(len(d["pages"]) for d in docs), file_hash_overlap=0,text_hash_overlap=0,
                    cohort_hash=self.manifest["cohort_hash"],dedup_removed_count=self.manifest["dedup_removed_count"],
                    eligible=self.manifest["eligible"],corpus=self.manifest["corpus_counts"])

    def ac3(self):
        extraction = read_json(PROCESSED/"extractions.json")
        records = {}
        for d in extraction["documents"]:
            doc = self.docs[d["resume_id"]]
            for r in d["records"]:
                page = doc["pages"][r["page_num"]-1]
                require(page["text"][r["page_start"]:r["page_end"]]==r["record_text"] and
                        r["char_start"]==page["char_start"]+r["page_start"], "记录偏移不符 "+r["record_id"])
                records[r["record_id"]] = r
        mentions = sum(len(r["entities"]) for r in records.values())
        require(mentions > 0 and extraction.get("model","").startswith("urchade/gliner_"), "缺少真实模型抽取")
        verified = {(e["p"]["record_id"],e["target"],e["p"]["evidence_quote"],e["type"]) for e in self.edges}
        kinds = {"AT_COMPANY":"WorkRecord","HELD_ROLE":"WorkRecord","USED_SKILL":"WorkRecord",
                 "AT_UNIVERSITY":"EduRecord","APPLIED_SKILL":"ProjectRecord"}
        relevant = [e for e in self.edges if e["type"] in {*kinds,"HAS_SKILL"}]
        require(set(e["type"] for e in relevant)=={*kinds,"HAS_SKILL"}, "缺少核心关系类型")
        valid = 0
        for e in relevant:
            p = e["p"]
            r = records[p["record_id"]]
            require(r["page_num"]==p["page_num"] and len(p["evidence_quote"])<=240 and
                    validate_quote(r["record_text"],p["evidence_quote"]) and validate_quote(p["evidence_quote"], p["surface"]),
                    "证据或实体不在记录内 "+p["record_id"])
            typ = e["type"]
            if typ in kinds:
                require(kinds[typ]==r["kind"] and e["source"]==p["record_id"],"跨记录连边 "+p["record_id"])
            else:
                require(e["source"]==p["resume_id"] and r["kind"] in
                        {"listed":{"SKILLS","PROFILE"},"project_verified":{"ProjectRecord"},
                         "work_verified":{"WorkRecord"}}.get(p["source"],{}), "技能来源不符 "+p["record_id"])
                if p["source"] != "listed":
                    rel = "USED_SKILL" if p["source"] == "work_verified" else "APPLIED_SKILL"
                    require((p["record_id"],e["target"],p["evidence_quote"],rel) in verified,
                            "实证 HAS_SKILL 缺少对应记录边 "+p["record_id"])
            valid += bool(p["evidence_valid"] and self.quote_ok(p))
        require(valid/len(relevant)>=.95, "引文校验率低于 95%")
        return dict(records=len(records),gliner_mentions=mentions,
                    key_edges=len(relevant),valid_quotes=valid,quote_valid_rate=valid/len(relevant),
                    cross_record_errors=0,relation_counts=dict(Counter(e["type"] for e in relevant)))

    def ac4(self):
        stats = graph_stats(self.driver)
        train = stats["train"]
        require(train["node_count"]>=100 and train["relationship_count"]>=150 and
                set(train["relationships"]) == set(SCHEMA), "训练子图规模或覆盖不足")
        require(set(self.cand)==set(self.docs) and all(c["split"]==self.docs[k]["split"] for k,c in self.cand.items()),
                "Neo4j 候选人集合与快照不一致")
        require(stats["all"]["node_count"]==len(self.kg["nodes"]) and
                stats["all"]["relationship_count"]==len(self.kg["edges"]), "数据库与提交的规范图不一致")
        return stats

    def ac5(self):
        groups = self.kg["disambiguation_groups"]
        coref = self.kg["coref_audit"]
        targets = {(e["source"],e["type"],e["target"],e["p"]["resume_id"],e["p"]["evidence_quote"]) for e in self.edges}
        train = {k for k,d in self.docs.items() if d["split"]=="train"}
        for g in groups:
            senses = g["senses"]
            require(len({s["node_id"] for s in senses})>=2, "义项目标未分开")
            for s in senses:
                require(s["resume_id"] in train and self.quote_ok(s) and normalize_text(g["surface"]) in
                        normalize_text(s["evidence_quote"]) and s["scores"] and
                        (s["edge_source"],s["edge_type"],s["node_id"],s["resume_id"],s["evidence_quote"]) in targets,
                        "双边消岐证据或图谱连边不符 "+g["surface"])
        aliases, chains, controls = (coref[k] for k in ("cross_document_groups","within_document_chains","negative_controls"))
        require(len({g["surface"].casefold() for g in groups})>=2 and aliases and chains and len(controls)>=2,
                "消岐、跨文档别名、文内指代或反例数不足")
        linked = {(e["target"],e["p"]["resume_id"],e["p"]["evidence_quote"]) for e in self.edges}
        ids = {r["id"] for r in self.rows("MATCH (n:ResumeKG {kg_owner:$owner}) RETURN n.id AS id")}
        for g in aliases:
            ex = g["examples"]
            require(len({e["resume_id"] for e in ex})>=2 and len({normalize_text(e["alias"]) for e in ex})>=2
                    and all(self.quote_ok(e) and (g["node_id"],e["resume_id"],e["evidence_quote"]) in linked for e in ex),
                    "跨文档融合证据不符 "+g["node_id"])
        for ch in chains:
            require(ch["node_id"] in ids and self.quote_ok(ch) and validate_quote(ch["evidence_quote"],ch["surface"]),
                    "指代缺少原句或先行实体")
        for pair in controls:
            require(len(set(pair["node_ids"]))==2 and set(pair["node_ids"])<=ids and all(self.quote_ok(e)
                    and (uid,e["resume_id"],e["evidence_quote"]) in linked for uid,e in zip(pair["node_ids"],pair["examples"])),
                    "反例未在图中保持分离")
        return dict(verified_groups=len(groups),surfaces=[g["surface"] for g in groups],alias_groups=len(aliases),
                    reference_chains=len(chains),negative_controls=len(controls),noise_pruned=len(self.kg["noise_pruned_mentions"]),
                    nodes_before=coref["nodes_before"],nodes_after=coref["nodes_after"],compression_ratio=coref["compression_ratio"])

    def ac6(self):
        from src.stage4_rules import fit, evaluate, raw_rows, compute_features
        model = read_json(PROCESSED/"rules_model.json")
        snapshot = read_json(PROCESSED/"sync_check_report.json")
        fresh = [compute_features(*row) for row in raw_rows(self.driver)]
        train = [r for r in fresh if r["split"]=="train"]
        rebuilt = fit(train)
        dimensions = ("EDU","EXP","SKL","POT")
        require(Counter(r["dimension"] for r in model["rules"])==dict.fromkeys(dimensions,4),"分维度规则数量不符")
        def signature(m):
            return (m["train_ids"],m["cohort_hash"],m["grade_thresholds"],
                    [(r["rule_id"],r["threshold"],r["train_hit_count"]) for r in m["rules"]])
        require(signature(rebuilt)==signature(model)==signature(snapshot["snapshot_b"]), "训练规则重算不符")
        for rule in model["rules"]:
            key = rule["feature"]
            require(re.fullmatch(r"[a-z_]+",key) and rule["threshold"] is not None, "无有效阈值")
            predicate = f"c.{key} >= {rule['threshold']!r}"
            require(predicate==rule["cypher_predicate"],"Cypher 条件不符")
            hits = self.rows("MATCH (c:ResumeKG:Candidate {kg_owner:$owner,split:'train'}) WHERE "+predicate+
                             " RETURN c.resume_id AS id")
            hit_ids = {r["id"] for r in hits}
            require(len(hits)==rule["train_hit_count"]>=1 and rule["business_meaning"] and rule["sample_hit_resumes"]
                    and all(self.quote_ok(e) and e["resume_id"] in hit_ids for e in rule["sample_hit_resumes"]),
                    "死规则、覆盖率或命中证据错误 "+rule["rule_id"])
        index = {r["resume_id"]:r for r in fresh}
        for rid,r in index.items():
            ev = evaluate(r["features"],model)
            c = self.cand[rid]
            require(all(c[k]==v for k,v in r["features"].items()) and set(ev["hit_rules"])==set(c["hit_rules"]) and
                    all(c["score_"+d.lower()]==ev["scores"][d] and c["grade_"+d.lower()]==ev["grades"][d]
                        for d in dimensions), "Neo4j 评级回写不符 "+rid)
        early = fit(sorted(train,key=lambda r:(r["features"]["merged_exp_months"],r["resume_id"]))[:len(train)//2])
        require(signature(snapshot["snapshot_a"])==signature(early) and early["cohort_hash"]!=model["cohort_hash"],
                "训练子集 A 不可复现")
        changes = {r["rule_id"] for r,s in zip(early["rules"],model["rules"]) if r["threshold"]!=s["threshold"]}
        require(changes and changes=={x["rule_id"] for x in snapshot["threshold_changes"]},"阈值变化不实")
        ids = sorted(k for k,v in self.docs.items() if v["split"]=="test")[:3]
        require(ids==[a["resume_id"] for a in snapshot["anchors"]],"测试锚点不固定")
        different = 0
        for a in snapshot["anchors"]:
            feats = index[a["resume_id"]]["features"]
            require(a["features"]==feats and a["a"]==evaluate(feats,early) and a["b"]==evaluate(feats,model),
                    "固定锚点评级无法复算")
            different += a["a"]["scores"]!=a["b"]["scores"] or a["a"]["grades"]!=a["b"]["grades"]
        require(different>=1, "固定锚点均无变化")
        profiles = sorted((PROCESSED/"focus_profiles").glob("*.json"))
        require(len(profiles)==3, "画像数量不符")
        for path in profiles:
            p=read_json(path)
            rid=p["resume_id"]
            png(path.with_suffix(".png"))
            require(path.with_suffix(".md").is_file() and path.stem==rid and p["scores"]==evaluate(index[rid]["features"],model)["scores"]
                    and set(p["rule_evidence"])==set(self.cand[rid]["hit_rules"]) and all(evs and all(self.quote_ok(e,rid)
                    for e in evs) for evs in p["rule_evidence"].values()), "画像内容、引文或雷达图不符 "+rid)
        return dict(rules_by_dimension=dict.fromkeys(dimensions,4),live_rules=len(model["rules"]),
                    minimum_train_hits=min(r["train_hit_count"] for r in model["rules"]),
                    snapshot_sizes=[len(early["train_ids"]),len(train)],threshold_changes=len(changes),
                    changed_anchors=different,focus_profiles=[p.stem for p in profiles])

    def ac7(self):
        from src.stage5_query import execute_query, MAIN_QUERY, ZERO_QUERY
        evidence = {k:set() for k in self.cand}
        nodes={n["id"]:n["properties"]["name"] for n in self.kg["nodes"]}
        for e in self.edges:
            if e["type"]=="HAS_SKILL" and e["p"]["evidence_valid"]:
                evidence[e["source"]].add(nodes[e["target"]])
        result = {}
        for key,query in (("main",MAIN_QUERY),("zero",ZERO_QUERY)):
            report = execute_query(query,self.driver)
            saved = read_json(PROCESSED/"query_reports"/(key+".json"))
            strict, near = report["strict_matches"], report["near_misses"]
            require(0<len(query)<=100 and "test"==report["scope"] and report["top3"]==saved["top3"] and
                    report["ir"]==saved["ir"] and query==saved["query"],"查询快照不符")
            strict_ids = {c["resume_id"] for c in strict}
            near_ids = {c["resume_id"] for c in near}
            require(not near_ids & strict_ids and near_ids|strict_ids=={rid for rid,c in self.cand.items() if c["split"]=="test"},
                    "严格/近似分区不完整")
            for part,rows in (("strict_matches",strict),("near_misses",near)):
                require([(c["resume_id"],c["missing_conditions"]) for c in rows]==
                        [(c["resume_id"],c["missing_conditions"]) for c in saved[part]], "持久化检索结果不符")
            for row in strict+near:
                rid=row["resume_id"]
                c=self.cand[rid]
                groups=report["ir"]["must_skills"]
                missing=[g for g in groups if not set(g)&evidence[rid]]
                degree=c["max_degree_level"]<report["ir"]["min_degree_level"]
                tenure=c["merged_exp_months"]<12*report["ir"]["min_exp_years"]
                messages=row["missing_conditions"]
                require(len(messages)==len(missing)+int(degree)+int(tenure) and
                        all(any(all(skill in msg for skill in grp) for msg in messages) for grp in missing)
                        and (not degree or any("学历" in m for m in messages))
                        and (not tenure or any("工龄" in m for m in messages))
                        and (not messages)==(rid in strict_ids),"缺失条件不符 "+rid)
                require(row["pdf_path"]==self.docs[rid]["pdf_path"] and (ROOT/row["text_path"]).is_file() and
                        row["split"]=="test" and all(self.quote_ok(e,rid) for e in row["skill_evidence"]),
                        "查询原始简历或证据不符 "+rid)
            result[key]=dict(query=query,length=len(query),strict=len(strict),near=len(near),top3=report["top3"])
        require(result["main"]["strict"]>=3 and result["zero"]["strict"]==0 and result["zero"]["near"]>0,"主/边界查询命中数不符")
        folder=PROCESSED/"query_reports"
        png(folder/"comparison.png")
        md=(folder/"comparison.md").read_text()
        require(all(rid in md for rid in result["main"]["top3"]),"缺少三人比较")
        return result


def check_package():
    if not PACKAGE.exists():
        subprocess.run(["bash","scripts/package_submission.sh"],cwd=ROOT,check=True)
    with zipfile.ZipFile(PACKAGE) as z:
        require(z.testzip() is None, "压缩包 CRC 校验失败")
        paths={e.filename for e in z.infolist()}
        require(all(n.startswith(NAME+"/") and not set(Path(n).parts)&{".venv","neo4j_data","raw","__pycache__",".git"}
                    and not n.endswith("ResumesPDF.zip") for n in paths), "压缩包命名或排除项不符")
        require(f"{NAME}/demo_video/" in paths,"缺少视频目录")
        for start in ("src","app.py","scripts","docs","data/sample_pdfs","data/extracted_txt","data/processed",
                      "README.md","pyproject.toml","requirements.txt","docker-compose.yml",".env.example"):
            root=ROOT/start
            for path in root.rglob("*") if root.is_dir() else [root]:
                if path.is_file() and "__pycache__" not in path.parts and path.name!=".DS_Store" and path.suffix!=".pyc":
                    entry=NAME+"/"+path.relative_to(ROOT).as_posix()
                    require(entry in paths, "提交包缺少 "+entry)
                    # The report is written after the check; its content is checked after publication.
                    if path!=AC:
                        require(z.read(entry)==path.read_bytes(),"提交包文件过期 "+entry)
    return dict(package=PACKAGE.name, document="docs/技术说明文档.md",video_directory=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish",action="store_true",help="从实测结果重新生成说明文档与提交包")
    args=parser.parse_args()
    result={"checks":{}}
    with get_driver() as driver:
        audit=Audit(driver)
        for i in range(1,8):
            key=f"AC-{i}"
            try:
                result["checks"][key]={"status":"PASS","metrics":getattr(audit,"ac"+str(i))()}
            except Exception as exc:
                result["checks"][key]={"status":"FAIL","error":f"{type(exc).__name__}: {exc}"}
            print(key,result["checks"][key]["status"],result["checks"][key].get("error",""),flush=True)
    if all(r["status"]=="PASS" for r in result["checks"].values()):
        try:
            from technical_report import render
            expected=render(result)
            if args.publish:
                DOC.parent.mkdir(exist_ok=True)
                DOC.write_text(expected,encoding="utf-8")
                write_json(AC,result)
                subprocess.run(["bash","scripts/package_submission.sh"],cwd=ROOT,check=True)
            require(DOC.read_text(encoding="utf-8")==expected,"技术说明与当前实测结果不一致")
            metrics=check_package()
            result["checks"]["AC-8"]={"status":"PASS","metrics":metrics}
        except Exception as exc:
            result["checks"]["AC-8"]={"status":"FAIL","error":f"{type(exc).__name__}: {exc}"}
    else:
        result["checks"]["AC-8"]={"status":"FAIL","error":"上游验收未通过，文档数字无法一致核验"}
    result["all_passed"]=all(r["status"]=="PASS" for r in result["checks"].values())
    write_json(AC,result)
    if result["all_passed"] and args.publish:
        subprocess.run(["bash","scripts/package_submission.sh"],cwd=ROOT,check=True)
    if result["all_passed"]:
        with zipfile.ZipFile(PACKAGE) as z:
            if json.loads(z.read(NAME+"/data/processed/acceptance_report.json"))!=result:
                result["checks"]["AC-8"]={"status":"FAIL","error":"压缩包内的验收结果过期；使用 --publish 重新发布"}
                result["all_passed"]=False
                write_json(AC,result)
    print("AC-8",result["checks"]["AC-8"]["status"],result["checks"]["AC-8"].get("error",""),flush=True)
    print(AC)
    return 0 if result["all_passed"] else 1


if __name__=="__main__":
    sys.exit(main())
