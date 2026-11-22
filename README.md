# 英文简历知识图谱 · 作业 2

丁宇轩（524031910745）独立完成，贡献比例 100%。本项目把原始英文简历逐页转为带引文的 Neo4j 知识图谱，用训练集标定四维规则，再在独立测试集进行中文岗位查询。

[技术说明与实测数据](docs/技术说明文档.md) · [逐项验收 JSON](data/processed/acceptance_report.json) · [12 份试点](data/processed/pilot_audit.md) · [三人对比](data/processed/query_reports/comparison.md) · [五阶段演示视频](demo_video/五阶段演示.mp4)

## 用提交包复核

解压后进入包含本文件的目录。下列命令适用于 macOS/Linux，使用 uv 和 Docker Compose。仓库锁定 Python 3.11，依赖清单来自本次 macOS arm64 环境。默认 HTTP 和 Bolt 端口为 7474 和 7687，仅绑定本机。

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -r requirements.txt
cp -n .env.example .env
docker compose up -d
```

等待 [Neo4j Browser](http://localhost:7474) 可访问。默认用户和本机演示密码见 .env.example。全新的数据库需先载入随包提供的规范图谱并回写评分。以下第一行使用当前图谱 JSON 原样入库，后两行使用实时数据库重算规则与报告。

```bash
.venv/bin/python -c 'from src.stage3_neo4j import load_graph; print(load_graph())'
.venv/bin/python -m src.cli stage4
.venv/bin/python -m src.cli stage5
.venv/bin/python scripts/verify_acceptance.py --publish
.venv/bin/python scripts/verify_acceptance.py
```

本机已入库时，可直接运行最后一条命令。验收覆盖 AC-1 至 AC-8，任一项失败即输出非零退出码，逐项原因写入 acceptance_report.json。无参数模式将现有文档、源文件和提交包与实时结果比较。--publish 会先通过 AC-1 至 AC-7，再按实测结果生成技术说明、打包并复核包内文件。初次解压缺少 dist 目录时，自检脚本可直接生成默认包。

## 从原始数据重新运行

数据源为 Mehyaar/Annotated_NER_PDF_Resumes 的 ResumesPDF.zip，初次运行下载到 data/raw/。默认模型是 urchade/gliner_medium-v2.1，可回退到 small-v2.1。代码探测 MPS，无法使用时回退 CPU。首次无缓存运行需要联网访问 Hugging Face；可在 .env 中配置 HF_ENDPOINT。随包的 data/processed/ner_windows 包含已推理的记录窗口。

```bash
.venv/bin/python -m src.cli pilot --size 12
```

打开试点核对表，对照原始 PDF 核查标题、记录边界、公司与工期、技能归属和消岐两侧语境。提交包内留有这次的逐份复核记录。如果原样重跑后试点报告未变，既有复核记录仍有效。如果更换数据或修改切分，核对新结果后填写实际结论。

```bash
.venv/bin/python -m src.cli pilot-review --note '填写本次实际核对结果'
.venv/bin/python -m src.cli run-all
.venv/bin/python scripts/verify_acceptance.py --publish
```

可以分别运行 stage1 到 stage5。stage3 从结构化抽取重新做消岐、共指与入库。stage4 可接受 --focus-ids 后跟三个简历 ID。stats 查询实时子图规模，sync-check 单独复跑固定训练子集实验。

## 交互演示

```bash
.venv/bin/streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

打开[五阶段演示](http://localhost:8501)。侧栏选择的简历联动「采 · 数据采集」和「治 · 记录抽取」。在原文阅读区切换 PDF 页码，在抽取页选择记录并核对同条记录的实体与引文。窄屏可用左上角按钮打开侧栏。

在「存 · 图谱探索」搜索节点，或用节点选择框查看关联关系和原文。切换到「算 · 规则画像」可比较训练快照与候选人评级。在「用 · 岗位检索」切换主查询、零命中示例或自定义需求，查看严格命中、近似候选缺项及三人对比。展开查询详情可复制 Cypher 到 Neo4j Browser 独立复核。

```cypher
MATCH p=(c:Candidate:ResumeKG {split:'train'})-[:HAS_EXPERIENCE]->(w:WorkExperience)-[:USED_SKILL]->(s:Skill)
RETURN p LIMIT 30
```

## 目录与打包

- src/ 实现「采、治、存、算、用」及 CLI，app.py 为五标签页入口。
- data/sample_pdfs/、data/extracted_txt/ 保存 60/20 固定 PDF、文本与页边界。先在整个归档做双哈希去重，再在符合采样条件的简历中按连续五词集合相似度排除近重复版本。
- data/processed/ 保存模型窗口缓存、原始/规范图谱、试点核对记录、16 条规则、同步实验、重点画像及查询结果。
- docs/技术说明文档.md 由实际运行数据生成。scripts/verify_acceptance.py 自检，scripts/technical_report.py 渲染说明书。
- demo_video/五阶段演示.mp4 为这次真实 Streamlit 操作录屏。更新视频后再次打包即可。

```bash
bash scripts/package_submission.sh
bash scripts/package_submission.sh 自定义包名
```

默认包为 dist/ISM2026HW2-524031910745丁宇轩.zip，内含源文件、固定快照和全部报告。原始数据归档、模型权重、数据库卷、虚拟环境和本地 .env 排除在外。
