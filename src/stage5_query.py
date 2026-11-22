"""中文岗位检索。语句只读，所有用户输入均作为 Neo4j 参数。"""
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/processed/query_reports"
MANIFEST = ROOT / "data/extracted_txt/manifest.json"
MAIN_QUERY = "本科及以上，掌握 Python、Java 或 SQL 任一项，有项目经验优先，熟悉 SQL 优先。"
ZERO_QUERY = "博士学历，至少8年工作经验，同时掌握 Rust、Kubernetes 与 SAP。"
DIMS = {"EDU": "教育", "EXP": "经历", "SKL": "技能", "POT": "潜力"}
DEGREES = {"大专": 1, "专科": 1, "本科": 2, "学士": 2, "硕士": 3, "研究生": 3, "博士": 4}
DEGREE_NAMES = ["未检出", "专科", "本科", "硕士", "博士"]
# 即使训练/测试样本都没有这项技能，也保留用户声明的硬条件。
STANDARD_NAMES = (
    "Python|Java|SQL|Rust|Kubernetes|SAP ERP|C|C++|C#|F#|JavaScript|TypeScript|"
    "R|Go|MySQL|PostgreSQL|Oracle Database|Node.js|.NET|ASP.NET|React|"
    "Machine Learning|Natural Language Processing|Amazon Web Services|Excel|Docker"
).split("|")
ALIASES = {"sap": "SAP ERP", "k8s": "Kubernetes", "aws": "Amazon Web Services",
           "ml": "Machine Learning", "nlp": "Natural Language Processing", "js": "JavaScript"}

def skill_catalog(graph_skills=()):
    catalog = {s.casefold(): s for s in STANDARD_NAMES}
    catalog.update(ALIASES)
    for row in graph_skills:
        for spelling in row.get("aliases") or []:
            if spelling.strip():
                catalog[spelling.strip().casefold()] = row["name"]
    for row in graph_skills:
        catalog[row["name"].casefold()] = row["name"]
    return catalog

def _skill_pattern(catalog):
    alternatives = sorted(catalog, key=len, reverse=True)
    return re.compile(r"(?<![A-Za-z0-9_+.#])(?:" + "|".join(map(re.escape, alternatives)) +
                      r")(?![A-Za-z0-9_+#]|\.[A-Za-z0-9_])", re.I)

def _year_number(match):
    number = match[1]
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
    if number in digits:
        return str(digits[number]) + "年"
    if number.count("十") == 1:
        tens, ones = number.split("十")
        if (not tens or tens in digits) and (not ones or ones in digits):
            return str(10 * digits.get(tens, 1) + digits.get(ones, 0)) + "年"
    raise ValueError("无法解析工作年限，请改用阿拉伯数字。")

