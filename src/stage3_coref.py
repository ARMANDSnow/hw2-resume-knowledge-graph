"""Resolve aliases within their entity type; protect language punctuation and product names."""
from collections import defaultdict
from copy import deepcopy
import hashlib
import re
import unicodedata

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .stage2_extract import SKILL_MAP, quote_at

ALIASES = {
    "Machine Learning": ("ML",), "Natural Language Processing": ("NLP",),
    "Artificial Intelligence": ("AI",), "Amazon Web Services": ("AWS","Amazon AWS"),
    "Google Cloud Platform": ("GCP","Google Cloud"), "Microsoft Azure": ("Azure",),
    "JavaScript": ("JS","Javascript"), "Kubernetes": ("K8s",),
    "React": ("React.js","ReactJS"), "Node.js": ("NodeJS","Node JS"),
    "Microsoft SQL Server": ("MS SQL","MS SQL Server","SQL Server","MSSQL"),
    "Microsoft Excel": ("MS Excel","Excel","MS-Excel"),
    "Microsoft Office": ("MS Office","MS-Office","MS Office Suite"),
    "PostgreSQL": ("Postgres",), "Apache Spark": ("Spark",),
    "Oracle Database": ("Oracle DB",), "Salesforce CRM": ("Salesforce",),
    "Golang": ("Go",), "Spring Framework": ("Spring",),
    "Adobe Photoshop": ("Photoshop",), "scikit-learn": ("Scikit Learn","Sklearn"),
}
COMPANIES = {"IBM": ("International Business Machines","IBM Corporation"),
             "Microsoft": ("Microsoft Corporation",),"Oracle": ("Oracle Corporation",),
             "SAP": ("SAP SE",),"Google": ("Google LLC",),"Amazon": ("Amazon.com, Inc.",)}
DEGREES = {"Bachelor of Science": (r"B\.?\s?S\.?|B\.?\s?Sc\.?|Bachelor(?:'s)? of Science",),
           "Master of Science": (r"M\.?\s?S\.?|M\.?\s?Sc\.?|Master(?:'s)? of Science",),
           "Bachelor of Arts": (r"B\.?\s?A\.?|Bachelor(?:'s)? of Arts",)}
GUARDS = [("C","C++"),("C","C#"),("C++","C#"),("Java","JavaScript"),("SQL","MySQL"),
          ("SQL","PostgreSQL"),("SQL","Oracle Database"),("R","React"),(".NET","ASP.NET")]
SHARED = {"Skill","University","JobTitle","Company"}


def norm(value):
    return " ".join(unicodedata.normalize("NFKC",value).casefold().split())


def canonical(label, name):
    table = ALIASES if label=="Skill" else COMPANIES if label=="Company" else {}
    key = norm(name)
    if label=="Skill":
        key = re.sub(r"^(python|java)\s+\d+(?:\.\d+)*$",r"\1",key)
    for base,variants in table.items():
        if key in {norm(v) for v in (base,*variants)}:
            return base
    if label=="Skill" and key in SKILL_MAP:
        return SKILL_MAP[key][0]
    return re.sub(r"\s+"," ",name).strip()


def char_similarity(left,right):
    vec=TfidfVectorizer(analyzer="char",ngram_range=(1,4)).fit_transform([left.lower(),right.lower()])
    return round(float(cosine_similarity(vec[0],vec[1])[0][0]),4)


class Components:
    def __init__(self, ids):
        self.parent={i:i for i in ids}

    def root(self, i):
        while self.parent[i]!=i:
            self.parent[i]=self.parent[self.parent[i]]
            i=self.parent[i]
        return i

    def join(self,a,b):
        a,b=self.root(a),self.root(b)
        self.parent[max(a,b)]=min(a,b)


