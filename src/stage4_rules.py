"""Train-only empirical thresholds over auditable features of the live Neo4j graph."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
from statistics import mean

import numpy as np

from .config import PROCESSED, write_json
from .stage2_extract import PERIOD
from .stage3_neo4j import OWNER, connection, graph_stats
from .visuals import DIMENSIONS, entity_distribution, radar

# One feature, one rule, four rules of equal weight per dimension. Zero means
# no observed evidence and must never be a qualifying threshold.
TEMPLATES = {
    "EDU": (
        ("max_degree_level", .75, "最高学历", "达到训练样本中较高的学位层级。"),
        ("has_stem_or_target_major", .50, "目标专业", "学历原句中出现技术、理工或商科方向专业。"),
        ("edu_record_completeness", .50, "学历记录完整", "同条学历记录具备院校、学位以及年份或专业。"),
        ("cert_or_multi_edu_count", .50, "进阶学习", "有可定位的认证或首段以外的学历经历。"),
    ),
    "EXP": (
        ("merged_exp_months", .75, "净任职月数", "将有明确起止日期的任职月份去重，再衡量经验累积。"),
        ("distinct_companies", .50, "企业历练", "按实际任职边上的不同企业衡量组织经历。"),
        ("max_seniority_level", .75, "岗位职责层级", "以实际岗位头衔可观察的最高职级衡量职责深度。"),
        ("avg_role_tenure_months", .50, "单段任职时长", "在日期可解析的岗位间比较平均持续月数。"),
    ),
    "SKL": (
        ("verified_skill_count", .75, "实证技能数量", "工作或项目中实际出现的不同技能数量达标。"),
        ("verified_skill_ratio", .50, "实证技能比例", "实际使用过的技能占全部已识别技能的比例达标。"),
        ("total_skill_count", .50, "技能广度", "规范化后的不同技能数量达标。"),
        ("skill_category_coverage", .75, "技能类别覆盖", "覆盖多种技术或业务能力方向。"),
    ),
    "POT": (
        ("project_count", .75, "独立项目", "可定位的独立项目记录数量达标。"),
        ("quantified_impact_count", .50, "量化成果", "任职或项目中存在包含具体数值的成果或服务规模。"),
        ("career_progression_delta", .50, "职级成长", "较晚开始的岗位具有更高的明确职责层级。"),
        ("applied_skill_diversity", .75, "跨类实践", "工作或项目中实际应用了多个方向的技能。"),
    ),
}
TITLES = dict(EDU="教育背景", EXP="工作经历", SKL="技能水平", POT="发展潜力")
DEGREES = [
    (4, re.compile(r"\b(?:ph\.?\s*d\b|doctor(?:al|ate| of philosophy)\b)", re.I)),
    (3, re.compile(r"\b(?:master(?:s|'s|’s)?|mba|mca|m\.?\s*(?:sc|s|tech|eng|e)\.?)\b", re.I)),
    (2, re.compile(r"\b(?:bachelor(?:s|'s|’s)?|b\.?\s*(?:sc|s|a|tech|eng|e|com|ca)\.?)\b", re.I)),
    (1, re.compile(r"\bassociate(?:s|'s|’s)?(?=\s+(?:of|degree)\b)", re.I)),
]
MAJOR = re.compile(r"\b(?:computer|computing|informatics|information (?:science|systems|technology)|"
                   r"[\w-]+ engineering|mathematics|statistics|biology|physics|chemistry|finance|"
                   r"accounting|business|economics|data science|analytics)\b", re.I)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
IMPACT = re.compile(r"(?:\b\d[\d,.]*\s*(?:%|percent\b|[- ]?fold\b|[x×]\b)|"
                    r"[$£€]\s*\d[\d,.]*|\b\d[\d,.]*\s*[kKmM]?\+?\s+"
                    r"(?:users|customers|clients|transactions|requests|records|employees|"
                    r"accounts|students|servers|devices|hours|teams)\b)", re.I)
CATEGORIES = {"Programming", "Data_AI", "Database", "Cloud_DevOps", "Web_Mobile", "Management_Business"}


def month_index(value):
    m = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", str(value or ""))
    return int(m[1])*12 + int(m[2])-1 if m else None


def merged_months(intervals):
    """Both endpoint months count; overlapping intervals contribute their union."""
    total, previous_end = 0, -1
    for start, end in sorted(intervals):
        if end >= start:
            total += max(0, end - max(start, previous_end + 1) + 1)
            previous_end = max(previous_end, end)
    return total


def seniority(title):
    if re.search(r"\b(?:chief|head|lead|leader|manager|director|vp|founder|principal)\b", title, re.I):
        return 4
    if re.search(r"\b(?:senior|sr|staff|architect)\b", title, re.I):
        return 3
    if re.search(r"\b(?:intern(?:ship)?|trainee|junior|jr|apprentice|student)\b", title, re.I):
        return 1
    return 2 if title.strip() else 0


def from_edge(edge):
    return {k: edge[k] for k in ("resume_id", "page_num", "evidence_quote", "record_id", "surface") if k in edge}


def snippet(rec, start, end):
    text = rec["record_text"]
    left = max(text.rfind("\n", 0, start) + 1, start - 85)
    right = text.find("\n", end)
    right = min(right if right != -1 else len(text), left + 240, end + 125)
    return dict(resume_id=rec["resume_id"], page_num=rec["page_num"],
                record_id=rec["id"], evidence_quote=text[left:right].strip())


GRAPH_COUNTS = """
MATCH (c:ResumeKG:Candidate {kg_owner:$owner})
CALL (c) {
    MATCH p=(c)-[:HAS_SKILL]->(s:Skill)
    WHERE all(r IN relationships(p) WHERE r.kg_owner=$owner AND r.evidence_valid)
    RETURN collect(DISTINCT s) AS listed
}
CALL (c) {
    MATCH p=(c)-[:HAS_EXPERIENCE|WORKED_ON]->()-[:USED_SKILL|APPLIED_SKILL]->(s:Skill)
    WHERE all(r IN relationships(p) WHERE r.kg_owner=$owner AND r.evidence_valid)
    RETURN collect(DISTINCT s) AS verified
}
CALL (c) {
    MATCH p=(c)-[:HAS_EXPERIENCE]->()-[:AT_COMPANY]->(b:Company)
    WHERE all(r IN relationships(p) WHERE r.kg_owner=$owner AND r.evidence_valid)
    RETURN count(DISTINCT b) AS distinct_companies
}
CALL (c) {
    MATCH (c)-[r:WORKED_ON]->(p:Project)
    WHERE r.kg_owner=$owner AND r.evidence_valid
    RETURN count(DISTINCT p) AS project_count
}
WITH c,verified,listed+[s IN verified WHERE NOT s IN listed] AS skills,
     distinct_companies,project_count