def parse_query(query, catalog=None):
    """将可验证的自然语言条件解析为 AND 连接的技能组，组内为 OR。"""
    if not isinstance(query, str) or not 1 <= len(query) <= 100 or not query.strip():
        raise ValueError("请输入 1 至 100 个字符的岗位需求。")
    catalog = skill_catalog() if catalog is None else catalog
    pattern = _skill_pattern(catalog)
    groups, preferred, signals = [], [], []
    min_degree = min_years = 0
    query_text = query.replace("；", "，").replace(";", "，")
    query_text = re.sub(r"([一二两三四五六七八九十零]+)年", _year_number, query_text)
    # 两个英文技能之间的半角逗号保留为同一列表，其余视为子句边界。
    query_text = re.sub(r"(?<=[A-Za-z0-9+#]),\s*(?=[A-Za-z.])", "、", query_text)
    # Only consume an explicit, standalone job heading. Unknown conditions
    # in the heading or subsequent clauses still go through strict validation.
    heading = re.match(r"^\s*(?:招聘|招募|岗位[：:]|职位[：:])\s*"
                       r"(?:初级|中级|高级|资深)?(?:软件开发|软件|后端开发|后端|前端开发|前端|"
                       r"全栈开发|全栈|数据开发|数据|测试|算法|运维|开发)工程师\s*[，,。：:\n]+", query_text)
    if heading:
        query_text = query_text[heading.end():]
    clauses = re.split(r"[，,。\n]+", query_text)
    for clause in filter(str.strip, clauses):
        is_pref = bool(re.search(r"优先|加分|偏好", clause))
        if is_pref and re.search(r"必须|必备|需(?:要)?掌握|要求", clause):
            raise ValueError("请将必须满足的条件与优先条件用逗号分开。")
        if is_pref and re.search(r"(?:且|并且|并)(?:掌握|具备|熟悉|了解|有)", clause):
            raise ValueError("这句话中的偏好范围不明确，请将每项条件分句写明。")
        years = re.search(r"(\d+(?:\.\d+)?)\s*年", clause)
        degrees = [v for k, v in DEGREES.items() if k in clause]
        skills = list(dict.fromkeys(catalog[m.group().casefold()] for m in pattern.finditer(clause)))
        project = bool(re.search(r"项目(?:经验|经历|实践|实战)", clause))
        ratio = bool(re.search(r"实证技能占比|技能实证占比", clause))
        if re.search(r"不(?:需要|要求|限)|无需|以下|至多|最多|(?<!不)少于|超过|仅限|恰好", clause):
            raise ValueError(f"暂不支持这类范围或否定写法，请使用明确的最低门槛：{clause.strip()}")
        if is_pref and (years or degrees):
            raise ValueError("学历和年限目前支持硬门槛写法，请将偏好单独成句。")
        if not is_pref and (project or ratio):
            raise ValueError("项目经验和实证技能占比目前支持排序偏好，请明确写出“优先”。")
        if len(degrees) > 1:
            raise ValueError("请在每个学历条件中只给出一个最低学历。")
        remainder = pattern.sub("", clause)
        remainder = re.sub(r"\d+(?:\.\d+)?\s*年", "", remainder)
        for word in sorted(DEGREES, key=len, reverse=True):
            remainder = remainder.replace(word, "")
        vocabulary = (
            "实证技能占比|技能实证占比|项目经验|项目经历|项目实践|项目实战|工作经验|工作经历|工作年限|"
            "任意一项|任意一种|其中之一|其中一项|至少一项|任一项|任一种|任一|之一|一种|"
            "要求|需要|候选人|至少|不低于|不少于|及以上|或以上|以上|学历|经验|及其|同时|必须|必备|者|"
            "精通|熟练|熟悉|掌握|具备|了解|会用|使用|会|有|且|并|和|与|或|及|优先|加分|偏好|较高|高|技能|技术|[、\\s]"
        )
        remainder = re.sub(vocabulary, "", remainder)
        if remainder or not (skills or years or degrees or project or ratio):
            raise ValueError(f"无法完整解释「{clause.strip()}」，请将技能、学历、年限或偏好分句写明。")
        if years:
            min_years = max(min_years, float(years[1]))
        if degrees:
            min_degree = max(min_degree, *degrees)
        connective = pattern.sub("", clause)
        any_of = bool(re.search(r"或(?!以上)|任一|任意|之一|至少一项", connective))
        if any_of and (re.search(r"同时|和|与|且|并", connective) or (skills and (degrees or years))):
            raise ValueError("请把必选技能和任选技能分成不同子句。")
        if is_pref:
            if any_of and len(skills) > 1:
                raise ValueError("请将每个加分技能单独写成“……优先”。")
            preferred.extend(skills)
            if project:
                signals.append("project_experience")
            if ratio:
                signals.append("verified_skill_ratio")
        elif any_of and skills:
            groups.append(skills)
        else:
            groups.extend([s] for s in skills)
    if not (groups or min_degree or min_years or signals or preferred):
        raise ValueError("请至少指定一个可验证的硬条件或排序偏好。")
    return {"must_skills": groups, "min_degree_level": min_degree, "min_exp_years": min_years,
            "prefer_signals": list(dict.fromkeys(signals)), "prefer_skills": list(dict.fromkeys(preferred))}