def _organization_matches(nodes, train_edges, component):
    # Conservative typo matching for named organizations: comparable full
    # names, matching distinctive tokens AND a shared observed role/school context.
    neighbors=defaultdict(set)
    per_record=defaultdict(list)
    for edge in train_edges:
        per_record[edge["properties"]["record_id"]].append(edge)
    for edges in per_record.values():
        ids={e["target"] for e in edges if e["type"] in ("AT_COMPANY","AT_UNIVERSITY","HELD_ROLE","USED_SKILL")}
        for uid in ids:
            neighbors[uid].update(ids-{uid})
    verified=[]
    for label in ("University","Company","JobTitle"):
        group=[n for n in nodes if n["label"]==label and n["id"] in neighbors and len(n["properties"]["name"])>=10]
        if len(group)<2:
            continue
        names=[norm(n["properties"]["name"]) for n in group]
        v=TfidfVectorizer(analyzer="char_wb",ngram_range=(3,5)).fit_transform(names)
        scores=cosine_similarity(v)
        for i,n in enumerate(group):
            for j in range(i):
                if scores[i,j]<.92 or not(neighbors[n["id"]]&neighbors[group[j]["id"]]):
                    continue
                # Absent a known alias, punctuation/spacing is the only safe
                # edit for organizations: subsidiaries and campuses stay separate.
                if re.sub(r"[\s,.-]+","",names[i])!=re.sub(r"[\s,.-]+","",names[j]):
                    continue
                component.join(n["id"],group[j]["id"])
                verified.append(dict(left=names[i],right=names[j],similarity=round(float(scores[i,j]),4)))
    return verified


def reference_chains(graph, by_id):
    chains=[]
    local=defaultdict(list)
    for e in graph["edges"]:
        local[e["properties"]["record_id"]].append(e)
    for d in graph["documents"]:
        rid=d["resume_id"]
        for r in d["records"]:
            txt, record_id=r["record_text"],r["record_id"]
            # Require the organization or project antecedent to precede its
            # generic reference within the same record.
            candidates=[(rid,r"\b(?:I(?=\s+(?:am|have|was|worked|led|developed|built|can|would|will|did|created|managed|completed|learned|studied|enjoy|believe|seek|want|started|took|performed|joined|also))|my|myself|me)\b",-1)]
            if r["kind"]=="WorkRecord":
                for edge in local[record_id]:
                    if edge["type"]=="AT_COMPANY":
                        candidates.append((edge["target"],r"\bthe (?:company|firm|organization)\b",txt.find(edge["properties"]["surface"])))
                        break
            elif r["kind"]=="ProjectRecord" and record_id in by_id:
                name=by_id[record_id]["properties"]["name"]
                candidates.append((record_id,r"\b(?:the project|this project|this system|the application)\b",txt.find(name)))
            for antecedent,expr,position in candidates:
                for m in re.finditer(expr,txt,re.I):
                    if m.start()<=position or antecedent not in by_id:
                        continue
                    if m[0].lower()=="i" and m[0]!="I":
                        continue
                    ev=quote_at(txt,m.start(),m.end())
                    matched=[]
                    for e in local[record_id]:
                        p=e["properties"]
                        if p["evidence_quote"]==ev:
                            p["coref_antecedent"]=antecedent
                            matched.append(e["type"])
                    chains.append(dict(resume_id=rid,split=d["split"],record_id=record_id,page_num=r["page_num"],
                         surface=m[0],evidence_quote=ev,node_id=antecedent,canonical_name=by_id[antecedent]["properties"]["name"],
                         linked_relations=sorted(set(matched))))
    return chains


