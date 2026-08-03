from __future__ import annotations

import csv
from pathlib import Path

from .models import Observation, ValueStatus
from .qualitative_review import read_qualitative_review_packets


RESEARCH_QUALITATIVE_MARKER = "[research-only:auto-qualitative-v1;not-formal]"


def build_research_qualitative_observations(
    packet_path: str | Path, gap_path: str | Path,
) -> tuple[list[Observation], dict]:
    packets = read_qualitative_review_packets(packet_path)
    observations = [
        Observation(
            item.company_code, item.company_name, item.report_year, item.indicator_code,
            float(item.suggested_score), ValueStatus.CONFIRMED,
            item.representative_source_url, item.representative_source_file,
            item.representative_page, f"{item.representative_evidence} {RESEARCH_QUALITATIVE_MARKER}",
            min(item.max_confidence, .79),
        )
        for item in packets
    ]
    with Path(gap_path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"company_code", "company_name", "report_year", "indicator_code"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("定性证据缺口文件字段不完整")
        for row in reader:
            observations.append(Observation(
                row["company_code"].strip().upper(), row["company_name"].strip(),
                int(row["report_year"]), row["indicator_code"].strip(), 0.0,
                ValueStatus.CONFIRMED, evidence_text=(
                    f"No qualifying public evidence in current collection {RESEARCH_QUALITATIVE_MARKER}"
                ), confidence=0.0,
            ))
    identities = {(item.company_code, item.report_year, item.indicator_code) for item in observations}
    if len(identities) != len(observations):
        raise ValueError("研究定性观测存在重复公司指标")
    return observations, {
        "algorithm_version": "auto-qualitative-v1",
        "observation_count": len(observations),
        "evidence_estimate_count": len(packets),
        "zero_evidence_gap_count": len(observations) - len(packets),
        "company_count": len({item.company_code for item in observations}),
        "research_only": True,
        "formal_scoring_authorized": False,
    }
