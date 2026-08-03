from __future__ import annotations

import json
import hashlib
import statistics
import time
import tracemalloc
from collections import defaultdict
from pathlib import Path

from .models import Observation
from .scoring import MissingStrategy, ScoringEngine


def plan_incremental_recompute(
    graph_path: str | Path, changed_ids: list[str] | None = None,
    changed_documents: list[str] | None = None,
) -> dict:
    graph_file = Path(graph_path)
    graph_sha256 = hashlib.sha256(graph_file.read_bytes()).hexdigest()
    with graph_file.open(encoding="utf-8") as stream:
        graph = json.load(stream)
    nodes = {item["id"]: item for item in graph.get("nodes", [])}
    if not nodes:
        raise ValueError("证据图没有节点")
    changed = set(changed_ids or [])
    document_keys = set(changed_documents or [])
    changed.update(
        node_id for node_id, node in nodes.items()
        if node["kind"] == "document" and node["natural_key"] in document_keys
    )
    unknown_documents = document_keys - {
        nodes[node_id]["natural_key"] for node_id in changed if nodes.get(node_id, {}).get("kind") == "document"
    }
    if unknown_documents:
        raise ValueError(f"证据图缺少变更文档: {sorted(unknown_documents)[0]}")
    unknown_ids = changed - set(nodes)
    if unknown_ids:
        raise ValueError(f"证据图缺少变更节点: {sorted(unknown_ids)[0]}")
    if not changed:
        raise ValueError("至少指定一个变更节点或文档")

    outgoing: dict[str, list[tuple[str, str]]] = defaultdict(list)
    incoming: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for edge in graph["edges"]:
        outgoing[edge["from"]].append((edge["relation"], edge["to"]))
        incoming[edge["to"]].append((edge["relation"], edge["from"]))

    seed_candidates = set()
    for node_id in changed:
        kind = nodes[node_id]["kind"]
        if kind == "candidate":
            seed_candidates.add(node_id)
        elif kind == "candidate_group":
            seed_candidates.update(source for relation, source in incoming[node_id] if relation == "member_of")
        elif kind in {"company", "indicator"}:
            relation = "observed_for" if kind == "company" else "measures"
            seed_candidates.update(source for edge_relation, source in incoming[node_id] if edge_relation == relation)
        elif kind == "page":
            seed_candidates.update(source for relation, source in incoming[node_id] if relation == "sourced_from")
        elif kind == "document":
            pages = {source for relation, source in incoming[node_id] if relation == "part_of"}
            for page_id in pages:
                seed_candidates.update(source for relation, source in incoming[page_id] if relation == "sourced_from")

    candidate_relations = {
        candidate_id: {relation: target for relation, target in outgoing[candidate_id]}
        for candidate_id in (node_id for node_id, node in nodes.items() if node["kind"] == "candidate")
    }
    affected_indicators = {candidate_relations[item]["measures"] for item in seed_candidates}
    population_candidates = {
        source for indicator_id in affected_indicators
        for relation, source in incoming[indicator_id] if relation == "measures"
    }
    score_candidates = seed_candidates | population_candidates
    affected_companies = {candidate_relations[item]["observed_for"] for item in score_candidates}
    affected_groups = {candidate_relations[item]["member_of"] for item in seed_candidates}
    all_candidates = {node_id for node_id, node in nodes.items() if node["kind"] == "candidate"}
    all_companies = {node_id for node_id, node in nodes.items() if node["kind"] == "company"}
    changed_document_hashes = {}
    for document in sorted(document_keys):
        document_path = Path(document)
        changed_document_hashes[document] = (
            hashlib.sha256(document_path.read_bytes()).hexdigest()
            if document_path.is_file() else None
        )

    return {
        "plan_version": "evidence-dependency-recompute-v1",
        "graph_path": str(graph_file),
        "graph_sha256": graph_sha256,
        "changed_document_sha256": changed_document_hashes,
        "changed_node_ids": sorted(changed),
        "seed_candidate_ids": sorted(seed_candidates),
        "affected_group_ids": sorted(affected_groups),
        "affected_indicator_ids": sorted(affected_indicators),
        "affected_company_ids": sorted(affected_companies),
        "seed_candidate_count": len(seed_candidates),
        "affected_group_count": len(affected_groups),
        "affected_indicator_count": len(affected_indicators),
        "affected_company_count": len(affected_companies),
        "full_candidate_count": len(all_candidates),
        "planned_candidate_scan_count": len(score_candidates),
        "full_company_count": len(all_companies),
        "candidate_scan_reduction_rate": round(1 - len(score_candidates) / max(len(all_candidates), 1), 6),
        "company_score_reduction_rate": round(1 - len(affected_companies) / max(len(all_companies), 1), 6),
        "ranking_resort_required": bool(affected_companies),
        "applicable": True,
    }