def resolve(graph):
    graph=deepcopy(graph)
    train={d["resume_id"] for d in graph["documents"] if d["split"]=="train"}
    by_id={n["id"]:n for n in graph["nodes"]}
    component=Components(by_id)
    canonical_ids={}
    for n in graph["nodes"]:
        if n["label"] not in SHARED:
            continue
        label,name=n["label"],n["properties"]["name"]
        key=label,norm(canonical(label,name))
        if key in canonical_ids:
            component.join(n["id"],canonical_ids[key])
        canonical_ids.setdefault(key,n["id"])
    train_edges=[e for e in graph["edges"] if e["properties"]["resume_id"] in train]
    fuzzy_pairs=_organization_matches(graph["nodes"],train_edges,component)
    groups=defaultdict(list)
    for uid in by_id:
        groups[component.root(uid)].append(by_id[uid])
    replacement={}
    merged=[]
    for nodes in groups.values():
        first=nodes[0]
        if first["label"] not in SHARED:
            merged.append(first)
            replacement[first["id"]]=first["id"]
            if first["label"]=="Education":
                degree=first["properties"].get("degree","")
                for base,(pattern,) in DEGREES.items():
                    if re.fullmatch(pattern,degree,re.I):
                        first["properties"]["canonical_degree"]=base
                        break
            continue
        names=[n["properties"]["name"] for n in nodes]
        label=first["label"]
        name=canonical(label,min(names,key=lambda s:(len(s),s)))
        uid=label+":"+norm(name)
        all_aliases=sorted(set(names+[name]))
        props={**first["properties"],"name":name,"canonical_name":name,"aliases":all_aliases}
        merged.append(dict(id=uid,label=label,properties=props))
        for n in nodes:
            replacement[n["id"]]=uid
    # Preserve independent evidence from multiple records and pages.
    retained,seen=[],set()
    examples=defaultdict(dict)
    for e in graph["edges"]:
        e["source"],e["target"]=replacement[e["source"]],replacement[e["target"]]
        p=e["properties"]
        key=(e["source"],e["target"],e["type"],p["record_id"],p["evidence_quote"],p.get("source"))
        if key not in seen:
            retained.append(e)
            seen.add(key)
        if p["resume_id"] in train and e["type"] in {"HAS_SKILL","AT_COMPANY","AT_UNIVERSITY","HELD_ROLE"}:
            alias=p["surface"]
            examples[e["target"]].setdefault((alias,p["resume_id"]),dict(alias=alias,resume_id=p["resume_id"],page_num=p["page_num"],evidence_quote=p["evidence_quote"]))
    graph.update(nodes=merged,edges=retained)
    by_id={n["id"]:n for n in merged}
    alias_groups=[]
    for uid,samples in examples.items():
        distinct={}
        for sample in samples.values():
            # Two case styles alone do not constitute a meaningful alias pair.
            distinct.setdefault(norm(sample["alias"]),[]).append(sample)
        pair=next(((a,b) for i,va in enumerate(distinct.values()) for vb in list(distinct.values())[i+1:]
                   for a in va for b in vb if a["resume_id"]!=b["resume_id"]),None)
        if pair:
            n=by_id[uid]
            alias_groups.append(dict(node_id=uid,canonical_name=n["properties"]["name"],aliases=n["properties"]["aliases"],
                                     examples=list(pair),method="canonical/abbreviation or verified organization cluster"))
    controls=[]
    for a,b in GUARDS:
        ia,ib="Skill:"+norm(a),"Skill:"+norm(b)
        if ia!=ib and ia in examples and ib in examples:
            controls.append(dict(names=[a,b],node_ids=[ia,ib],similarity=char_similarity(a,b),
                    reason="不同规范技术实体，技能禁止模糊合并，保留有语义的符号与完整产品名",
                    examples=[next(iter(examples[uid].values())) for uid in (ia,ib)]))
    for group in graph.get("disambiguation_groups",[]):
        for sense in group["senses"]:
            sense["node_id"]=replacement[sense["node_id"]]
            sense["edge_source"]=replacement[sense["edge_source"]]
            sense["name"]=by_id[sense["node_id"]]["properties"]["name"]
    chains=reference_chains(graph,by_id)
    before=len(replacement)
    graph["coref_audit"]=dict(cross_document_groups=alias_groups,within_document_chains=chains,negative_controls=controls,
                 verified_fuzzy_pairs=fuzzy_pairs,nodes_before=before,nodes_after=len(merged),
                 compression_ratio=round((before-len(merged))/max(before,1),5))
    return graph
