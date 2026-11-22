"""Render the submission narrative from verified data. Also used to detect stale docs."""
from src.config import PROCESSED, read_json


def cell(value):
    return " ".join(str(value).split()).replace("|", "&#124;")


def table(headers, rows):
    return ["| "+" | ".join(headers)+" |", "|"+"---|"*len(headers),
            *["| "+" | ".join(cell(v) for v in row)+" |" for row in rows], ""]


def render(report, *, brief=False):
    m = [None] + [report["checks"][f"AC-{i}"]["metrics"] for i in range(1,8)]
    kg = read_json(PROCESSED/"resolved_kg.json")
    model = read_json(PROCESSED/"rules_model.json")
    sync = read_json(PROCESSED/"sync_check_report.json")
    review = read_json(PROCESSED/"pilot_review.json")
    coref = kg["coref_audit"]
    train = m[4]["train"]
    main = read_json(PROCESSED/"query_reports/main.json")
    zero = read_json(PROCESSED/"query_reports/zero.json")
    title = "简历知识图谱与岗位匹配"
    byline = ["智能信息系统建模　作业 2", "", "丁宇轩 · 524031910745 · 独立完成全流程设计、开发、测试、录屏及文档撰写 · 贡献比例 100%。", ""]
    lines = ["# " + title + "项目说明", "", *byline,
             "## 项目概述", "",
             "招聘人员拿到一份简历时，常常需要确认两件事：候选人是否提过某项技能，又是否在具体工作中用过它。"
             "本项目把技能、岗位、企业和经历连到简历原句。阅读者可以从岗位筛选结果回到候选人的项目，再打开 PDF 核对页码。", "",
             f"在 {m[2]['train']} 份训练简历上构建了 {train['node_count']} 个可达领域节点和 "
             f"{train['relationship_count']} 条有来源的关系。{m[2]['test']} 份独立测试简历仅参与应用评估。"
             f"主岗位需求严格命中 {m[7]['main']['strict']} 人，极高门槛对照命中 {m[7]['zero']['strict']} 人。", "",
             "## 用户需求与实现", ""]
    lines += table(["需求", "实现结果"], [
        ("查看技能的使用场景", "每条工作或项目技能关系都带原句；在单份简历关系图中可隐藏仅列在清单里的技能。"),
        ("区分同名实体并归并别名", "用记录上下文区分 IBM 公司和 IBM MQ Series；把 ML 与 Machine Learning 归入同一技能。"),
        ("解释画像分数", "四个能力维度各有四条规则。工作台给出命中项、训练阈值与来源记录。"),
        ("按岗位条件比较简历", "从独立测试集筛选，再比较前三人的四维画像、项目和实证技能；缺少硬条件的人单列。"),
    ])
    lines += ["## 业务操作流程", "",
              "从「概览」的五步流程进入「采 · 原文」，选择一份简历，按页阅读或下载原始 PDF。进入「治 · 抽取」会沿用这份简历。"
              "选中一段经历，可核对关系图、高亮词和对应的原句。", "",
              "在「存 · 图谱」中选择简历范围，搜索 IBM 或点选节点查看相邻关系和原句。「消歧」对照 IBM 的公司与技术产品含义，「归并」解释别名，"
              "「分布与审计」列出节点、关系和保留为不同实体的相似名称。", "",
              "到「算 · 评分」选择维度，展开规则核对门槛与原文。「训练快照对比」展示样本增加后阈值如何变化，「重点简历画像」可下载个人报告。"
              "在「用 · 检索」输入需求，或点击示例填入后提交。阅读匹配概况、对比前三人，再从候选人详情跳回原文页核查。", "",
              "## 五阶段技术建模", ""]
    lines += table(["阶段", "主要技术", "形成的数据"], [
        ("采 · 原文", "PyMuPDF 逐页取文，文件与文本哈希去重，连续五词相似度复核", "保留页码的原文、固定训练集与测试集"),
        ("治 · 抽取", "按记录切分上下文，用 GLiNER 标注实体，再按证据生成关系", "工作、项目、教育记录及带引文的关系"),
        ("存 · 图谱", "上下文消歧、同类型别名归并、Neo4j 持久化", "规范实体、双边消歧与防误并记录"),
        ("算 · 评分", "从训练样本标定特征阈值，逐人计算命中项", "四维分数、训练快照和三份重点画像"),
        ("用 · 检索", "将中文条件转为 Cypher，测试集按硬条件过滤、按偏好排序", "严格命中、近似候选、前三人比较和原件入口"),
    ])
    if brief:
        lines += ["![环形布局下的训练子图与实体导览](同心轨道.png)", "",
                  "## 实体消歧与共指消解", "",
                  "简历里的 IBM 有时是雇主，有时出现在技术产品名称中。系统用局部词窗相似度（50%）、段落位置（30%）和同条记录里的实体（20%）给两种含义评分。只有两种含义都有训练原句和独立关系，才算验证了一组。", ""]
        ibm = next(g for g in kg["disambiguation_groups"] if g["surface"] == "IBM")
        lines += table(["来源页", "IBM 的原文", "图谱关系"], [
            (f"{e['resume_id']} · p.{e['page_num']}", e['evidence_quote'], e['edge_type'])
            for e in ibm["senses"]])
        lines += [f"训练集验证了 {m[5]['verified_groups']} 组同名消歧，涉及 " + "、".join(m[5]["surfaces"]) +
                  f"。共指消解则查找不同写法所指的同一实体。ML 与 Machine Learning 合为一项技能，C、C++ 和 C# 各自保留。"
                  f"训练集确认 {m[5]['alias_groups']} 组跨文档别名。全量记录还识别出 {m[5]['reference_chains']} 处文内指代，第一人称指向候选人，机构或项目泛指需匹配本条记录中的先行实体。", "",
                  "## 规则生成与重点画像", "",
                  "对教育背景、工作经历、技能水平和发展潜力分别取四个可核查的特征。训练集的经验分位数决定命中门槛。例如技能水平考查实证技能数、实证占比、技能总数和覆盖类别。每项达标得 25 分，每维最高 100 分。", "",
                  f"将训练样本从 {m[6]['snapshot_sizes'][0]} 份扩大到 {m[6]['snapshot_sizes'][1]} 份后，{m[6]['threshold_changes']} 条规则的阈值改变。固定的三位测试对象中，有 {m[6]['changed_anchors']} 人的得分或等级随之变化。", ""]
        dims = ("EDU", "EXP", "SKL", "POT")
        profiles = [read_json(PROCESSED/f"focus_profiles/{rid}.json") for rid in m[6]["focus_profiles"]]
        lines += table(["重点简历", "教育", "经历", "技能", "潜力"], [
            (r["resume_id"], *[f"{r['scores'][d]} / {r['grades'][d]}" for d in dims]) for r in profiles])
        lines += ["## 岗位检索与三人比较", "", "主岗位需求为「" + main["query"] + "」", "",
                  f"测试集中有 {m[7]['main']['strict']} 人满足全部硬条件，另有 {m[7]['main']['near']} 人列入近似候选。偏好条件用于排序。", ""]
        lines += table(["严格命中前三人", "净工龄（月）", "项目数", "实证技能占比"], [
            (r["resume_id"], r["merged_exp_months"], r["project_count"], f"{r['verified_skill_ratio']:.1%}")
            for r in main["strict_matches"][:3]])
        lines += ["![严格命中前三人的四维比较](../data/processed/query_reports/comparison.png)", "",
                  "前两人的简历均包含 SQL 和项目记录；第三人的净工龄较长，抽取到的技能均有实证，但没有独立项目记录。"
                  "面试时可以从项目职责、用到的技术和任职日期三个角度分别追问。", "",
                  "对照需求为「" + zero["query"] + "」"
                  f"严格命中 {m[7]['zero']['strict']} 人，近似候选 {m[7]['zero']['near']} 人。近似列表逐人说明缺少的硬条件。", "",
                  "## 运行结果与材料", "",
                  "文中的得分描述简历所提供的证据，并受训练样本构成和日期可解析程度影响。持续至今的经历按快照月折算，较早撰写的简历可能高估工龄。", "",
                  "[旧版五阶段操作录像](../demo_video/五阶段演示.mp4) · [完整规则、引文与 Cypher](技术说明文档.md) · [运行方法](../README.md) · [逐项验收](../data/processed/acceptance_report.json)", ""]
        return "\n".join(lines)
    lines = ["# " + title + "技术说明", "", *byline,
             "本文件汇总完整的样本统计、双边引文、规则阈值与查询。业务操作流程见[项目说明](项目说明.md)。", ""]
    lines += ["## 系统架构与复现", "",
             "```mermaid","flowchart LR","    A[原始 PDF] --> B[逐页抽取和两级去重]",
             "    B --> C[12 份试点与原文复核]","    C --> D[固定 60 / 20 快照]",
             "    D --> E[记录切分与 GLiNER 实体识别]","    E --> F[实体消歧与共指消解]",
             "    F --> G[(Neo4j)]","    G --> H[训练集规则标定]","    H --> I[四维画像]",
             "    G --> J[测试集岗位查询]","    J --> K[严格与近似分区 / 三人对比]","```","",
             f"本次使用 uv 与 Python {m[1]['python']}，数据库为 {m[1]['database']} Community，"
             f"实体识别模型为 `{m[1]['model']}`。GLiNER 在每条带页码的记录中标注人、机构、学位、岗位及技能等实体跨度。"
             "技能词典补全易漏的短词和带符号语言。窗口输出落盘，改图谱算法时可复用。","",
             "从项目根目录执行 `.venv/bin/python scripts/verify_acceptance.py` 可独立核对原始 PDF、实时图库、规则与打包件。"
             "各阶段的重建命令见 [README](../README.md)。","",
             "## 数据治理与试点","",
             "输入来自公开数据集 [Mehyaar/Annotated_NER_PDF_Resumes](https://huggingface.co/datasets/Mehyaar/Annotated_NER_PDF_Resumes)。"
             "对归档 PDF 计算 SHA-256，逐页抽取后对 NFKC、空白及大小写规范化文本再计算 SHA-256。"
             "文本优先使用 PyMuPDF，提取出错或未返回文字时尝试 pdfplumber。",""]
    labels={"pdf_files":"归档 PDF","duplicate_file":"重复文件","duplicate_text":"异文件同文本","low_quality":"空文本或质量过滤",
            "unreadable":"无法提取","missing_sections":"教育、任职或技能标题不完整","outside_role_scope":"岗位词或页数筛选"}
    lines+=table(["语料处理","份数"],[(v,m[2]["corpus"].get(k,0)) for k,v in labels.items()]+[("符合选样条件",m[2]["eligible"])])
    lines += [f"在 {m[2]['eligible']} 份符合范围的简历中另行比较连续五词集合，Jaccard 相似度为交集大小除以并集大小。达到 "
              f"{m[2]['near_duplicate_threshold']:.2f} 的版本视为同组，保留英文词数较多的一份，同长按文本哈希确定。"
              f"按此规则另剔除 {m[2]['near_duplicate_excluded']} 个改写版本。最初的双哈希快照曾含相近的 .NET 岗位简历，"
              "本次在分配 train/test 前过滤该组，再按既定种子从同层候补中补入。原 20 份测试简历、预设岗位需求和 12 份试点成员均保持固定。"
              f"复查全部 60 × 20 个跨集组合，最高五词 Jaccard 为 {m[2]['maximum_cross_split_jaccard']:.4f}。","",
              f"两级共排除 {m[2]['dedup_removed_count']} 份重复。哈希互斥检验覆盖相同字节或相同规范化全文；同一人可能有内容不同的简历版本。软件与数据岗位样本需包含三类标题和至少三种领域词，"
              "取四页以内的简历。按文本哈希排序，以 seed=42 洗牌，兼顾有无独立项目标题的版式。测试集先固定，"
              "训练集预留品牌歧义上下文的分层入口。样本代表这一岗位与版式范围。","",
              f"最终保留 {m[2]['pages']} 页。文件哈希跨集交集为 {m[2]['file_hash_overlap']}，文本哈希跨集交集为 "
              f"{m[2]['text_hash_overlap']}。快照签名为 `{m[2]['cohort_hash']}`。","",
              f"试点覆盖 {m[1]['pilot_count']} 份训练简历和 {m[1]['pilot_layout_signatures']} 种版式特征组合，"
              f"产生 {m[1]['pilot_records']} 条记录、{m[1]['pilot_edges']} 条关系。{review['note']}",
              "", "[试点逐记录核对表](../data/processed/pilot_audit.md) · [逐份抽查记录](../data/processed/pilot_review_notes.md)","",
              "## 原文证据与图谱规模","",
              "项目、任职、学历三种记录分别保留页内和全文字符偏移。项目中的技术通过 APPLIED_SKILL 连边，任职中的技术使用 USED_SKILL。"
              "候选人 HAS_SKILL 的 source 区分 listed、work_verified 与 project_verified。仅技能表中的词只进入列举技能。"
              "每条关键关系保留简历编号、页码和最长 240 字符的引文，验收时重新读取 PDF 并检查原文及所属记录。","",
              f"全量抽取 {m[3]['records']} 条记录与 {m[3]['gliner_mentions']} 个模型实体提及。实时图库的 "
              f"{m[3]['key_edges']} 条关键关系中，{m[3]['valid_quotes']} 条通过逐页引文校验（{m[3]['quote_valid_rate']:.2%}）。"
              "该比例衡量引文能否在对应页面找到。抽取语义准确性另见逐份试点记录。",""]
    lines += table(["口径","可达节点","可达关系"],[(scope,m[4][scope]["node_count"],m[4][scope]["relationship_count"]) for scope in ("train","test","all")])
    for title,key in [("节点类型","nodes"),("关系类型","relationships")]:
        lines+=table([title,"train","test","all"],[(kind,*[m[4][s][key].get(kind,0) for s in ("train","test","all")])
                 for kind in sorted(m[4]["all"][key])])
    lines+=["统计从对应 split 的 Candidate 出发，沿领域有向边向外最多两跳，以 DISTINCT 分别计数。跨集可共享技能、学校、公司等实体，全图计其并集。","",
            "![各口径节点分布](../data/processed/entity_distribution.png)","",
            "![Neo4j Browser 中候选人、三个项目与实证技能的网络图](Neo4j项目技能子图.png)","",
            "图例取自主查询候选人 cv-486c4ba1bcae。WORKED_ON 连到三个独立项目，APPLIED_SKILL 连到各项目原文中出现的技能。下面的只读查询可复现截图。","",
            "```cypher","MATCH p=(c:Candidate {resume_id:'cv-486c4ba1bcae'})-[:WORKED_ON]->(j:Project)",
            "OPTIONAL MATCH q=(j)-[:APPLIED_SKILL]->(:Skill)","RETURN p, q","```","",
            "## 实体消歧、别名归并与文内指代","",
            "消歧使用局部词窗、段落位置及同记录实体共现三类信号。词窗与义项上下文原型通过词频–逆文档频率向量的余弦相似度比较。"
            "综合分为 0.50 × 词窗相似度 + 0.30 × 段落先验 + 0.20 × 同记录一致性。只有训练原文支持两个真实目标且两条边都存在时，才计为一组。",""]
    for group in kg["disambiguation_groups"]:
        lines+=["### "+group["surface"],""]
        lines+=table(["原文位置","引文","真实连边与目标","各义项综合分"],[
            (f"{s['resume_id']} · p.{s['page_num']}",s["evidence_quote"],f"{s['edge_type']} → {s['label']} · {s['name']}",
             " / ".join(f"{k} {v['total']:.3f}" for k,v in s["scores"].items())) for s in group["senses"]])
    lines += [f"验证双边组 {m[5]['verified_groups']}，另记录 {m[5]['noise_pruned']} 条被上下文判为普通词或其他噪声的提及。","",
              f"受保护的符号参与规范化。实体先做同类型规范名与缩写归并，机构相似写法再结合字符 n-gram 和邻域验证。"
              f"合并前 {m[5]['nodes_before']} 个节点，合并后 {m[5]['nodes_after']} 个，压缩率 {m[5]['compression_ratio']:.2%}。"
              f"训练集中检出跨文档别名组 {m[5]['alias_groups']} 组；全量记录内识别 {m[5]['reference_chains']} 处指代。"
              "同文档的第一人称指向候选人，机构或项目泛指结合本条记录中的先行实体判定。",""]
    lines += table(["规范实体","异名证据 A","异名证据 B"],[(g["canonical_name"],*[f"{e['alias']} · {e['resume_id']} p.{e['page_num']}" for e in g["examples"][:2]]) for g in coref["cross_document_groups"]])
    for c in coref["within_document_chains"][:3]:
        lines.append(f"- {c['resume_id']} p.{c['page_num']}　{cell(c['evidence_quote'])}　“{c['surface']}” 指向 {cell(c['canonical_name'])}。")
    lines+=["",f"以下 {m[5]['negative_controls']} 对技术名称在 Neo4j 中各保留两个目标节点。",""]
    lines+=table(["反例对","字符相似度","保护依据"],[(" / ".join(x["names"]),f"{x['similarity']:.3f}",x["reason"]) for x in coref["negative_controls"]])
    lines+=["## 规则生成、同步实验与重点画像","",
            "特征来自带来源的教育、任职、项目与技能关系。最高学历排除简历中明确标为在读或预计授予的学位，仍保留该教育记录及状态引文。工龄按可解析的月份闭区间取并集；同时期兼职只计一次。"
            "实证占比用工作或项目中出现的去重技能数除以全部去重技能数，分母至少为一。职级成长按时间比较早期与后续职级。"
            "每个原子特征对应一条可执行规则。经验分位数取训练观测值，若分位为零则转用正值子集。每条命中计 25 分，"
            "每维满分 100；零分定为 D，正分按训练分数的四分位边界确定 A/B/C/D。",""]
    lines+=table(["规则","特征与业务含义","实际标定","Cypher 条件","训练覆盖"],[(r["rule_id"],f"{r['feature']} · {r['business_meaning']}",r["threshold_formula"],r["cypher_predicate"],f"{r['train_hit_count']} / {model['train_size']} ({r['train_hit_rate']:.1%})") for r in model["rules"]])
    lines+=[sync["design"],"",f"A 的快照签名为 `{sync['snapshot_a']['cohort_hash']}`，B 为 `{sync['snapshot_b']['cohort_hash']}`。"
            f"两个训练快照各有 {m[6]['snapshot_sizes'][0]} 和 {m[6]['snapshot_sizes'][1]} 人。{m[6]['threshold_changes']} 条规则阈值变化，"
            f"{m[6]['changed_anchors']} 位锚点发生得分或等级变化。",""]
    lines+=table(["变化规则","快照 A","快照 B"],[(x["rule_id"],x["threshold_a"],x["threshold_b"]) for x in sync["threshold_changes"]])
    dims=("EDU","EXP","SKL","POT")
    lines+=table(["固定测试锚点","A 教育/经历/技能/潜力","B 教育/经历/技能/潜力","变化命中项"],[(a["resume_id"],*[" / ".join(f"{a[k]['scores'][d]}{a[k]['grades'][d]}" for d in dims) for k in ("a","b")],", ".join(a["changed_hit_rules"]) or "无") for a in sync["anchors"]])
    lines+=["### 三份重点简历",""]
    for rid in m[6]["focus_profiles"]:
        p=read_json(PROCESSED/f"focus_profiles/{rid}.json")
        lines += [f"**{rid}**　"+" ".join(p["analysis"]),"", f"[逐维规则与逐条原句](../data/processed/focus_profiles/{rid}.md)","",
                  f"![{rid} 四维雷达图](../data/processed/focus_profiles/{rid}.png)",""]
    lines+=["## 测试集检索与三人比较","",
            f"主需求（{len(main['query'])} 字）为「{main['query']}」。严格命中 {len(main['strict_matches'])} 人，"
            f"近似候选 {len(main['near_misses'])} 人。零命中对照需求（{len(zero['query'])} 字）为「{zero['query']}」，"
            f"严格命中 {len(zero['strict_matches'])} 人，近似候选 {len(zero['near_misses'])} 人。","",
            "自定义输入示例为「招聘高级软件开发工程师，本科及以上，掌握 Python 和 SQL，2年以上工作经验，有项目经验优先。」岗位名称用于说明，后续分句明确学历、技能、年限与偏好。","",
            "每个必选技能组内部取或，组间取且。学历和净任职月数为硬门槛。偏好技能、项目或实证占比只影响排序。以下为主查询可在 Neo4j Browser 中执行的 Cypher。","",
            "```cypher",main["browser_cypher"],"```",""]
    lines+=table(["主查询 Top-3","教育","经历","技能","潜力","项目","实证技能占比"],[(c["resume_id"],*[f"{c['scores'][d]} / {c['grades'][d]}" for d in dims],c["project_count"],f"{c['verified_skill_ratio']:.1%}") for c in main["strict_matches"][:3]])
    lines+=["![严格命中前三人的四维比较](../data/processed/query_reports/comparison.png)","",
            "[三人比较、原始 PDF 与面试核实建议](../data/processed/query_reports/comparison.md)","",
            "零命中查询中最接近的三人仍缺少下列硬条件。",""]
    lines+=table(["近似候选","缺失项"],[(c["resume_id"],"；".join(c["missing_conditions"])) for c in zero["near_misses"][:3]])
    lines+=["## 复核边界","",
            "简历给出的技能和业绩来自候选人自述。引文核验检验可追溯性，业务语义仍需逐记录抽查。"
            "无可靠日期的经历不计入净工龄，只有年份的日期用年初或年末作边界，持续至今的日期按作业快照月 2026-11 折算，古老简历可能因此高估工龄。PDF 多栏版式、匿名占位和历史简历会影响项目边界与工龄解释。"
            "这组分位阈值描述固定训练队列，未使用录用结果标签，也未测量实际岗位表现。","",
            "[机器可读验收结果](../data/processed/acceptance_report.json) · [规则元数据与原文样例](../data/processed/rules_model.json) · [同步实验快照](../data/processed/sync_check_report.json)",""]
    if (PROCESSED.parents[1]/"demo_video/五阶段演示.mp4").is_file():
        lines += ["[旧版五阶段界面实录（MP4）](../demo_video/五阶段演示.mp4)",""]
    return "\n".join(lines)