def write_incremental_recompute_plan(path: str | Path, report: dict) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def benchmark_incremental_scoring(
    engine: ScoringEngine, observations: list[Observation], affected_indicators: set[str],
    missing_strategy: MissingStrategy | str = MissingStrategy.INDICATOR_NEUTRAL_V1,
    repetitions: int = 7,
) -> dict:
    if repetitions < 1:
        raise ValueError("重复次数必须至少为1")
    known = {item.indicator_code for item in observations}
    unknown = affected_indicators - known
    if unknown:
        raise ValueError(f"观测中不存在受影响指标: {sorted(unknown)[0]}")
    cache = engine.build_cache(observations, missing_strategy)
    full_times: list[float] = []
    incremental_times: list[float] = []
    full_peaks: list[int] = []
    incremental_peaks: list[int] = []
    full = []
    incremental = []
    for _ in range(repetitions):
        tracemalloc.start()
        started = time.perf_counter()
        full = engine.evaluate(observations, missing_strategy)
        full_times.append(time.perf_counter() - started)
        full_peaks.append(tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()

        tracemalloc.start()
        started = time.perf_counter()
        incremental = engine.evaluate_from_cache(cache, affected_indicators)
        incremental_times.append(time.perf_counter() - started)
        incremental_peaks.append(tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()

    full_payload = [item.to_dict() for item in full]
    incremental_payload = [item.to_dict() for item in incremental]
    full_hash = hashlib.sha256(
        json.dumps(full_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    incremental_hash = hashlib.sha256(
        json.dumps(incremental_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    affected_companies = set().union(
        *(cache.companies_by_indicator.get(code, set()) for code in affected_indicators)
    ) if affected_indicators else set()
    full_median = statistics.median(full_times)
    incremental_median = statistics.median(incremental_times)
    full_peak = int(statistics.median(full_peaks))
    incremental_peak = int(statistics.median(incremental_peaks))
    return {
        "benchmark_version": "incremental-scoring-e3-v1",
        "repetitions": repetitions,
        "observation_count": len(observations),
        "company_count": len(cache.results),
        "affected_indicators": sorted(affected_indicators),
        "affected_company_count": len(affected_companies),
        "full_median_seconds": round(full_median, 9),
        "incremental_median_seconds": round(incremental_median, 9),
        "elapsed_reduction_rate": round(1 - incremental_median / full_median, 6),
        "full_peak_bytes": full_peak,
        "incremental_peak_bytes": incremental_peak,
        "peak_memory_reduction_rate": round(1 - incremental_peak / max(full_peak, 1), 6),
        "full_output_sha256": full_hash,
        "incremental_output_sha256": incremental_hash,
        "field_equivalent": full_payload == incremental_payload,
        "applicable": full_payload == incremental_payload,
    }


def benchmark_cache_change(
    engine: ScoringEngine, observations: list[Observation], change: Observation,
    missing_strategy: MissingStrategy | str = MissingStrategy.INDICATOR_NEUTRAL_V1,
    repetitions: int = 7,
) -> dict:
    identity = (change.company_code, change.report_year, change.indicator_code)
    replaced = False
    updated = []
    for item in observations:
        if (item.company_code, item.report_year, item.indicator_code) == identity:
            updated.append(change)
            replaced = True
        else:
            updated.append(item)
    if not replaced:
        raise ValueError("模拟变更必须替换现有观测")
    full_times: list[float] = []
    incremental_times: list[float] = []
    full_peaks: list[int] = []
    incremental_peaks: list[int] = []
    full = []
    incremental = []
    audit = {}
    for _ in range(repetitions):
        cache = engine.build_cache(observations, missing_strategy)
        tracemalloc.start()
        started = time.perf_counter()
        full = engine.evaluate(updated, missing_strategy)
        full_times.append(time.perf_counter() - started)
        full_peaks.append(tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()

        tracemalloc.start()
        started = time.perf_counter()
        incremental, audit = engine.apply_cache_changes(cache, [change])
        incremental_times.append(time.perf_counter() - started)
        incremental_peaks.append(tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()
    full_payload = [item.to_dict() for item in full]
    incremental_payload = [item.to_dict() for item in incremental]
    payload = lambda value: hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    full_median = statistics.median(full_times)
    incremental_median = statistics.median(incremental_times)
    full_peak = int(statistics.median(full_peaks))
    incremental_peak = int(statistics.median(incremental_peaks))
    return {
        "benchmark_version": "dynamic-cache-change-e3-v1",
        "simulation_only": True,
        "repetitions": repetitions,
        "change": {
            "company_code": change.company_code,
            "report_year": change.report_year,
            "indicator_code": change.indicator_code,
            "new_value": change.value,
        },
        **audit,
        "full_median_seconds": round(full_median, 9),
        "incremental_median_seconds": round(incremental_median, 9),
        "elapsed_reduction_rate": round(1 - incremental_median / full_median, 6),
        "full_peak_bytes": full_peak,
        "incremental_peak_bytes": incremental_peak,
        "peak_memory_reduction_rate": round(1 - incremental_peak / max(full_peak, 1), 6),
        "full_output_sha256": payload(full_payload),
        "incremental_output_sha256": payload(incremental_payload),
        "field_equivalent": full_payload == incremental_payload,
        "applicable": full_payload == incremental_payload,
    }
