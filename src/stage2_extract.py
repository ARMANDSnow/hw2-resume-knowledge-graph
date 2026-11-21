"""Record-local resume extraction. All offsets refer to the original PDF page text."""
import calendar
import hashlib
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from .config import RAW, read_json, write_json
from .provenance import validate_quote

LABELS = ["person", "company", "university", "degree", "major", "job title",
          "skill", "project", "date range", "certification"]
SECTIONS = {
    "EXPERIENCE": r"(?:(?:professional|work|working|employment|internship|relevant)\s+)?experience(?:s)?|employment history|work history|employment",
    "EDUCATION": r"educational qualifications?|education(?: and (?:training|certifications?|certificates|academic achievements)|al background)?|academic (?:background|qualifications?)",
    "PROJECTS": r"(?:(?:personal|academic|technical|selected|major|professional|final year)\s+)?projects?(?: worked on| and extracurricular activities)?",
    "SKILLS": r"(?:(?:technical|professional|computer|key|core|programming)\s+)?skills(?: summary| and activities| and abilities)?|skill highlights|technical proficiencies|technical expertise|core competencies",
    "CERTIFICATIONS": r"certifications?(?: and (?:licenses|courses))?|certificates|courses attended",
    "PROFILE": r"(?:professional |career )?(?:summary|profile|objective)|about me",
    "OTHER": r"key strengths|major modules(?: are)?|coursework|hobbies|personal (?:details|information)|accomplishments|declaration|academic achievements|awards(?: and honors)?|languages|interests|publications|references|activities|volunteer experience",
}
# Lowercase headings embedded in prose are deliberately excluded.
_HEADING_WORDS = "|".join(f"(?P<{k}>{v})" for k, v in SECTIONS.items())
HEADING = re.compile(r"(?<![A-Za-z])(?:" + _HEADING_WORDS + r")(?![A-Za-z])", re.I)
MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
YEAR = r"(?:19[6-9]\d|20[0-3]\d)"
DATE = rf"(?:{MONTH}\.?[\s,/’-]*{YEAR}|(?:0?[1-9]|1[012])\s*[/.-]\s*{YEAR}|{YEAR}(?:[-/]\d{{1,2}})?)"
PERIOD = re.compile(rf"(?<!\d)(?P<start>{DATE})\s*(?:[-–—−]|\bto\b|\buntil\b)\s*(?P<end>{DATE}|present|current(?:ly)?|ongoing|now|till date|to date)\b", re.I)
DEGREE = re.compile(r"\b(?:Ph\.?\s?D\.?|Doctor(?:ate| of [A-Z][a-z]+)|Masters?(?:['’]s)?|M\.?\s?Sc\.?|M\.?\s?S\.?|MBA|Bachelors?(?:['’]s)?|B\.?\s?Sc\.?|B\.?\s?S\.?|B\.?\s?Tech\.?|Associate(?:['’]s)?\s+(?:degree|of))(?=\s|[,.(]|$)", re.I)
ROLE = re.compile(r"\b(?:senior |junior |lead |principal |associate |assistant |staff )?(?:[A-Za-z][\w&/-]*[ \t]+){0,3}(?:engineer|developer|intern|analyst|scientist|consultant|manager|director|architect|designer|administrator|coordinator|officer|specialist|technician|teacher|accountant|executive|associate|lead)\b", re.I)
SCHOOL = re.compile(r"\b(?:university|college|institute|polytechnic|school)\b", re.I)
CATEGORIES = {
    "Programming": "Python|Java|C++|C#|C|F#|R|Golang|Go|Rust|Scala|Kotlin|Swift|Ruby|Perl|MATLAB|SAS|Objective-C|Bash|Shell Scripting|Shell scripting|PowerShell|Haskell|Dart",
    "Data_AI": "Machine Learning|ML|Deep Learning|Natural Language Processing|NLP|Artificial Intelligence|AI|TensorFlow|PyTorch|Pandas|NumPy|Scikit-learn|Tableau|Power BI|Microsoft Excel|MS Excel|Excel|Spark|Apache Spark|Hadoop|Data Analysis|Data Analytics|Statistics|Data Visualization|Big Data|Computer Vision|ETL",
    "Database": "SQL|MySQL|PostgreSQL|Postgres|Microsoft SQL Server|MS SQL Server|MS SQL|SQL Server|T-SQL|PL/SQL|SQLite|MongoDB|Redis|Oracle Database|Oracle DB|Oracle SQL|Cassandra|DynamoDB|Snowflake",
    "Cloud_DevOps": "Amazon Web Services|Amazon AWS|AWS|Microsoft Azure|Azure|Google Cloud Platform|Google Cloud|GCP|Docker|Kubernetes|K8s|Linux|Unix|Git|GitHub|GitLab|Jenkins|Terraform|Ansible|CI/CD|Microsoft Windows|Windows|VMware|Cisco IOS",
    "Web_Mobile": "JavaScript|Javascript|JS|TypeScript|React.js|ReactJS|React|Node.js|NodeJS|AngularJS|Angular|Vue.js|Next.js|HTML5|HTML|CSS3|CSS|PHP|jQuery|Django|Flask|Spring Boot|Spring Framework|Spring|ASP.NET|.NET|REST API|RESTful APIs|Android|iOS|Bootstrap|Express.js",
    "Management_Business": "Project Management|Agile|Scrum|Six Sigma|Salesforce CRM|Salesforce|SAP ERP|SAP|Business Analysis|Risk Management|Accounting|Microsoft Office|MS Office|PowerPoint|Adobe Photoshop|Photoshop|Adobe Illustrator|Jira|Confluence|Financial Analysis|Change Management|Supply Chain Management|Stakeholder Management",
}
SKILL_MAP = {s.casefold(): (s, cat) for cat, skills in CATEGORIES.items() for s in skills.split("|")}
SKILL_PATTERN = re.compile(r"(?<![\w+#])(?:" + "|".join(re.escape(s) for s in sorted(SKILL_MAP, key=len, reverse=True)) + r")(?![\w+#])", re.I)
MODEL_IDS = ("urchade/gliner_medium-v2.1", "urchade/gliner_small-v2.1")


