"""Resolve ambiguous company/product and degree/product mentions using local context."""
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .stage2_extract import ROLE, quote_at
from .provenance import validate_quote

# Each vendor sense requires evidence that the person worked at that entity.
# A product mention must name the product or supply an explicit database/ERP context.
PRODUCTS = {
    "Microsoft": r"Microsoft\s+(?:SQL Server|Azure|Excel|Office|Windows|Power BI|Access|Word|PowerPoint|Visual Studio|Teams|SharePoint|Dynamics(?:\s+365)?)",
    "Amazon": r"Amazon\s+(?:Web Services|AWS|EC2|S3|Redshift|DynamoDB|CloudWatch|SageMaker|Lambda)",
    "Google": r"Google\s+(?:Cloud(?: Platform)?|Analytics|AdWords|BigQuery|Sheets|Data Studio|Firebase|Tag Manager|Maps API|Colab)",
    "IBM": r"IBM\s+(?:DB2|SPSS|Watson|Cognos|WebSphere|Cloud|Bluemix|Rational|MQ(?: Series)?|Mainframe)",
    "Oracle": r"Oracle\s+(?:Database|SQL|PL/SQL|DB(?:MS)?|RDBMS|PeopleSoft|ERP|EBS|Financials|Fusion|Forms|\d{1,2}[cig]\b)",
    "SAP": r"SAP\s+(?:ERP|HANA|S/4HANA|R/3|ABAP|FICO|FI/CO|Business(?: One|Objects)?|MM|SD|BW|ECC)",
    "Cisco": r"Cisco\s+(?:IOS|Packet Tracer|ASA|routers?|switches?|UCS|Webex)",
    "Adobe": r"Adobe\s+(?:Photoshop|Illustrator|InDesign|Premiere(?: Pro)?|Experience Manager|Acrobat|Creative (?:Suite|Cloud)|Analytics|Dreamweaver)",
    "Salesforce": r"Salesforce\s+(?:CRM|Apex|Lightning|Platform|Sales Cloud|Service Cloud)",
    "Intel": r"Intel\s+(?:Quartus|oneAPI|OpenVINO|VTune|MPI)",
    "Shell": r"Shell\s+(?:[Ss]cripting|scripts?)",
}
VENDOR_HINT = re.compile(r"(?i)\b(?:developer|scientist|engineer|manager|consultant|intern|analyst|architect|associate|specialist|director|lead|administrator)\b")
PROFILES = {
    "company":"employer employee employment work experience hired worked at intern engineer developer manager company corporation team role responsibilities",
    "product":"software skills tools technologies database programming expertise developed using platform technology environment applications Microsoft Office Excel SQL cloud",
    "job_rank":"associate position job employment developer engineer colleague role title senior consultant manager rank",
    "degree":"university education degree master science major graduate bachelor studies college academic engineering computer science",
}


@lru_cache(maxsize=8192)
def _semantics(window, senses):
    matrix=TfidfVectorizer(ngram_range=(1,2),stop_words="english").fit_transform([window,*[PROFILES[s] for s in senses]])
    return tuple(float(v) for v in cosine_similarity(matrix[0],matrix[1:])[0])


def scores(record, start, end, senses, header_role=False):
    txt=record["record_text"]
    window=" ".join([*txt[:start].split()[-15:],txt[start:end],*txt[end:].split()[:15]])
    tokens=record["entities"]
    labels={e["label"] for e in tokens}
    values={}
    for sense,sim in zip(senses,_semantics(window,tuple(senses)),strict=True):
        if sense=="company":
            loc=1. if record["kind"]=="WorkRecord" and header_role else .08
            coh=float(("job title" in labels or bool(ROLE.search(window))) and header_role)
        elif sense=="job_rank":
            loc=float(record["kind"]=="WorkRecord")
            coh=float("job title" in labels or bool(ROLE.search(window)))
        elif sense=="degree":
            loc=float(record["kind"]=="EduRecord")
            coh=float(bool(labels & {"university","major","degree"}) or bool(re.search(r"(?i)\b(?:university|college|science|engineering)\b",window)))
        else:
            loc={"SKILLS":1.,"PROFILE":.65,"WorkRecord":.65,"ProjectRecord":.85}.get(record["kind"],.1)
            if header_role:
                loc=.1
            coh=float("skill" in labels or bool(re.search(r"(?i)\b(?:software|tools|skills|office|server|database|cloud|excel|azure|services|analytics|photoshop)\b",window)))
        values[sense]=dict(tfidf_cosine=round(sim,4),section_prior=loc,record_coherence=coh,
                           total=round(.5*sim+.3*loc+.2*coh,4))
    return values


