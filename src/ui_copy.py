"""五个阶段在导航、页头和流程入口共用同一套名称。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    path: str
    name: str
    mark: str
    icon: str
    description: str
    title: str
    subtitle: str


STAGES = (
    Stage("source", "原文", "采", "description", "逐页阅读简历", "从样本读起", "查看样本如何筛选，翻阅原始简历并核对页码。"),
    Stage("extract", "抽取", "治", "format_ink_highlighter", "核对经历与原句", "每条关系，回到原句", "选中一段简历，查看对应的实体、关系和原文。"),
    Stage("graph", "图谱", "存", "hub", "探索实体关系", "探索简历之间的联系", "沿着工作经历和项目寻找共同技能，查看同名词和别名如何处理。"),
    Stage("rules", "评分", "算", "tune", "理解评分依据", "一份评分，从何而来", "查看训练样本如何确定评分规则，再从候选人的得分追溯到原文。"),
    Stage("search", "检索", "用", "search", "按岗位找人", "用一句中文描述岗位", "写下必备条件和优先考虑的经历，在测试候选人中寻找匹配。"),
)
