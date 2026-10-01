"""Generate the weekly dashboard from the cumulative four-source archive."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.fapesp_agent import build_dashboard, export_results, normalize_records, weekly_rows


def generate(archive: Path, report_file: Path, output: Path) -> dict:
    rows = weekly_rows(archive.read_bytes())
    data, quality = normalize_records(rows)
    if data.empty:
        raise ValueError("O histórico semanal está vazio; o painel anterior não será substituído")
    report = json.loads(report_file.read_text(encoding="utf-8"))
    diagnostics = []
    for source in report.get("sources", []):
        diagnostics.append({"notebook": "workflow semanal: " + source["source_id"],
                            "source_id": source["source_id"], "status": source.get("status", "unknown"),
                            "records": source.get("seen", 0), "pages_ok": 0,
                            "pages_requested": 0,
                            "errors": [{"error": source["error"]}] if source.get("error") else []})
    dashboard = build_dashboard(data, diagnostics, days=365)
    paths = export_results(data, diagnostics, dashboard, output, quality, embed_plotly_js=False)
    return {"records": len(data), "figures": len(dashboard["figures"]),
            "sources": len(diagnostics), "paths": paths}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "data/news.csv")
    parser.add_argument("--report", type=Path, default=ROOT / "data/runs/latest.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/analysis")
    args = parser.parse_args()
    result = generate(args.archive, args.report, args.output)
    print(f"Painel semanal: {result['records']} URLs, {result['figures']} gráficos, {result['sources']} fontes")


if __name__ == "__main__":
    main()