def _employer_header(record, brand):
    text=record["record_text"]
    direct=re.search(rf"(?i)\b(?:having worked|worked|was employed) (?:for|by|at) ({brand})\b",text)
    if direct:
        return next(m for m in re.finditer(r"(?i)\b"+brand+r"\b",text) if m.start()==direct.start(1))
    tagged=re.search(rf"(?im)name and address of employer[ \t]*\n\s*({brand})\b",text)
    if tagged:
        return next(m for m in re.finditer(r"(?i)\b"+brand+r"\b",text) if m.start()==tagged.start(1))
    for m in re.finditer(r"(?i)\b"+re.escape(brand)+r"\b",text[:350]):
        line_start=text.rfind("\n",0,m.start())+1
        end=text.find("\n",m.end())
        end=len(text) if end<0 else end
        line=text[line_start:end].strip()
        around=text[max(0,line_start-120):min(len(text),end+125)]
        # References to a vendor within its own products, client lists or an
        # education/training provider cannot establish an employer.
        if re.search(PRODUCTS[brand],line,re.I) or re.search(r"(?i)\b(?:client|customer|certified|certification|courses?|partner|vendor|training|project for|worked with)\b",line):
            continue
        bare=re.fullmatch(rf"(?i)[•●\s]*{brand}(?:\s+(?:corporation|corp\.?|inc\.?|technologies|india|labs|solutions|development cent(?:er|re)))?(?:[\s,|–—-]+(?:[A-Z][a-z]+(?:[, ]+[A-Z][a-z]+)?|(?:19|20)\d\d.*))?\s*", line)
        hiring=re.search(rf"(?i)\b(?:employer|company|employed (?:by|at)|working at|worked at|intern at|engineer at)\s*[:–-]?\s*{brand}\b",line)
        # The same line may format role | employer | time.
        header_role=VENDOR_HINT.search(line) and len(line)<135 and re.search(r"[|—–]|\s-\s|\bat\b",line,re.I)
        if (bare or hiring or header_role) and VENDOR_HINT.search(around):
            return m
    return None


