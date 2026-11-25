"""
实体关系抽取：
优先用大模型抽取；没有 LLM key 时退回规则抽取，保证图谱不为空。
"""
from __future__ import annotations

import re
from typing import Any

import llm

ALLOWED_TYPES = {
    "Country", "Region", "University", "Program", "Degree", "Exam",
    "Fee", "Visa", "Requirement", "Scholarship", "Organization",
}
ALLOWED_RELATIONS = {
    "LOCATED_IN", "OFFERS", "REQUIRES", "CHARGES", "PROVIDES",
    "PART_OF", "APPLIES_TO", "ELIGIBLE_FOR", "RELATED_TO",
}

PROMPT = """你是知识图谱抽取器。请从下面的文档片段中抽取实体和关系。

实体类型（只能使用这些）：
Country, Region, University, Program, Degree, Exam, Fee, Visa, Requirement, Scholarship, Organization

关系类型（只能使用这些）：
LOCATED_IN: 机构/院校位于某地区或国家
OFFERS: 学校或机构提供某项目/学位
REQUIRES: 项目或签证要求某考试/材料/条件
CHARGES: 学校或机构收取某费用
PROVIDES: 政策或机构提供某福利/奖学金
PART_OF: 某实体是另一实体的一部分
APPLIES_TO: 政策/要求适用于某对象
ELIGIBLE_FOR: 某对象有资格获得某项目
RELATED_TO: 其他相关关系

要求：
1. 只抽取文中明确出现的信息，不要编造。
2. 实体名称保持原文，不要翻译或改写。
3. 忽略页码、页眉页脚、纯数字。
4. relations 中的 head / tail 必须是 entities 中出现过的名称。
5. 最多 12 个实体、10 条关系。
6. 只输出 JSON，不要解释。

输出格式：
{"entities":[{"name":"巴登-符腾堡州","type":"Region"}],
 "relations":[{"head":"海德堡大学","relation":"LOCATED_IN","tail":"巴登-符腾堡州"}]}

文档片段：
{text}"""


def _rule_entities(text: str) -> list[dict[str, str]]:
    entities: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(name: str, typ: str) -> None:
        name = name.strip(" ，。、；：:（）()《》")
        if 1 < len(name) <= 30 and name not in seen:
            seen.add(name)
            entities.append({"name": name, "type": typ})

    for country in ["德国", "新加坡", "中国", "英国", "澳大利亚", "美国", "瑞士", "荷兰"]:
        if country in text:
            add(country, "Country")

    for m in re.finditer(r"([\u4e00-\u9fa5·\-]{2,15}(?:州|省))", text):
        add(m.group(1), "Region")

    for m in re.finditer(r"([\u4e00-\u9fa5A-Za-z·\-\s]{2,18}(?:大学|学院|理工大学|工业大学))", text):
        add(m.group(1), "University")

    for exam in ["雅思", "托福", "TestDaF", "DSH", "APS", "德适考试", "GMAT", "GRE", "SAT", "A-Level", "IB"]:
        if exam in text:
            add(exam, "Exam")

    for m in re.finditer(r"([\u4e00-\u9fa5]{2,12}(?:签证|居留许可|冻结账户))", text):
        add(m.group(1), "Visa")

    for m in re.finditer(r"(\d[\d,.]*\s*(?:欧元|元人民币|人民币|新币|新加坡元))", text):
        add(m.group(1), "Fee")

    return entities[:12]


def _rule_relations(text: str, entities: list[dict[str, str]]) -> list[dict[str, str]]:
    relations = []
    unis = [e["name"] for e in entities if e["type"] == "University"]
    regions = [e["name"] for e in entities if e["type"] == "Region"]
    for u in unis:
        for r in regions:
            if u in text and r in text:
                relations.append({"head": u, "relation": "LOCATED_IN", "tail": r})
                break
    return relations[:10]


def extract(text: str, use_llm: bool = True) -> dict[str, list[dict[str, str]]]:
    if use_llm and llm.available():
        data = llm.chat_json([{"role": "user", "content": PROMPT.replace("{text}", text)}])
        raw_entities = data.get("entities") or []
        raw_relations = data.get("relations") or []
        if not isinstance(raw_entities, list):
            raw_entities = []
        if not isinstance(raw_relations, list):
            raw_relations = []
        entities = [
            e for e in raw_entities
            if isinstance(e, dict) and e.get("name") and e.get("type") in ALLOWED_TYPES
        ]
        names = {e["name"] for e in entities}
        relations = [
            r for r in raw_relations
            if isinstance(r, dict)
            and r.get("head") in names
            and r.get("tail") in names
            and r.get("relation") in ALLOWED_RELATIONS
        ]
        if entities:
            return {"entities": entities[:12], "relations": relations[:10]}

    entities = _rule_entities(text)
    return {"entities": entities, "relations": _rule_relations(text, entities)}