_BASE = """
MATCH (c:Candidate {split: 'test'})
WHERE c:ResumeKG AND c.kg_owner='ism2026hw2_resume_graph'
OPTIONAL MATCH (c)-[h:HAS_SKILL]->(s:Skill:ResumeKG)
WHERE h.kg_owner='ism2026hw2_resume_graph' AND h.evidence_valid = true
WITH c, collect(DISTINCT s.name) AS skills,
     collect(DISTINCT CASE WHEN s IS NOT NULL THEN
       {skill:s.name, resume_id:h.resume_id, page_num:h.page_num, evidence_quote:h.evidence_quote,
        source:h.source, evidence_valid:h.evidence_valid} END) AS skill_evidence
WITH c, skills, skill_evidence,
     [grp IN $skill_groups WHERE none(name IN grp WHERE name IN skills)] AS missing_groups,
     c.max_degree_level < $min_degree AS degree_missing,
     c.merged_exp_months < $min_months AS months_missing,
     [name IN $prefer_skills WHERE name IN skills] AS preferred_hits
WITH c, skills, skill_evidence, missing_groups, degree_missing, months_missing, preferred_hits,
     size(missing_groups) + CASE WHEN degree_missing THEN 1 ELSE 0 END
                          + CASE WHEN months_missing THEN 1 ELSE 0 END AS missing_count,
     size(preferred_hits) + CASE WHEN $prefer_projects AND c.project_count > 0 THEN 1 ELSE 0 END
       + CASE WHEN $prefer_verified THEN c.verified_skill_ratio ELSE 0.0 END AS preference_score
""".strip()
_RETURN = """
RETURN properties(c) AS candidate, skills, skill_evidence, missing_groups,
       degree_missing, months_missing, preferred_hits, missing_count, preference_score
ORDER BY missing_count, preference_score DESC, c.resume_id
""".strip()
STRICT_CYPHER = _BASE + "\nWHERE missing_count = 0\n" + _RETURN
NEAR_CYPHER = _BASE + "\nWHERE missing_count > 0\n" + _RETURN
RECORD_CYPHER = """
MATCH (c:Candidate {split:'test'})-[r:HAS_EDUCATION|HAS_EXPERIENCE|WORKED_ON]->(rec)
WHERE c:ResumeKG AND c.kg_owner='ism2026hw2_resume_graph'
  AND r.kg_owner='ism2026hw2_resume_graph' AND c.resume_id IN $ids
OPTIONAL MATCH (rec)-[detail:USED_SKILL|APPLIED_SKILL]->(s:Skill)
WHERE detail.kg_owner='ism2026hw2_resume_graph' AND detail.evidence_valid=true
RETURN c.resume_id AS resume_id, type(r) AS relation, properties(r) AS evidence,
       r.page_num AS page, rec.id AS record_id, rec.name AS record_name, collect(DISTINCT s.name) AS applied_skills
ORDER BY resume_id, page, record_id
"""

def parameters(ir):
    return {"skill_groups": ir["must_skills"], "min_degree": ir["min_degree_level"],
            "min_months": math.ceil(ir["min_exp_years"] * 12), "prefer_skills": ir["prefer_skills"],
            "prefer_projects": "project_experience" in ir["prefer_signals"],
            "prefer_verified": "verified_skill_ratio" in ir["prefer_signals"]}

def browser_cypher(statement, params):
    """Browser 粘贴版本。仅内联本模块生成的字符串、数字、布尔和列表字面量。"""
    return re.sub(r"\$(\w+)", lambda m: json.dumps(params[m[1]], ensure_ascii=False), statement)