def resolve(extractions):
    graph=deepcopy(extractions)
    nodes={n["id"]:n for n in graph["nodes"]}
    pages={(d["resume_id"],p["page_num"]):p["text"] for d in graph["documents"] for p in d["pages"]}
    per_record=defaultdict(list)
    for e in graph["edges"]:
        per_record[e["properties"]["record_id"]].append(e)
    evidence=defaultdict(lambda:defaultdict(list))
    def attach(rid,record,src,dst,rel,a,b,**extra):
        txt=record["record_text"]
        p=dict(resume_id=rid,record_id=record["record_id"],page_num=record["page_num"],
               evidence_quote=quote_at(txt,a,b),surface=txt[a:b],**extra)
        p["evidence_valid"]=validate_quote(pages[rid,record["page_num"]],p["evidence_quote"])
        # Only spans from a record already proven to be a literal slice of the PDF
        # are admitted. The independent verifier reloads the PDF for every edge.
        if not p["evidence_valid"] or not validate_quote(txt,p["evidence_quote"]):
            raise ValueError("invalid record excerpt")
        node_edge=next((e for e in per_record[record["record_id"]] if e["source"]==src and e["target"]==dst and e["type"]==rel
                       and e["properties"]["surface"].casefold()==p["surface"].casefold()),None)
        if node_edge:
            return node_edge
        edge=dict(source=src,target=dst,type=rel,properties=p)
        graph["edges"].append(edge)
        per_record[record["record_id"]].append(edge)
        return edge

    def sense_row(edge,sc):
        p=edge["properties"]
        node=nodes[edge["target"]]
        return dict(node_id=node["id"],name=node["properties"]["name"],label=node["label"],
            edge_type=edge["type"],edge_source=edge["source"],resume_id=p["resume_id"],record_id=p["record_id"],
            page_num=p["page_num"],evidence_quote=p["evidence_quote"],scores=sc)

    for d in graph["documents"]:
        rid=d["resume_id"]
        for r in d["records"]:
            record_id,txt,kind=r["record_id"],r["record_text"],r["kind"]
            if not txt:
                continue
            for brand,pattern in PRODUCTS.items():
                if brand.casefold() not in txt.casefold():
                    continue
                senses=("company","product")
                if kind=="WorkRecord" and record_id in nodes:
                    main=next((e for e in per_record[record_id] if e["type"]=="AT_COMPANY"),None)
                    m=_employer_header(r,brand)
                    if m and (not main or re.search(r"(?i)\b"+brand+r"\b",main["properties"]["surface"])):
                        sc=scores(r,m.start(),m.end(),senses,True)
                        if sc["company"]["total"]>sc["product"]["total"]:
                            if not main:
                                uid="Company:"+brand.casefold()
                                nodes.setdefault(uid,dict(id=uid,label="Company",properties=dict(name=brand)))
                                main=attach(rid,r,record_id,uid,"AT_COMPANY",m.start(),m.end())
                            if d["split"]=="train" and brand.casefold() in main["properties"]["evidence_quote"].casefold():
                                evidence[brand]["company"].append(sense_row(main,sc))
                if kind not in ("SKILLS","PROFILE","WorkRecord","ProjectRecord") or (kind in ("WorkRecord","ProjectRecord") and record_id not in nodes):
                    continue
                m=re.search(pattern,txt,re.I)
                if not m:
                    continue
                sc=scores(r,m.start(),m.end(),senses)
                if sc["product"]["total"]<=sc["company"]["total"]:
                    continue
                source={"WorkRecord":"work_verified","ProjectRecord":"project_verified"}.get(kind,"listed")
                uid="Skill:"+m[0].casefold()
                category="Database" if brand in ("Oracle","IBM") or "SQL" in m[0] else "Management_Business"
                if re.search(r"cloud|aws|web services|azure|cisco",m[0],re.I):
                    category="Cloud_DevOps"
                nodes.setdefault(uid,dict(id=uid,label="Skill",properties=dict(name=m[0],category=category)))
                match=attach(rid,r,rid,uid,"HAS_SKILL",m.start(),m.end(),source=source)
                if source!="listed":
                    rel="USED_SKILL" if kind=="WorkRecord" else "APPLIED_SKILL"
                    match=attach(rid,r,record_id,uid,rel,m.start(),m.end())
                if d["split"]=="train":
                    evidence[brand]["product"].append(sense_row(match,sc))
            if d["split"]!="train":
                continue
            # Associate denotes a job rank (e.g. Senior Associate) as well
            # as a formal academic degree (Associate of Applied Science).
            for edge in list(per_record[record_id]):
                p=edge["properties"]
                if edge["type"]=="HELD_ROLE" and (m:=re.search(r"\bAssociate\b",p["surface"],re.I)):
                    at=txt.find(p["surface"])+m.start()
                    sc=scores(r,at,at+len(m[0]),("job_rank","degree"))
                    if sc["job_rank"]["total"]>sc["degree"]["total"]:
                        evidence["Associate"]["job_rank"].append(sense_row(edge,sc))
            if kind=="EduRecord" and record_id in nodes and (m:=re.search(r"(?i)\bAssociate(?:['’]s)? (?:of|degree in) (?:Applied Science|Arts|Science|Business|Engineering)\b",txt)):
                sc=scores(r,m.start(),m.end(),("job_rank","degree"))
                if sc["degree"]["total"]>sc["job_rank"]["total"]:
                    edge=attach(rid,r,rid,record_id,"HAS_EDUCATION",m.start(),m.end())
                    evidence["Associate"]["degree"].append(sense_row(edge,sc))
            # The identical abbreviation MS can denote Master of Science or
            # Microsoft in an explicitly named software suite (e.g. MS Office).
            if kind=="EduRecord" and record_id in nodes:
                m=re.search(r"\bMS\b",txt)
                if m and re.search(r"(?i)\b(?:degree|university|college|engineering|computer|science)\b",txt):
                    sc=scores(r,m.start(),m.end(),("degree","product"))
                    if sc["degree"]["total"]>sc["product"]["total"]:
                        edge=attach(rid,r,rid,record_id,"HAS_EDUCATION",m.start(),m.end())
                        evidence["MS"]["degree"].append(sense_row(edge,sc))
            for edge in per_record[record_id]:
                if edge["type"]=="HAS_SKILL" and (m:=re.match(r"MS\b[ -]+(?:Excel|Office|SQL)",edge["properties"]["surface"])):
                    at=txt.find(m[0])
                    sc=scores(r,at,at+len(m[0]),("degree","product"))
                    if sc["product"]["total"]>sc["degree"]["total"]:
                        evidence["MS"]["product"].append(sense_row(edge,sc))
    for e in graph["edges"]:
        p=e["properties"]
        p["evidence_valid"]=validate_quote(pages[p["resume_id"],p["page_num"]],p["evidence_quote"])
        if not p["evidence_valid"]:
            raise ValueError(f"Quote mismatch: {p['record_id']} {e['type']}")
    graph["nodes"]=list(nodes.values())
    groups=[]
    for surface,by_sense in sorted(evidence.items()):
        if len(by_sense)!=2:
            continue
        rows=[max(group,key=lambda s:s["scores"][k]["total"]) for k,group in by_sense.items()]
        if len({row["node_id"] for row in rows})!=2:
            continue
        groups.append(dict(surface=surface,senses=rows))
    graph["disambiguation_groups"]=groups
    return graph
