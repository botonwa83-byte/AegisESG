from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from .methodology import Methodology
from .models import Observation


GRAPH_VERSION = "evidence-constraint-graph-v1"


def build_evidence_constraint_graph(
    observations: list[Observation], methodology: Methodology,
) -> tuple[dict, dict]:
    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str, str]] = set()
    constraints = []
    grouped: dict[tuple[str, int, str], list[tuple[str, Observation]]] = defaultdict(list)

    def add_node(kind: str, natural_key: str, **attributes) -> str:
        node_id = _node_id(kind, natural_key)
        candidate = {"id": node_id, "kind": kind, "natural_key": natural_key, **attributes}
        existing = nodes.get(node_id)
        if existing is not None and existing != candidate:
            raise ValueError(f"证据图节点Hash碰撞或属性漂移: {node_id}")
        nodes[node_id] = candidate
        return node_id

    for index, item in enumerate(observations):
        company_id = add_node("company", item.company_code)
        year_id = add_node("report_year", str(item.report_year), year=item.report_year)
        indicator = methodology.by_code[item.indicator_code]
        indicator_id = add_node(
            "indicator", item.indicator_code, name=indicator.name,
            dimension=indicator.dimension, unit=indicator.unit, weight=indicator.weight,
        )
        source_key = item.source_file or item.source_url or "missing-source"
        document_id = add_node("document", source_key)
        page_key = f"{source_key}#page={item.source_page if item.source_page is not None else 'unknown'}"
        page_id = add_node("page", page_key, page=item.source_page)
        candidate_key = "|".join((
            item.company_code, str(item.report_year), item.indicator_code,
            "" if item.value is None else format(item.value, ".12g"), source_key,
            "" if item.source_page is None else str(item.source_page), str(index),
        ))
        candidate_id = add_node(
            "candidate", candidate_key, value=item.value, status=item.status.value,
            confidence=item.confidence, evidence_text=item.evidence_text,
        )
        edges.update({
            (candidate_id, "observed_for", company_id),
            (candidate_id, "measures", indicator_id),
            (candidate_id, "for_period", year_id),
            (candidate_id, "sourced_from", page_id),
            (page_id, "part_of", document_id),
        })
        grouped[(item.company_code, item.report_year, item.indicator_code)].append((candidate_id, item))
        checks = {
            "provenance_complete": bool(item.source_file or item.source_url),
            "page_bound": item.source_page is not None,
            "finite_value": item.value is not None and math.isfinite(float(item.value)),
            "report_year_valid": 2000 <= item.report_year <= 2100,
            "confidence_threshold": 0 <= item.confidence <= 1 and item.confidence >= .8,
            "evidence_present": bool(item.evidence_text.strip()),
        }
        for name, passed in checks.items():
            constraints.append({
                "id": _node_id("constraint", f"{candidate_id}|{name}"),
                "scope": "candidate", "target_id": candidate_id,
                "constraint": name, "passed": passed,
            })

    for key, items in sorted(grouped.items()):
        values = {round(float(item.value), 8) for _, item in items if item.value is not None}
        passed = len(values) <= 1
        group_key = "|".join((key[0], str(key[1]), key[2]))
        group_id = add_node(
            "candidate_group", group_key, company_code=key[0], report_year=key[1],
            indicator_code=key[2], candidate_count=len(items), distinct_value_count=len(values),
        )
        for candidate_id, _ in items:
            edges.add((candidate_id, "member_of", group_id))
        constraints.append({
            "id": _node_id("constraint", f"{group_id}|value_consistency"),
            "scope": "candidate_group", "target_id": group_id,
            "constraint": "value_consistency", "passed": passed,
        })

    ordered_nodes = [nodes[key] for key in sorted(nodes)]
    ordered_edges = [
        {"from": source, "relation": relation, "to": target}
        for source, relation, target in sorted(edges)
    ]
    constraints.sort(key=lambda item: item["id"])
    failures = Counter(item["constraint"] for item in constraints if not item["passed"])
    node_counts = Counter(item["kind"] for item in ordered_nodes)
    graph = {
        "graph_version": GRAPH_VERSION,
        "nodes": ordered_nodes,
        "edges": ordered_edges,
        "constraints": constraints,
    }
    summary = {
        "graph_version": GRAPH_VERSION,
        "observation_count": len(observations),
        "node_count": len(ordered_nodes),
        "edge_count": len(ordered_edges),
        "constraint_count": len(constraints),
        "failed_constraint_count": sum(failures.values()),
        "node_kind_counts": dict(sorted(node_counts.items())),
        "failed_constraint_counts": dict(sorted(failures.items())),
        "conflicting_group_count": failures["value_consistency"],
        "applicable": False,
    }
    return graph, summary


def write_evidence_constraint_graph(
    graph_path: str | Path, summary_path: str | Path, graph: dict, summary: dict,
) -> None:
    output = Path(graph_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(graph, ensure_ascii=False, separators=(",", ":")) + "\n"
    output.write_text(serialized, encoding="utf-8")
    summary["graph_sha256"] = hashlib.sha256(serialized.encode()).hexdigest()
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _node_id(kind: str, natural_key: str) -> str:
    digest = hashlib.sha256(f"{kind}\0{natural_key}".encode()).hexdigest()[:24]
    return f"{kind}:{digest}"