def format_result(row, ir, doc):
    c = row["candidate"]
    missing = ["缺少技能 " + " 或 ".join(group) for group in row["missing_groups"]]
    if row["degree_missing"]:
        missing.append(f"最高学历 {DEGREE_NAMES[c['max_degree_level']]}，要求 {DEGREE_NAMES[ir['min_degree_level']]}及以上")
    if row["months_missing"]:
        missing.append(f"净工龄 {c['merged_exp_months']} 个月，要求至少 {math.ceil(12 * ir['min_exp_years'])} 个月")
    hard_skills = {s for group in ir["must_skills"] for s in group}
    wanted = hard_skills | set(ir["prefer_skills"])
    relevant = [e for e in row["skill_evidence"] if e["skill"] in wanted]
    relevant.sort(key=lambda e: (e["source"] == "listed", e["page_num"], e["skill"], e["evidence_quote"]))
    return {
        "resume_id": c["resume_id"], "split": c["split"], "pdf_path": doc["pdf_path"],
        "text_path": doc["text_path"], "source_name": doc["source_name"],
        "text_excerpt": doc["pages"][0]["text"][:400],
        "skills": sorted(row["skills"]), "matched_skills": sorted(hard_skills & set(row["skills"])),
        "missing_conditions": missing, "matched_prefer_skills": sorted(row["preferred_hits"]),
        "unmatched_prefer_skills": sorted(set(ir["prefer_skills"]) - set(row["preferred_hits"])),
        "preference_score": row["preference_score"], "degree_level": c["max_degree_level"],
        "merged_exp_months": c["merged_exp_months"], "project_count": c["project_count"],
        "verified_skill_count": c["verified_skill_count"], "verified_skill_ratio": c["verified_skill_ratio"],
        "scores": {k: c["score_" + k.lower()] for k in DIMS},
        "grades": {k: c["grade_" + k.lower()] for k in DIMS},
        "skill_evidence": relevant, "record_evidence": [], "project_evidence": [],
    }

def execute_query(query, driver=None):
    from .stage3_neo4j import get_driver
    if driver is None:
        with get_driver() as owned:
            return execute_query(query, owned)
    docs = {d["resume_id"]: d for d in json.loads(MANIFEST.read_text())["documents"]}
    with driver.session() as session:
        skills = session.run("MATCH (s:Skill:ResumeKG {kg_owner:'ism2026hw2_resume_graph'}) "
                             "RETURN s.name AS name,s.aliases AS aliases").data()
        ir = parse_query(query, skill_catalog(skills))
        params = parameters(ir)
        def read(tx):
            counts = tx.run("MATCH (c:Candidate:ResumeKG {split:'test', kg_owner:'ism2026hw2_resume_graph'}) RETURN count(c) AS total,"
                            "count(c.score_pot) AS scored").single()
            if not counts["total"] or counts["total"] != counts["scored"]:
                raise ValueError("测试集四维评估尚未完成，请先运行阶段四。")
            strict = [format_result(r, ir, docs[r["candidate"]["resume_id"]]) for r in tx.run(STRICT_CYPHER, params)]
            near = [format_result(r, ir, docs[r["candidate"]["resume_id"]]) for r in tx.run(NEAR_CYPHER, params)]
            by_id = {c["resume_id"]: c for c in strict}
            for row in tx.run(RECORD_CYPHER, ids=list(by_id)):
                candidate = by_id[row["resume_id"]]
                edge = row["evidence"]
                if edge.get("evidence_valid") and edge.get("evidence_quote"):
                    info = {k: edge.get(k) for k in ("resume_id", "page_num", "evidence_quote", "evidence_valid", "record_id")}
                    info.update(relation=row["relation"], record_name=row["record_name"], applied_skills=sorted(row["applied_skills"]))
                    candidate["record_evidence"].append(info)
                    if row["relation"] == "WORKED_ON":
                        candidate["project_evidence"].append(info)
            return strict, near
        strict, near = session.execute_read(read)
    feature_file = ROOT / "data/processed/candidate_features.json"
    if feature_file.exists():
        evidence_by_id = {row["resume_id"]: row["evidence"] for row in json.loads(feature_file.read_text())["candidates"]}
        for candidate in strict:
            evidence = evidence_by_id[candidate["resume_id"]]
            candidate["threshold_evidence"] = {
                feature: evidence.get(feature, []) for feature, used in
                [("max_degree_level", ir["min_degree_level"]), ("merged_exp_months", ir["min_exp_years"])] if used
            }
    return {"query": query, "ir": ir, "scope": "test", "parameters": params,
            "cypher": STRICT_CYPHER, "near_cypher": NEAR_CYPHER,
            "browser_cypher": browser_cypher(STRICT_CYPHER, params),
            "strict_matches": strict, "near_misses": near, "top3": [c["resume_id"] for c in strict[:3]]}