RETURN c.id AS id,distinct_companies,project_count,size(verified) AS verified_skill_count,
       size(skills) AS total_skill_count,
       CASE WHEN size(skills)=0 THEN 0.0 ELSE toFloat(size(verified))/size(skills) END AS verified_skill_ratio,
       size([cat IN $categories WHERE any(s IN skills WHERE s.category=cat)]) AS skill_category_coverage,
       size([cat IN $categories WHERE any(s IN verified WHERE s.category=cat)]) AS applied_skill_diversity
"""


def raw_rows(driver):
    with driver.session() as s:
        candidates = {r["c"]["id"]: r["c"] for r in s.run(
            "MATCH (c:ResumeKG:Candidate {kg_owner:$owner}) RETURN properties(c) AS c", owner=OWNER)}
        grouped = defaultdict(list)
        # The first pattern visits the immediate records and listed skills;
        # the second visits only the endpoints of those records' outgoing edges.
        for r in s.run("""
            MATCH (c:ResumeKG:Candidate {kg_owner:$owner})-[r]->(n:ResumeKG)
            WHERE r.kg_owner=$owner
            RETURN c.id AS resume_id,c.id AS src,type(r) AS rel, properties(r) AS edge,
                   properties(n) AS node
            UNION ALL
            MATCH (c:ResumeKG:Candidate {kg_owner:$owner})-[a:HAS_EXPERIENCE|HAS_EDUCATION|WORKED_ON]
                  ->(x:ResumeKG)-[r]->(n:ResumeKG)
            WHERE a.kg_owner=$owner AND a.evidence_valid AND r.kg_owner=$owner
            RETURN DISTINCT c.id AS resume_id,x.id AS src,type(r) AS rel,properties(r) AS edge,
                   properties(n) AS node
            """, owner=OWNER):
            item = r.data()
            if item["edge"]["kg_snapshot"] != candidates[item["resume_id"]]["kg_snapshot"]:
                raise RuntimeError("The graph changed during the feature read")
            grouped[item["resume_id"]].append(item)
        for rec in s.run(GRAPH_COUNTS, owner=OWNER, categories=sorted(CATEGORIES)):
            values = rec.data()
            candidates[values.pop("id")]["graph_counts"] = values
    return [(candidates[k], grouped[k]) for k in sorted(candidates)]


# Completion is assessed per credential, not from a status word anywhere on a page.
PENDING_PREFIX = re.compile(
    r"(?:candidate for|pursuing|working (?:toward[s]?|on)|studying (?:toward[s]?|for)|"
    r"enrolled in|in pursuit of|coursework toward[s]?)\s+(?:(?:a|an|the|my|his|her)\s+)?$", re.I)
PENDING_FOLLOW = re.compile(
    r"\b(?:expected|anticipated)\s+(?:graduation|completion|in\s+\d{4}|\d|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|spring|fall|summer|winter)|"
    r"\b(?:in progress|not yet completed|did not complete|currently enrolled|"
    r"currently (?:a |an )?(?:(?:full|part)[- ]time )?student)\b|"
    r"^[.,:\s]*(?:degree\s+)?candidate\b|"
    r"(?:[-–—,]|\bto)\s*\b(?:present|current)\b(?!\s+(?:member|gpa|affiliations))|"
    r"\b(?:present|current)\s+(?:university|college)\b|"
    r"(?m:^\s*(?:present|current)\s*$)", re.I)
UNRELATED_SECTION = re.compile(
    r"\b(?:(?:(?:present|current)\s+)?affiliations|presentations|work experience|certifications|professional memberships|awards)\b", re.I)
ACADEMIC_STOP = set("the for and with science bachelor bachelors master masters associate arts degree university college school state city applied".split())


def education_status(records):
    """Locate pending qualifiers; reconcile adjacent duplicate headers for the same credential."""
    mentions = {}
    for key, (kind, rec, _) in records.items():
        if kind != "HAS_EDUCATION":
            continue
        text = rec["record_text"]
        spans = sorted(((level, m) for level, rx in DEGREES for m in rx.finditer(text)),
                       key=lambda x:x[1].start())
        entries = []
        for i, (level, match) in enumerate(spans):
            start, end = match.span()
            before = max(spans[i-1][1].end() if i else 0, start-80)
            after = min(spans[i+1][1].start() if i+1 < len(spans) else len(text), end+260)
            # Preserve offsets through whitespace-heavy PDF table cells.
            following = UNRELATED_SECTION.split(text[end:after], maxsplit=1)[0]
            pre = PENDING_PREFIX.search(text[before:start])
            post = PENDING_FOLLOW.search(following)
            reason = None
            if pre:
                reason = snippet(rec, before+pre.start(), end)
            elif post:
                reason = snippet(rec, end+post.start(), end+post.end())
            entries.append(dict(level=level, match=match, pending=reason))
        mentions[key] = entries

    # PDF layouts sometimes repeat the same credential as an unqualified short
    # header, immediately followed by the full line that specifies its status.
    # Only propagate across neighbouring fragments with matching field terms.
    ordered = sorted((rec for kind,rec,_ in records.values() if kind=="HAS_EDUCATION"),
                     key=lambda r:(r["page_num"], r.get("page_start",0)))
    for a,b in zip(ordered, ordered[1:]):
        if a["page_num"] != b["page_num"]:
            continue
        gap = b.get("page_start",0) - a.get("page_start",0) - len(a["record_text"])
        if not -1 <= gap <= 20:
            continue
        for brief,detail in ((a,b),(b,a)):
            header = brief["record_text"]
            if len(header)>250 or YEAR.search(header) or re.search(r"\b(?:graduated|awarded|conferred)\b",header,re.I):
                continue
            def keywords(text):
                return set(re.findall(r"[a-z]{3,}", text.lower())) - ACADEMIC_STOP
            if len(keywords(header) & keywords(detail["record_text"][:250])) < 2:
                continue
            for ent in mentions[brief["id"]]:
                same = next((x for x in mentions[detail["id"]]
                             if x["level"]==ent["level"] and x["pending"]),None)
                if same:
                    ent["pending"] = same["pending"]
    return mentions


def compute_features(candidate, rows):
    rid = candidate["id"]
    features = {t[0]: 0 for templates in TEMPLATES.values() for t in templates}
    evidence = defaultdict(list)
    def add(key, quote):
        if quote.get("evidence_quote") and quote not in evidence[key]:
            evidence[key].append(quote)
    rows = sorted(rows, key=lambda r: (r["src"], r["rel"], r["node"]["id"],
                                       r["edge"].get("page_num", 0), r["edge"].get("evidence_quote", "")))
    records, edges = {}, defaultdict(list)
    all_skills, verified = {}, {}
    for row in rows:
        if not row["edge"].get("evidence_valid"):
            continue
        rel, node = row["rel"], row["node"]
        edges[(row["src"], rel)].append(row)
        if rel in {"HAS_EXPERIENCE", "HAS_EDUCATION", "WORKED_ON"}:
            records[node["id"]] = (rel, {**node, "resume_id":rid}, row["edge"])
        if rel in {"HAS_SKILL", "USED_SKILL", "APPLIED_SKILL"}:
            all_skills[node["id"]] = node
            quote = dict(from_edge(row["edge"]), target=node["name"], target_id=node["id"],
                         relationship=rel, source=row["edge"].get("source", rel))
            add("total_skill_count", quote)
            if node.get("category") in CATEGORIES:
                add("skill_category_coverage", quote)
            if rel != "HAS_SKILL":
                verified[node["id"]] = node
                add("verified_skill_count", quote)
                add("verified_skill_ratio", quote)
                if node.get("category") in CATEGORIES:
                    add("applied_skill_diversity", quote)
    if verified:
        # Numerator evidence comes first. Include the listed-only denominator
        # as well so the reader can reconstruct the exact ratio.
        for quote in evidence["total_skill_count"]:
            if quote["target_id"] not in verified:
                add("verified_skill_ratio", quote)
    features.update(total_skill_count=len(all_skills), verified_skill_count=len(verified),
                    verified_skill_ratio=len(verified)/max(1,len(all_skills)),
                    skill_category_coverage=len({n.get("category") for n in all_skills.values()} & CATEGORIES),
                    applied_skill_diversity=len({n.get("category") for n in verified.values()} & CATEGORIES))
    education, companies, tenures, seniorities, impacts = {}, set(), [], [], set()
    credentials = education_status(records)
    pending_degrees = []
    for key, (rel, rec, link) in records.items():
        text = rec.get("record_text", "")
        if rel == "HAS_EDUCATION":
            entries = credentials[key]
            # Education records, including ongoing studies, still describe an
            # educational experience. Only completed-level scoring excludes them.
            matched = max(((entry["level"], entry["match"]) for entry in entries),
                          key=lambda item:item[0], default=None)
            for entry in entries:
                proof = snippet(rec, *entry["match"].span())
                level = entry["level"]
                if entry["pending"]:
                    pending_degrees.append(dict(level=level, degree_evidence=proof,
                                                status_evidence=entry["pending"]))
                    continue
                if level > features["max_degree_level"]:
                    features["max_degree_level"] = level
                    evidence["max_degree_level"] = []
                if level == features["max_degree_level"]:
                    add("max_degree_level", proof)
            institution = edges[(key, "AT_UNIVERSITY")]
            major = MAJOR.search(text)
            if matched:
                level, match = matched
                proof = snippet(rec, *match.span())
                if institution or rec.get("degree"):
                    # Split fragments describing the same credential count once.
                    school = institution[0]["node"]["id"] if institution else ""
                    education[(school, level, rec.get("year") or "")] = proof
                if institution and (major or YEAR.search(text)):
                    features["edu_record_completeness"] = 1
                    add("edu_record_completeness", from_edge(institution[0]["edge"]))
                    add("edu_record_completeness", proof)
                    add("edu_record_completeness", snippet(rec, *(major or YEAR.search(text)).span()))
            if major:
                features["has_stem_or_target_major"] = 1
                add("has_stem_or_target_major", snippet(rec, *major.span()))
            continue
        if rel == "WORKED_ON":
            features["project_count"] += 1
            add("project_count", from_edge(link))
        if rel == "HAS_EXPERIENCE":
            start, end = month_index(rec.get("start_ym")), month_index(rec.get("end_ym"))
            span = PERIOD.search(text)
            date_quote = snippet(rec, *span.span()) if span else from_edge(link)
            if start is not None and end is not None and start <= end:
                tenures.append((start, end))
                date_quote.update(start_ym=rec["start_ym"], end_ym=rec["end_ym"])
                for feature in ("merged_exp_months", "avg_role_tenure_months"):
                    add(feature, date_quote)
            for firm in edges[(key, "AT_COMPANY")]:
                companies.add(firm["node"]["id"])
                add("distinct_companies", dict(from_edge(firm["edge"]), target=firm["node"]["name"],
                                               relationship="AT_COMPANY"))
            for job in edges[(key, "HELD_ROLE")]:
                level = seniority(job["node"]["name"])
                proof = dict(from_edge(job["edge"]), target=job["node"]["name"],
                             seniority=level, relationship="HELD_ROLE")
                if level > features["max_seniority_level"]:
                    features["max_seniority_level"] = level
                    evidence["max_seniority_level"] = []
                if level == features["max_seniority_level"]:
                    add("max_seniority_level", proof)
                if start is not None:
                    seniorities.append((start, level, proof, date_quote))
        for match in IMPACT.finditer(text):
            proof = snippet(rec, *match.span())
            # One source line is one outcome, even if it contains multiple metrics.
            pos = text.rfind("\n", 0, match.start()) + 1
            outcome = key, pos
            if outcome not in impacts:
                impacts.add(outcome)
                add("quantified_impact_count", proof)
    features.update(merged_exp_months=merged_months(tenures), distinct_companies=len(companies),
                    avg_role_tenure_months=mean(e-s+1 for s,e in tenures) if tenures else 0,
                    quantified_impact_count=len(impacts))
    for first in seniorities:
        for later in seniorities:
            delta = later[1] - first[1]
            if first[0] < later[0] and delta > features["career_progression_delta"]:
                features["career_progression_delta"] = delta
                evidence["career_progression_delta"] = []
                for proof in (*first[2:], *later[2:]):
                    add("career_progression_delta", proof)
    certificates = dict(zip(candidate.get("certification_quotes", []),
                            candidate.get("certification_pages", [])))
    features["cert_or_multi_edu_count"] = len(certificates) + max(0, len(education)-1)
    for quote, page in certificates.items():
        add("cert_or_multi_edu_count", dict(resume_id=rid, page_num=page, evidence_quote=quote))
    if len(education) > 1:
        for proof in education.values():
            add("cert_or_multi_edu_count", proof)
    # Match the proof reconstruction against independent DISTINCT counts in Cypher.
    for key, value in candidate.get("graph_counts", {}).items():
        if value != features[key]:
            raise ValueError(f"{rid}: graph count {key}={value} differs from the supporting evidence")
        features[key] = value
    return dict(resume_id=rid, split=candidate["split"], text_hash=candidate.get("text_hash", ""),
                graph_snapshot=candidate.get("kg_snapshot"),
                features=features, evidence=dict(evidence), pending_degrees=pending_degrees)


def quantile(values, fraction):
    """Observed order statistic; no interpolated thresholds for discrete measurements."""
    return float(np.quantile(values, fraction, method="higher"))


def cohort_hash(rows):
    identities = sorted((r["resume_id"], r["text_hash"]) for r in rows)
    return hashlib.sha256(json.dumps(identities, ensure_ascii=False).encode()).hexdigest()


def fit(train):
    if not train or any(r["split"] != "train" for r in train):
        raise ValueError("Threshold calibration requires a non-empty training cohort")
    rules = []
    for dimension, templates in TEMPLATES.items():
        for i, (key, q, title, meaning) in enumerate(templates, 1):
            vals = [r["features"][key] for r in train]
            threshold = quantile(vals, q)
            formula = f"训练集 Q{q*100:.0f}（经验分位，向上取实际观测值）"
            if threshold == 0:
                positive = [v for v in vals if v > 0]
                threshold = quantile(positive, q) if positive else None
                formula += "；零值分位回退到训练集正值子集同一分位"
            active = threshold is not None
            predicate = f"c.{key} >= {threshold!r}" if active else "false"
            formula += f" = {threshold:.5g}" if active else "；快照中无正证据，规则停用"
            hits = [r for r in train if active and r["features"][key] >= threshold]
            examples = []
            for r in hits[:3]:
                proofs = r["evidence"].get(key, [])
                if not proofs:
                    raise ValueError(f"Positive feature without source evidence: {r['resume_id']} {key}")
                examples.append(dict(resume_id=r["resume_id"], feature_value=r["features"][key],
                                     **{k:v for k,v in proofs[0].items() if k!="resume_id"},
                                     evidence=proofs))
            rules.append(dict(rule_id=f"R-{dimension}-{i:02d}", dimension=dimension,
                              feature=key, title=title, business_meaning=meaning, threshold=threshold,
                              threshold_formula=formula, points=25, cypher_predicate=predicate,
                              if_then_text=f"满足 {predicate} 时，{TITLES[dimension]}加 25 分。",
                              train_hit_count=len(hits), train_hit_rate=len(hits)/len(train),
                              sample_hit_resumes=examples))
    totals = [score(r["features"], rules)[0] for r in train]
    bounds = {d:[quantile([t[d] for t in totals], q) for q in (.25, .50, .75)] for d in DIMENSIONS}
    return dict(train_size=len(train), train_ids=sorted(r["resume_id"] for r in train),
                cohort_hash=cohort_hash(train), grade_thresholds=bounds,
                grade_policy="零分缺少命中证据，统一 D；正分按训练 Q75、Q50、Q25 依次取 A、B、C，否则 D。",
                rules=rules)


def score(features, rules):
    totals = dict.fromkeys(DIMENSIONS, 0)
    hits = []
    for rule in rules:
        threshold = rule["threshold"]
        if threshold is not None and features[rule["feature"]] >= threshold:
            totals[rule["dimension"]] += rule["points"]
            hits.append(rule["rule_id"])
    return totals, hits


def evaluate(features, model):
    scores, hits = score(features, model["rules"])
    grades = {}
    for d, amount in scores.items():
        lo, mid, hi = model["grade_thresholds"][d]
        if not amount:
            grades[d] = "D"
        elif amount >= hi:
            grades[d] = "A"
        elif amount >= mid:
            grades[d] = "B"
        else:
            grades[d] = "C" if amount >= lo else "D"
    return dict(scores=scores, grades=grades, hit_rules=hits)


def sync_check(driver=None, candidates=None):
    if candidates is None:
        with connection(driver) as db:
            candidates = [compute_features(*pair) for pair in raw_rows(db)]
    train = [r for r in candidates if r["split"] == "train"]
    test = sorted((r for r in candidates if r["split"] == "test"), key=lambda r:r["resume_id"])
    # An intervention defined before scoring: early-career cohort vs. full cohort;
    # anchor selection uses only immutable IDs and never inspects the outcome.
    ranked = sorted(train, key=lambda r:(r["features"]["merged_exp_months"], r["resume_id"]))
    a, b = fit(ranked[:max(1,len(ranked)//2)]), fit(train)
    changes = [dict(rule_id=x["rule_id"], threshold_a=x["threshold"], threshold_b=y["threshold"])
               for x,y in zip(a["rules"], b["rules"]) if x["threshold"] != y["threshold"]]
    anchors = []
    for r in test[:3]:
        ea, eb = evaluate(r["features"], a), evaluate(r["features"], b)
        anchors.append(dict(resume_id=r["resume_id"], features=r["features"], a=ea, b=eb,
                            changed=ea["scores"] != eb["scores"] or ea["grades"] != eb["grades"],
                            changed_hit_rules=sorted(set(ea["hit_rules"]) ^ set(eb["hit_rules"]))))
    report = dict(design="A 为净工龄最短的一半训练样本（同值按 ID），B 为完整训练集；固定测试 ID 排序前 3 人。",
                  test_cohort_hash=cohort_hash(test), snapshot_a=a, snapshot_b=b,
                  threshold_changes=changes, anchors=anchors)
    write_json(PROCESSED / "sync_check_report.json", report)
    return report


def group_rule_evidence(examples):
    """Group display rows by original location while keeping the raw edge-level proofs."""
    quotes = {}
    for evidence in examples:
        key = (evidence["resume_id"], evidence["page_num"], evidence.get("record_id"),
               " ".join(evidence["evidence_quote"].split()))
        if key not in quotes:
            quotes[key] = dict(resume_id=key[0], page_num=key[1], record_id=key[2], evidence_quote=key[3], skills=[])
        skill = evidence.get("target")
        if (skill and evidence.get("relationship") in {"HAS_SKILL", "USED_SKILL", "APPLIED_SKILL"}
                and skill not in quotes[key]["skills"]):
            quotes[key]["skills"].append(skill)
    return list(quotes.values())


def focus_profiles(candidates, model, ids=None):
    directory = PROCESSED / "focus_profiles"
    directory.mkdir(parents=True, exist_ok=True)
    lookup = {r["resume_id"]:r for r in candidates}
    evals = {rid:evaluate(r["features"], model) for rid,r in lookup.items()}
    if not ids:
        order = sorted(lookup)
        def pick(measure, used):
            return max((k for k in order if k not in used), key=measure)
        ids = []
        ids.append(pick(lambda k:sum(evals[k]["scores"].values()), ids))
        ids.append(pick(lambda k:lookup[k]["features"]["verified_skill_count"], ids))
        # A listed-heavy profile gives the reader a different evidence pattern.
        ids.append(pick(lambda k:lookup[k]["features"]["total_skill_count"]-
                                 lookup[k]["features"]["verified_skill_count"], ids))
    if len(set(ids)) != 3 or len(ids) != 3 or any(i not in lookup for i in ids):
        raise ValueError("--focus-ids requires exactly three distinct candidate IDs in the graph")
    outputs = []
    for rid in ids:
        row, result = lookup[rid], evals[rid]
        rules = [x for x in model["rules"] if x["rule_id"] in result["hit_rules"]]
        rule_evidence = {x["rule_id"]:row["evidence"][x["feature"]] for x in rules}
        strength = max(DIMENSIONS, key=lambda d:result["scores"][d])
        gap = min(DIMENSIONS, key=lambda d:result["scores"][d])
        f = row["features"]
        fit_advice = {
            "EDU":"核对课程与岗位任务的对应关系，面试中补充一项落地案例。",
            "EXP":"优先考察需要持续交付和跨任职环境协作的岗位，核对本人承担的职责。",
            "SKL":"可进入强调实际技术应用的岗位面试，选一项实证技能做现场演练。",
            "POT":"可进入项目驱动岗位的实践面试，进一步核对项目范围与成果归属。",
        }
        analysis = [
            f"{TITLES[strength]}得分 {result['scores'][strength]}，为此人较突出的维度。",
            f"{TITLES[gap]}得分 {result['scores'][gap]}；凡缺少原文证据的条件均未加分。",
            f"共识别 {f['total_skill_count']} 项技能，其中 {f['verified_skill_count']} 项有项目或任职实证。"
            f"可解析日期的净工龄为 {f['merged_exp_months']} 个月。",
            fit_advice[strength],
        ]
        profile = dict(resume_id=rid,split=row["split"],features=f,rule_evidence=rule_evidence,
                       analysis=analysis, **result)
        write_json(directory / f"{rid}.json", profile)
        radar({rid:result["scores"]}, directory / f"{rid}.png", "Evidence-based profile")
        lines = [f"# {rid} 简历评估", "", f"所属样本集：{row['split']}。",
                 "", f"![四维雷达图]({rid}.png)", "", *analysis, ""]
        for d in DIMENSIONS:
            lines += [f"## {TITLES[d]}　{result['scores'][d]} / 100　等级 {result['grades'][d]}", ""]
            fired = [x for x in rules if x["dimension"] == d]
            if not fired:
                lines.append("该维度未命中加分条件。")
            for rule in fired:
                lines += [f"### {rule['rule_id']}　{rule['title']}", "",
                          f"特征值 {f[rule['feature']]:.5g}，标定门槛 {rule['threshold']:.5g}，计 25 分。", ""]
                for ev in rule_evidence[rule["rule_id"]]:
                    lines.append(f"- {rid} · PDF 第 {ev['page_num']} 页　"
                                 + " ".join(ev["evidence_quote"].split()))
                lines.append("")
        (directory / f"{rid}.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
        outputs.append(profile)
    # Remove only the generated triplets for obsolete focus selections.
    for path in directory.iterdir():
        if path.suffix in {".md",".png",".json"} and path.stem in lookup and path.stem not in ids:
            path.unlink()
    return outputs


def _store_scores(tx, updates):
    tx.run("MATCH (l:ResumeKGWriteLock {id:$owner}) SET l.scoring_token=l.token", owner=OWNER).consume()
    result = tx.run("""
        UNWIND $rows AS row
        MATCH (c:ResumeKG:Candidate {id:row.id,kg_owner:$owner,kg_snapshot:row.snapshot})
        SET c += row.properties RETURN count(c) AS count
        """, rows=updates, owner=OWNER).single(strict=True)
    if result["count"] != len(updates):
        raise RuntimeError("Candidate cohort changed; rerun on a stable graph")


def run(driver=None, focus_ids=None):
    with connection(driver) as db:
        candidates = [compute_features(*pair) for pair in raw_rows(db)]
        model = fit([r for r in candidates if r["split"] == "train"])
        updates = []
        for row in candidates:
            result = evaluate(row["features"], model)
            props = dict(row["features"], hit_rules=result["hit_rules"])
            for k in DIMENSIONS:
                props["score_"+k.lower()] = result["scores"][k]
                props["grade_"+k.lower()] = result["grades"][k]
            updates.append(dict(id=row["resume_id"], snapshot=row["graph_snapshot"], properties=props))
        with db.session() as session:
            session.execute_write(_store_scores, updates)
        write_json(PROCESSED / "candidate_features.json", {"candidates":candidates})
        write_json(PROCESSED / "rules_model.json", model)
        sync_check(candidates=candidates)
        focus_profiles(candidates, model, focus_ids)
        stats = graph_stats(db)
        entity_distribution(stats, PROCESSED / "entity_distribution.png")
        return model
