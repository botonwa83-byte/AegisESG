"""生成可运行的演示输入；数据是合成数据，不代表任何真实公司。"""
from __future__ import annotations

import csv
import random
from pathlib import Path

from aegis_esg.io import OBSERVATION_COLUMNS
from aegis_esg.methodology import load_methodology
from aegis_esg.models import Direction, IndicatorKind


def main() -> None:
    random.seed(2025)
    root = Path(__file__).resolve().parents[1]
    methodology = load_methodology(root / "data/methodologies/energy_esg_2025.json")
    output = root / "data/samples/demo_observations.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=OBSERVATION_COLUMNS)
        writer.writeheader()
        for company_index in range(1, 13):
            for indicator_index, indicator in enumerate(methodology.indicators):
                if indicator.kind == IndicatorKind.QUALITATIVE:
                    value = (20, 50, 80, 100)[(company_index + indicator_index) % 4]
                else:
                    base = 20 + indicator_index * 3
                    value = base + random.gauss(0, max(1, base * .15)) + company_index
                    if indicator.direction == Direction.NEGATIVE:
                        value += company_index * 1.5
                writer.writerow({
                    "company_code": f"DEMO{company_index:03d}",
                    "company_name": f"演示能源{company_index:02d}",
                    "report_year": 2024,
                    "indicator_code": indicator.code,
                    "value": round(max(0, value), 6),
                    "status": "confirmed",
                    "source_url": "https://example.invalid/demo",
                    "source_file": "synthetic-demo",
                    "source_page": "",
                    "evidence_text": "仅用于验证端到端流程的合成数据",
                    "confidence": 1,
                })
    print(output)


if __name__ == "__main__":
    main()