def comparison_rows(candidates):
    return [{"简历": c["resume_id"], **{name: f"{c['scores'][dim]} / {c['grades'][dim]}" for dim, name in DIMS.items()},
             "学历": DEGREE_NAMES[c["degree_level"]], "净工龄（月）": c["merged_exp_months"],
             "项目数": c["project_count"], "有技能证据的项目": sum(bool(e["applied_skills"]) for e in c["project_evidence"]),
             "实证技能": c["verified_skill_count"], "实证占比": f"{c['verified_skill_ratio']:.0%}",
             "加分技能命中": "、".join(c["matched_prefer_skills"]) or "无",
             "加分技能未命中": "、".join(c["unmatched_prefer_skills"]) or "无"} for c in candidates]

def comparison_conclusion(candidates):
    top_score = candidates[0]["preference_score"]
    tied = [c for c in candidates if c["preference_score"] == top_score]
    names = "、".join(c["resume_id"] for c in tied)
    project = max(candidates, key=lambda c: (sum(bool(p["applied_skills"]) for p in c["project_evidence"]),
                                             c["verified_skill_count"]))
    depth = sum(bool(p["applied_skills"]) for p in project["project_evidence"])
    return (f"在表内候选人中，{names} 的岗位偏好得分最高（{top_score:g}），建议优先安排面试。"
            f"{project['resume_id']} 有 {depth} 段带技能证据的项目，工作或项目中可核对 "
            f"{project['verified_skill_count']} 项实证技能，可据此设计实操环节。")

def comparison_markdown(report):
    people = report["strict_matches"][:3]
    lines = ["# 测试集岗位对比", "", report["query"], "",
             f"严格命中 {len(report['strict_matches'])} 人。排序时每项加分技能计 1 分，有项目经验计 1 分（若岗位指定）；指定实证占比优先时按实际比例计分。同分依简历编号排序。", ""]
    if not people:
        return "\n".join(lines + ["没有通过全部硬条件的候选人。"])
    rows = comparison_rows(people)
    lines += ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
    for row in rows:
        lines.append("| " + " | ".join(map(str, row.values())) + " |")
    if len(people) == 3:
        lines.extend(["", "![三人四维得分对比](comparison.png)"])
    lines.extend(["", comparison_conclusion(people)])
    for c in people:
        lines.extend(["", f"## {c['resume_id']}", "",
                      f"[原始 PDF](../../../{c['pdf_path']}) · [逐页文本](../../../{c['text_path']})",
                      "", f"满足的必选或任选技能为 {', '.join(c['matched_skills']) or '本岗位未设技能门槛'}。"])
        evidence = []
        for skill in c["matched_skills"] + c["matched_prefer_skills"]:
            selected = next((e for e in c["skill_evidence"] if e["skill"] == skill), None)
            if selected and selected not in evidence:
                evidence.append(selected)
        for e in evidence:
            lines.extend(["", f"- {e['skill']}（{e['source']}，第 {e['page_num']} 页） “{' '.join(e['evidence_quote'].split())}”"])
        for feature, examples in c.get("threshold_evidence", {}).items():
            for e in examples[:2]:
                lines.extend(["", f"- {feature}（第 {e['page_num']} 页） “{' '.join(e['evidence_quote'].split())}”"])
        for e in c["project_evidence"]:
            lines.extend(["", f"- {e['record_name']}（项目，第 {e['page_num']} 页） “{' '.join(e['evidence_quote'].split())}”。记录内技能为 {', '.join(e['applied_skills']) or '未检出'}。"])
        lines.extend(["", recommendation(c)])
    return "\n".join(lines) + "\n"