def ym(value, end=False):
    if re.fullmatch(r"present|current(?:ly)?|ongoing|now|till date|to date", value, re.I):
        return "2026-11"  # Submission snapshot date, held fixed for reproducible scoring.
    year = re.search(YEAR, value)
    if not year:
        return ""
    month = re.search(MONTH, value, re.I)
    if month:
        n = list(calendar.month_abbr).index(month[0][:3].title())
    else:
        number = re.search(r"\b(\d{1,2})\s*[/.-]|[-/](\d{1,2})\b", value)
        n = int(number[1] or number[2]) if number else (12 if end else 1)
    return f"{year[0]}-{n:02}" if 1 <= n <= 12 else ""


def quote_at(text, start, end):
    """Retain a bounded excerpt including the complete match when possible."""
    lo = max(text.rfind("\n", 0, start), text.rfind(". ", 0, start)) + 1
    ends = [i for i in (text.find("\n", end), text.find(". ", end)) if i >= 0]
    hi = min(ends, default=len(text))
    lo = max(lo, start - max(10, (240 - (end-start)) // 2))
    hi = min(hi + (hi < len(text) and text[hi] == "."), lo + 240)
    return text[lo:hi].strip()


def section_spans(text, previous="PROFILE"):
    cuts = []
    current = previous
    for match in HEADING.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        prefix = text[line_start:match.start()].strip(" \t:|•▪-")
        suffix = text[match.end():].split("\n", 1)[0]
        token = match[0].strip()
        if token.casefold()=="accomplishments" and (prefix or current=="EXPERIENCE" and suffix.strip()):
            continue
        if match.lastgroup=="EXPERIENCE" and re.match(r"\s+total years",suffix,re.I):
            continue
        if token.casefold()=="project" and not token.isupper() and suffix.strip() and not suffix.lstrip().startswith(":"):
            continue
        if match.lastgroup=="PROJECTS" and re.match(r"(?i)\s*(?:management|manager|lead|architect|team|engineer|member)\b",suffix):
            continue
        if match.lastgroup=="PROJECTS" and token.casefold()=="project" and match.start() > 0 and current in ("PROJECTS","EXPERIENCE"):
            continue  # Nested Project: / Project 2: titles belong to the record splitter.
        if match.lastgroup=="OTHER" and token.casefold()=="languages" and current=="SKILLS":
            after=text[match.end():match.end()+170]
            if re.search(r"(?i)\b(?:Python|Java|SQL|C\+\+|JavaScript)\b",after):
                continue
        # Embedded headings require emphatic uppercase or a colon. A plain
        # line-initial heading followed by prose is usually a noun, not a section.
        if prefix and not token.isupper() and not suffix.lstrip().startswith(":"):
            continue
        if suffix.strip() and not token.isupper() and not suffix.lstrip().startswith((':', '|', '–', '-')):
            if not (not prefix and token.istitle() and suffix.lstrip()[:1].isupper()):
                continue
        if prefix and token.isupper() and prefix[-1:].isalnum() and token in ("EXPERIENCE", "SKILLS"):
            if match.start() > 0 and not text[match.start()-1].isspace():
                continue
        if not cuts or cuts[-1][1] != match.end():
            cuts.append((match.start(), match.end(), match.lastgroup))
            current=match.lastgroup
    begin, section = 0, previous
    for pos, heading_end, next_section in cuts:
        if text[begin:pos].strip():
            yield section, begin, pos
        begin, section = heading_end, next_section
    yield section, begin, len(text)


def _blocks(text, section):
    """Identify work dates with adjacent title lines, and project/degree headers."""
    lines = list(re.finditer(r"[^\n]+", text))
    starts = []
    if section == "EXPERIENCE":
        if re.search(r"(?im)^\s*(?:occupation or position held|name and address of employer)\s*$",text):
            starts.extend(m.start() for m in re.finditer(r"(?im)^[ \t]*dates[ \t]*$",text))
        else:
            dates=[]
            for date in PERIOD.finditer(text):
                line_start=text.rfind("\n",0,date.start())+1
                prefix=text[line_start:date.start()].strip()
                if len(prefix)>130 or re.search(r"(?i)\b(?:during|since|period of|budget|oversaw|implemented|developed|won|training)\b",prefix):
                    continue  # Narrative date ranges do not introduce employment.
                dates.append(date)
            for i, match in enumerate(dates):
                line_idx = next((j for j,l in enumerate(lines) if l.end()>=match.start()),0)
                first=line_idx
                line_prefix=text[lines[first].start():match.start()].strip()
                if (not line_prefix or len(line_prefix)<4) and line_idx:
                    for j in range(line_idx-1,max(-1,line_idx-3),-1):
                        prev=lines[j][0].strip()
                        if not prev or len(prev)>105 or prev[:1] in "•●▪-*·" or PERIOD.search(prev):
                            break
                        header=(ROLE.search(prev) or re.search(r"(?i)\b(?:company name|ltd|inc|gmbh|corp|limited|private)\b",prev))
                        if not header or re.search(r"(?i)^(?:built|managed|using|used|led|improved|created|designed|implemented|in |as |during|responsible|the )\b",prev):
                            break
                        first=j
                leading=text[:lines[first].start()]
                if i or len(leading.strip())>160 or re.search(rf"{MONTH}\.?\s+{YEAR}",leading,re.I):
                    starts.append(lines[first].start())
    elif section == "EDUCATION":
        prior = False
        for i, l in enumerate(lines):
            if not DEGREE.search(l[0]):
                continue
            if prior:
                start = l.start()
                if i and len(lines[i-1][0].strip())<90 and SCHOOL.search(lines[i-1][0]) and not re.search(r"(?i)recipient|fellowship|award|gpa|distinction",lines[i-1][0]) and not DEGREE.search(lines[i-1][0]):
                    start = lines[i-1].start()
                starts.append(start)
            prior = True
    elif section == "PROJECTS":
        explicit=[l.start() for l in lines if re.match(r"(?i)^\s*(?:(?:final year|academic)\s+)?project\s*(?:\d+\s*)?[:–-]",l[0])]
        if explicit:
            starts.extend(explicit)
        else:
            for i,l in enumerate(lines[1:],1):
                title=l[0].strip()
                following=lines[i+1][0].strip() if i+1<len(lines) else ""
                if (4<len(title)<=85 and (title.istitle() or title.isupper()) and len(title.split())>=2
                    and re.match(r"(?i)^(?:built|developed|designed|implemented|created|description|tools)\b",following)
                    and not re.search(r"[.,:;@]|https|resume|curriculum",title,re.I)):
                    starts.append(l.start())
    elif section=="PROFILE":
        # A direct employment claim can occur in a summary. Keep just the
        # clause as an undated job record so unrelated summary skills stay listed.
        for claim in re.finditer(r"(?i)\b(?:having worked|worked|was employed) (?:for|by|at) [A-Z][a-zA-Z&.-]*(?: [A-Z][A-Za-z&.-]*){0,3} for (?:a period of )?\d+ years?",text):
            if claim.start():
                yield section,0,claim.start()
            yield "EXPERIENCE",claim.start(),claim.end()
            if claim.end()<len(text):
                yield section,claim.end(),len(text)
            return
    nested = list(re.finditer(r"(?im)(?:^|(?<=\n))[ \t]*(?:project\s*(?:\d+\s*)?[:–-])", text)) if section == "EXPERIENCE" else []
    cuts = sorted(set([0, len(text), *starts, *(m.start() for m in nested)]))
    nested_at = {m.start() for m in nested}
    active = section
    for start, end in zip(cuts, cuts[1:]):
        if start in nested_at:
            active = "PROJECTS"
        elif start in starts:
            active = section
        if text[start:end].strip():
            yield active, start, end


def records_for(doc):
    records = []
    previous = "PROFILE"
    stacked=any(len(re.findall(r"(?im)^\s*(?:work experience|skills|education|certifications?|profile summary)\s*$",p["text"][-450:]))>=3 for p in doc["pages"])
    for page in doc["pages"]:
        text = page["text"]
        spans=list(section_spans(text,previous))
        if stacked:
            # Some two-column PDFs emit dates first and all section titles last.
            # Do not attach those dates or sidebar skills to an arbitrary job.
            # Admit only adjacent, unambiguous title/company or degree/school lines.
            local=[]
            lines=list(re.finditer(r"[^\n]+",text))
            for i,l in enumerate(lines[:-1]):
                line,following=l[0].strip(),lines[i+1][0].strip()
                if ROLE.search(line) and len(line)<=85 and re.search(r"(?i)\b(?:ltd|limited|holding group|cement co|pvt|llc|corp)\b",following) and len(following)<95:
                    local.append(("EXPERIENCE",l.start(),lines[i+1].end()))
                elif DEGREE.fullmatch(line.rstrip(".")) and (SCHOOL.search(following) or following.isupper()):
                    local.append(("EDUCATION",l.start(),lines[i+1].end()))
            spans=[]
            pos=0
            for labeled,a,b in local:
                if a<pos:
                    continue
                spans.extend([("OTHER",pos,a),(labeled,a,b)])
                pos=b
            spans.append(("OTHER",pos,len(text)))
        elif previous=="PROJECTS" and page["page_num"]>1 and spans and spans[0][0]=="PROJECTS" and spans[0][1]==0:
            typ,lo,hi=spans[0]
            anchor=re.search(r"(?im)^\s*(?:project\s*\d+\s*[:–-])",text[:hi])
            # A page header and carry-over description are not a new named project.
            spans[:1]=[("OTHER",0,anchor.start()),(typ,anchor.start(),hi)] if anchor else [("OTHER",0,hi)]
        for section, off, hi in spans:
            previous = section
            for typ, a, b in _blocks(text[off:hi], section):
                lo, end = off+a, off+b
                while lo < end and text[lo].isspace():
                    lo += 1
                while end > lo and text[end-1].isspace():
                    end -= 1
                if lo == end:
                    continue
                kind = {"EXPERIENCE":"WorkRecord", "EDUCATION":"EduRecord", "PROJECTS":"ProjectRecord"}.get(typ, typ)
                records.append(dict(record_id=f"{doc['resume_id']}:r{len(records)+1}", kind=kind,
                    page_num=page["page_num"], char_start=page["char_start"]+lo, char_end=page["char_start"]+end,
                    page_start=lo, page_end=end, record_text=text[lo:end]))
    return records


def windows(text):
    # GLiNER tokenizes words again. Bound both whitespace words and punctuation.
    tokens = list(re.finditer(r"\w+|[^\w\s]", text))
    for start in range(0, len(tokens), 168):
        group = tokens[start:start+192]
        yield group[0].start(), text[group[0].start():group[-1].end()]
        if start + 192 >= len(tokens):
            break


class EntityRecognizer:
    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model = None
        self.model_name = os.environ.get("GLINER_MODEL") or MODEL_IDS[0]
        self.device = "cache"

    def _load(self):
        import torch
        from gliner import GLiNER
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        if self.device == "cpu":
            torch.set_num_threads(min(6, os.cpu_count() or 2))
        options = [self.model_name] if os.getenv("GLINER_MODEL") else MODEL_IDS
        for index, model_name in enumerate(options):
            try:
                source = RAW/"models"/Path(model_name).name
                config_file = source/"gliner_config.json"
                if config_file.exists() and (source/"model.safetensors").is_file():
                    config = read_json(config_file)
                    backbone = RAW/"models"/Path(config["model_name"]).name
                    with TemporaryDirectory() as prepared:
                        directory = Path(prepared)
                        if (backbone/"config.json").exists():
                            config["model_name"] = str(backbone)
                        write_json(directory/"gliner_config.json",config)
                        (directory/"model.safetensors").symlink_to(source/"model.safetensors")
                        self.model = GLiNER.from_pretrained(str(directory)).to(self.device)
                else:
                    self.model = GLiNER.from_pretrained(model_name).to(self.device)
                self.model.eval()
                self.model_name = model_name
                break
            except (OSError, ValueError) as exc:
                if index == len(options) - 1:
                    raise
                print(f"GLiNER {model_name} unavailable ({type(exc).__name__}), loading {options[index+1]}", flush=True)

    def entities(self, records):
        # Cache model inference independently of the sample split and graph logic.
        pending, positions = {}, []
        for r in records:
            r["entities"] = []
            for offset, text in windows(r["record_text"]):
                key = hashlib.sha256((self.model_name + "|ner-3|" + text).encode()).hexdigest()
                positions.append((r,offset,key))
                if not (self.cache_dir/f"{key}.json").exists():
                    pending[key] = text
        if pending and self.model is None:
            requested = self.model_name
            self._load()
            if self.model_name != requested:
                self.entities(records)
                return
        rows = sorted(pending.items(), key=lambda item: len(item[1]))
        batch_size = int(os.getenv("GLINER_BATCH_SIZE", "6"))
        for i in range(0, len(rows), batch_size):
            group = rows[i:i+batch_size]
            args = ([s for _,s in group], LABELS)
            try:
                batch = self.model.run(*args, threshold=.39, flat_ner=False, batch_size=batch_size)
            except (RuntimeError, NotImplementedError):
                if self.device != "mps":
                    raise
                self.model.to("cpu")
                self.device = "cpu"
                batch = self.model.run(*args, threshold=.39, flat_ner=False, batch_size=batch_size)
            for (key,s), result in zip(group, batch, strict=True):
                output = [dict(text=s[e["start"]:e["end"]],label=e["label"],start=e["start"],end=e["end"],
                               score=round(float(e["score"]),4)) for e in result]
                write_json(self.cache_dir/f"{key}.json",output)
        for r, offset, key in positions:
            r["entities"].extend({**e,"start":e["start"]+offset,"end":e["end"]+offset} for e in read_json(self.cache_dir/f"{key}.json"))
        for r in records:
            ents = {(e["start"],e["end"],e["label"]):e for e in r["entities"]}
            r["entities"] = sorted(ents.values(), key=lambda e:e["start"])


def match_entity(record, label, header_limit=420):
    # Employer and role must be in the record header. Do not turn tool vendors,
    # clients or a project team's subcontractor from a bullet into the employer.
    text = record["record_text"]
    candidates = []
    for ent in record["entities"]:
        if ent["label"] != label or ent["start"] >= header_limit or len(ent["text"]) > 135:
            continue
        prefix = text[:ent["start"]]
        line = prefix.rsplit("\n",1)[-1]
        if label in {"company", "job title"}:
            before_first_bullet=re.split(r"[•●▪\uf0b7]",text,1)[0]
            if ent["start"]>=len(before_first_bullet):
                continue
            if label=="company":
                name=" ".join(ent["text"].split())
                line_start=text.rfind("\n",0,ent["start"])+1
                line_end=text.find("\n",ent["end"])
                context=text[line_start:line_end if line_end>=0 else len(text)]
                # Technology names and generic occupations/sectors in a work
                # record remain skills or prose, even if NER labels them company.
                if (name.casefold() in SKILL_MAP or re.search(r"(?i)\bindustry$",name)
                    or re.search(r"(?i)\b(?:across|providing|responsible for|maintained|assisted|certified by|serviced|attended)\b",line)
                    or (len(name)<=4 and name.isupper() and name!=context.strip() and not re.search(r"(?i)\b(?:employer|company|employed by|worked at|engineer at)\b",context))
                    or (line_start>150 and re.search(r"(?im)^(?:organized|enforced|promoted|certified|developed|maintained|implemented|facilitated)\b",prefix))):
                    continue
                if (re.search(r"(?i)\b(?:company name|name of company|current company|confidential|city , state|hp-unix|state assist)\b", " ".join(text[:145].split()))
                    or re.search(r"(?i)\b(?:managed|using|for client|developed|participated|received|delivered|project|provided|monitoring|supported|installation|configured|within|responsible)\b",context)
                    or len(context)>140 or re.fullmatch(r"(?i)(?:company|client|suppliers?|contractors?|stakeholders?|industry|team|partners?|state|city|department|recruitment)",name)
                    or name.islower() or len(name)<2):
                    continue
                if re.search(r"(?i)\b(?:Oracle|Microsoft|IBM|Amazon|Adobe|Google|SAP)\b",name) and not (
                    re.fullmatch(r"(?i)\s*(?:Oracle|Microsoft|IBM|Amazon|Adobe|Google|SAP)(?: (?:corp(?:oration)?|inc\.?|global services|india))?\s*",context)
                    or re.search(r"(?i)(?:employer|company|worked at|employed by)\s*:?\s*$",line)):
                    continue
            if label=="job title" and re.search(r"(?i)\b(?:Oracle SQL Developer|form developer|application server|SQL Server|software suite|IDE)\b",ent["text"]):
                continue
            if re.search(r"(?im)^\s*[●•▪]\s+(?:built|developed|managed|designed|led|implemented|conducted)\b", prefix):
                continue
            if re.search(r"(?i)(?:using|knowledge of|experience with|responsible for|built|implemented|managed|supported|led|on|client)\b.{0,45}$", line):
                continue
            if label == "company" and re.match(r"(?i)(?:microsoft (?:office|excel|azure|sql)|google (?:cloud|analytics)|amazon (?:web services|aws)|oracle (?:database|db)|sap erp)\b", ent["text"]):
                continue
        candidates.append(ent)
    if candidates:
        return max(candidates, key=lambda e: e["score"] - min(e["start"]/1000,.5))


def main_facts(record):
    text = record["record_text"]
    kind = record["kind"]
    facts = {}
    if kind == "WorkRecord":
        date = PERIOD.search(text)
        header_limit = min(380, max((date.end()+130 if date else 260), 180))
        company = match_entity(record, "company", header_limit)
        explicit=re.search(r"(?im)^\s*Name and address of employer[ \t]*\n\s*([^\n]{2,100})",text)
        if not explicit:
            explicit=re.search(r"(?i)\b(?:having worked|worked|was employed) (?:for|by|at) (.+?) for (?:a period of )?\d+ years?",text)
        if explicit:
            company=dict(text=explicit[1].strip(),start=explicit.start(1),end=explicit.end(1))
        if company and (re.search(r"(?i)\b(?:Company Name|City , State|employer name)\b",company["text"])
                        or re.fullmatch(r"(?i)(?:city|state|company|employer|client|university|confidential)",company["text"].strip())):
            company=None
        title = match_entity(record, "job title", header_limit)
        if (labeled:=re.search(r"(?im)^\s*Occupation or position held[ \t]*\n\s*([^\n]{2,100})",text)):
            title=dict(text=labeled[1].strip(),start=labeled.start(1),end=labeled.end(1))
        if not title:
            for line in text[:header_limit].splitlines()[:4]:
                m = ROLE.search(line)
                if m and len(line.strip()) <= 120 and not re.search(r"(?i)\b(?:Oracle|SQL Server|using|requirements|platform|tool)\b",line) and not re.search(r"(?i)\b(developed|served|managed|supported|worked)\b", line[:m.end()]):
                    pos = text.index(line)+m.start()
                    title = dict(text=m[0],start=pos,end=pos+len(m[0]))
                    break
        if date:
            a,b = ym(date["start"]), ym(date["end"],end=True)
            if a and b and b >= a:
                facts.update(start_ym=a,end_ym=b)
        return facts,company,title
    if kind == "EduRecord":
        school = match_entity(record, "university", 650)
        degree = match_entity(record, "degree", 550)
        major = match_entity(record, "major", 550)
        if not degree and (m := DEGREE.search(text)):
            degree = dict(text=m[0],start=m.start(),end=m.end())
        facts.update(degree=degree["text"] if degree else "", major=major["text"] if major else "",
                     year=next((m[0] for m in re.finditer(YEAR,text)), ""))
        return facts,school,None
    return facts,None,None


def skill_mentions(record):
    text = record["record_text"]
    occupied = []
    for m in SKILL_PATTERN.finditer(text):
        occupied.append((m.start(),m.end()))
        canonical, cat = SKILL_MAP[m[0].casefold()]
        around = text[max(0,m.start()-26):min(len(text),m.end()+26)]
        reason = None
        # Acronyms such as R or C are skills only within a technical context.
        if canonical.lower() in {"c","r","go","ai","ml","js"} and (
            m[0].islower() or (canonical.lower() in {"c","r","go"} and not
            re.search(r"(?i)languages?|programming|\b(?:Python|Java|C\+\+|Ruby|Golang|Scala|RStudio|coding|SQL|code|MATLAB|SAS|software)\b", around))
        ):
            reason = "短词缺少编程语境或为普通词"
        if canonical == "Spring" and re.search(r"(?i)Spring\s*(?:term|semester|20\d\d|19\d\d)", around):
            reason = "学期或季节"
        if canonical in {"AI","ML"} and re.search(r"\d\s*(?:ml|mL)\b", around):
            reason = "计量单位"
        yield m.start(),m.end(),m[0],cat,reason
    # Discover additional, named technical skills: retain their raw NER spans
    # even when no controlled vocabulary category is sufficiently reliable.
    for ent in record["entities"]:
        if ent["label"] != "skill" or ent["score"] < .68 or len(ent["text"]) > 45:
            continue
        if any(a < ent["end"] and ent["start"] < b for a,b in occupied):
            continue
        value = ent["text"].strip()
        if not value or "\n" in value or len(value)<3 or len(value.split())>4 or not re.fullmatch(r"[\w+.#/ &-]+",value):
            continue
        yield ent["start"],ent["end"],value,"",None


def extraction_graph(documents, records_by_id):
    nodes, edges, noise, docs_out = {},[],[],[]
    for doc in documents:
        rid = doc["resume_id"]
        records = records_by_id[rid]
        pages = {p["page_num"]:p["text"] for p in doc["pages"]}
        name_ent = next((e for r in records[:2] for e in r["entities"]
                         if e["label"]=="person" and e["start"]<110 and len(e["text"].split()) in (2,3,4)), None)
        first_line = doc["pages"][0]["text"].strip().splitlines()[0].strip()
        display = name_ent["text"] if name_ent else rid
        if not name_ent and re.fullmatch(r"[A-Za-zÀ-ž][A-Za-zÀ-ž. '’-]{2,55}",first_line) and 2<=len(first_line.split())<=4 and not re.search(r"(?i)resume|curriculum|vitae|engineer|manager|profile",first_line):
            display = first_line
        props = dict(name=display,resume_id=rid,split=doc["split"],pdf_path=doc["pdf_path"],
                     file_hash=doc.get("file_hash",""),text_hash=doc.get("text_hash",""),
                     certification_quotes=[],certification_pages=[])
        nodes[rid] = dict(id=rid,label="Candidate",properties=props)
        education_seen=set()
        for record in records:
            txt, record_id = record["record_text"],record["record_id"]
            page_num, kind = record["page_num"],record["kind"]
            def link(src,dst,rel,start,end,**more):
                ev = quote_at(txt,start,end)
                if rel=="AT_COMPANY":
                    # A labeled Europass employer field often sits on the line
                    # before the company name; display that evidence together.
                    field=re.search(r"(?im)(?:Name and address of employer|Name of employer|Employer|Company)[ \t]*[:\s]*$",txt[:start])
                    if field and end-field.start()<=240:
                        ev=txt[field.start():end].strip()
                evidence = dict(resume_id=rid,page_num=page_num,record_id=record_id,
                    evidence_quote=ev,evidence_valid=validate_quote(pages[page_num],ev),surface=txt[start:end],**more)
                edges.append(dict(source=src,target=dst,type=rel,properties=evidence))
            def target(label, name, **extra):
                uid=label+":"+re.sub(r"\s+"," ",name).strip().casefold()
                nodes.setdefault(uid,dict(id=uid,label=label,properties=dict(name=name.strip(),**extra)))
                return uid
            facts,main,role = main_facts(record)
            parent = {"WorkRecord":("WorkExperience","HAS_EXPERIENCE"),"EduRecord":("Education","HAS_EDUCATION"),
                      "ProjectRecord":("Project","WORKED_ON")}.get(kind)
            header = next((l.strip(" \t-:•") for l in txt.splitlines() if l.strip(" \t-:•")), "")[:130]
            # Exclude empty heading tails; record types require local evidence.
            if kind=="WorkRecord" and not (role or facts or (main and re.search(r"(?i)name and address of employer|worked (?:for|at) .+? for (?:a period of )?\d+ years?",txt))):
                parent = None
            if kind=="WorkRecord" and PERIOD.fullmatch(txt.strip(" \n:–-")):
                parent=None
            if kind=="EduRecord" and not (main or facts.get("degree") or SCHOOL.search(txt[:200])):
                parent = None
            if kind=="ProjectRecord" and (len(header)<3 or not any(c.isalpha() for c in header)
                    or re.fullmatch(r"(?i)(?:WORKED ON|PROJECTS?|RESUME|CURRICULUM VITAE)[ :]*",header)
                    or (record["page_start"]==0 and not re.match(r"(?i)^project\b",header)
                        and len(txt)<170)):

                parent = None
            if kind=="EduRecord" and main and facts["degree"] and facts["year"]:
                signature=(main["text"].casefold(),facts["degree"].casefold(),facts["major"].casefold(),facts["year"])
                if signature in education_seen:
                    parent=None
                education_seen.add(signature)
            if parent:
                if kind=="EduRecord" and facts.get("degree"):
                    header=" / ".join(dict.fromkeys(v for v in (facts["degree"],facts.get("major",""),main["text"] if main else "") if v))
                if kind=="ProjectRecord" and (proj:=match_entity(record,"project",95)):
                    header=proj["text"]
                meta = dict(name=header or kind, record_id=record_id,resume_id=rid,record_text=txt,page_num=page_num,
                            char_start=record["char_start"],page_start=record["page_start"],**facts)
                nodes[record_id]=dict(id=record_id,label=parent[0],properties=meta)
                evidence_name=facts.get("degree") or header
                at=txt.find(evidence_name)
                link(rid,record_id,parent[1],max(0,at),max(0,at)+min(len(evidence_name),130))
                if main:
                    label, rel = ("Company","AT_COMPANY") if kind=="WorkRecord" else ("University","AT_UNIVERSITY")
                    link(record_id,target(label,main["text"]),rel,main["start"],main["end"])
                if role:
                    link(record_id,target("JobTitle",role["text"]),"HELD_ROLE",role["start"],role["end"])
            if kind == "CERTIFICATIONS":
                for ent in record["entities"]:
                    if ent["label"]=="certification":
                        quote=quote_at(txt,ent["start"],ent["end"])
                        if validate_quote(pages[page_num],quote) and quote not in props["certification_quotes"]:
                            props["certification_quotes"].append(quote)
                            props["certification_pages"].append(page_num)
            if kind not in ("SKILLS","PROFILE","WorkRecord","ProjectRecord") or (kind in ("WorkRecord","ProjectRecord") and not parent):
                continue
            used = set()
            for a,b,value,cat,reason in skill_mentions(record):
                if reason:
                    noise.append(dict(surface=value,reason=reason,resume_id=rid,page_num=page_num,evidence_quote=quote_at(txt,a,b)))
                    continue
                if main and a < main["end"] and main["start"] < b:
                    continue
                key=value.casefold()
                if key in used:
                    continue
                used.add(key)
                skill=target("Skill",value,category=cat)
                source={"WorkRecord":"work_verified","ProjectRecord":"project_verified"}.get(kind,"listed")
                link(rid,skill,"HAS_SKILL",a,b,source=source)
                if source != "listed":
                    rel="USED_SKILL" if kind=="WorkRecord" else "APPLIED_SKILL"
                    link(record_id,skill,rel,a,b)
        docs_out.append(dict(resume_id=rid,split=doc["split"],records=records,pages=doc["pages"]))
    return dict(documents=docs_out,nodes=list(nodes.values()),edges=edges,noise_pruned_mentions=noise)


def extract(documents, cache_dir):
    records_by_id = {d["resume_id"]:records_for(d) for d in documents}
    recognizer = EntityRecognizer(Path(cache_dir)/"ner_windows")
    for i,(rid, records) in enumerate(records_by_id.items(),1):
        recognizer.entities(records)
        print(f"GLiNER {i}/{len(documents)} {rid} ({len(records)} records, {recognizer.device})", flush=True)
    graph = extraction_graph(documents,records_by_id)
    graph["model"] = recognizer.model_name
    return graph