def recommendation(c):
    applied = [e for e in c["project_evidence"] if e["applied_skills"]]
    if applied:
        skills = "、".join(applied[0]["applied_skills"][:4])
        return f"面试建议围绕项目中出现的 {skills} 追问具体贡献，并核实交付成果。"
    if c["verified_skill_count"]:
        return f"可进入岗位面试，重点核实工作经历中 {c['verified_skill_count']} 项实证技能的应用深度，以及独立承担项目的范围。"
    return "可安排基础技能面试，先要求演示与岗位相关的实操样例，再评估项目交付能力。"

def query_markdown(report):
    hits, near = report["strict_matches"], report["near_misses"]
    lines = ["# 测试集岗位检索", "", report["query"], "",
             f"需求长度 {len(report['query'])} 字，严格命中 {len(hits)} 人，近似候选 {len(near)} 人。", "",
             "## 条件与查询", "", "```json", json.dumps(report["ir"], ensure_ascii=False, indent=2),
             "```", "", "```cypher", report["browser_cypher"], "```", "", "## 严格命中", ""]
    if not hits:
        lines.append("测试集中无人满足全部硬条件。")
    for c in hits:
        lines.extend([f"### {c['resume_id']}", "",
                      f"[原始 PDF](../../../{c['pdf_path']}) · [全文](../../../{c['text_path']})", "",
                      f"{DEGREE_NAMES[c['degree_level']]}，净工龄 {c['merged_exp_months']} 个月，"
                      f"项目 {c['project_count']} 段。符合的岗位技能为 {'、'.join(c['matched_skills']) or '未指定'}。"])
        for name in c["matched_skills"]:
            quote = next(e for e in c["skill_evidence"] if e["skill"] == name)
            lines.extend(["", f"- {name} · 第 {quote['page_num']} 页 · {quote['source']} · "
                              + " ".join(quote["evidence_quote"].split())])
        lines.append("")
    if hits and report["query"] == MAIN_QUERY:
        lines.append("[前三位候选人多维对比](comparison.md)")
    lines.extend(["", "## 近似候选与缺失硬条件", ""])
    for c in near:
        lines.append(f"- {c['resume_id']}　" + "；".join(c["missing_conditions"]))
    if not near:
        lines.append("所有测试候选人均通过硬条件。")
    return "\n".join(lines) + "\n"

def run_stage5(driver=None):
    from .config import write_json
    from .visuals import radar
    from .stage3_neo4j import get_driver
    if driver is None:
        with get_driver() as owned:
            return run_stage5(owned)
    OUT.mkdir(parents=True, exist_ok=True)
    main, zero = (execute_query(query, driver) for query in (MAIN_QUERY, ZERO_QUERY))
    for name, report in (("main", main), ("zero", zero)):
        write_json(OUT / f"{name}.json", report)
        (OUT / f"{name}.md").write_text(query_markdown(report), encoding="utf-8")
    (OUT / "comparison.md").write_text(comparison_markdown(main), encoding="utf-8")
    top = main["strict_matches"][:3]
    if len(top) == 3:
        radar({c["resume_id"]: c["scores"] for c in top}, OUT / "comparison.png", "Top 3 | job query")
    elif (OUT / "comparison.png").exists():
        (OUT / "comparison.png").unlink()
    return {"main": main, "zero": zero}
