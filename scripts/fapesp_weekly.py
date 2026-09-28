"""Collect recent public news and check the existing FAPESP notebooks.

The CSV is cumulative. A failed source never deletes previously collected rows.
This script does not execute Colab notebooks or claim that they run end to end.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from IPython.core.interactiveshell import InteractiveShell
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("source_id", "title", "published_date", "published_raw", "url", "first_seen", "last_seen")
SOURCES = ("nic", "edpb", "mercociudades", "senado_federal")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FAPESP research news monitor; +https://github.com/anamacao/FAPESP-PIBIC-scrapping)"}
MONTHS = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
    "enero": 1, "febrero": 2, "marzo": 3, "mayo": 5, "junio": 6,
    "julio": 7, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def session() -> requests.Session:
    client = requests.Session()
    client.headers.update(HEADERS)
    retry = Retry(total=2, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504))
    client.mount("https://", HTTPAdapter(max_retries=retry))
    return client


def fetch(client: requests.Session, url: str) -> requests.Response:
    response = client.get(url, timeout=25)
    response.raise_for_status()
    return response


def date_iso(raw: str) -> str:
    raw = re.sub(r"\s+", " ", raw or "").strip()
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})(?:\b|T)", raw)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d").date().isoformat()
        except ValueError:
            return ""
    match = re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b", raw)
    if match:
        try:
            return datetime(int(match.group(3)), int(match.group(2)), int(match.group(1))).date().isoformat()
        except ValueError:
            return ""
    match = re.search(r"\b(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})\b", raw.lower())
    if match and match.group(2) in MONTHS:
        try:
            return datetime(int(match.group(3)), MONTHS[match.group(2)], int(match.group(1))).date().isoformat()
        except ValueError:
            return ""
    for fmt in ("%d %B %Y", "%B %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def record(source_id: str, title: str, raw_date: str, url: str, base: str) -> dict | None:
    title = re.sub(r"\s+", " ", BeautifulSoup(title or "", "html.parser").get_text(" ", strip=True)).strip()
    absolute = urljoin(base, url or "")
    parsed = urlsplit(absolute)
    if not title or not parsed.hostname or parsed.scheme != "https":
        return None
    canonical = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    return {"source_id": source_id, "title": title, "published_date": date_iso(raw_date),
            "published_raw": (raw_date or "").strip()[:100], "url": canonical}


def collect_nic(client: requests.Session) -> list[dict]:
    base = "https://www.nic.br"
    data = fetch(client, base + "/noticias/indice/todos/indice-1.json").json()
    if not isinstance(data, list):
        raise ValueError("O índice NIC.br não retornou uma lista JSON")
    return [item for news in data[:600]
            if (item := record("nic", news.get("titulo"), news.get("data"), news.get("permalink"), base))]


def collect_edpb(client: requests.Session) -> list[dict]:
    base = "https://www.edpb.europa.eu/news_en?type%5B1%5D=1"
    soup = BeautifulSoup(fetch(client, base).text, "html.parser")
    rows = []
    for card in soup.select(".node-article-card"):
        title = card.select_one(".node-article-card__title")
        link = card.select_one("a.node-article-card__link[href]")
        if not title or not link:
            continue
        date = card.select_one("time, .views-field-created, .date-display-single")
        raw = date.get("datetime") or date.get_text(" ", strip=True) if date else ""
        item = record("edpb", title.get_text(" ", strip=True), raw, link["href"], base)
        if item:
            rows.append(item)
    return rows


def collect_mercociudades(client: requests.Session) -> list[dict]:
    base = "https://mercociudades.org/pt-br/noticias/"
    soup = BeautifulSoup(fetch(client, base).text, "html.parser")
    rows = []
    for article in soup.select("article.post"):
        link = article.select_one("h2 a[href]")
        if not link:
            continue
        date = article.select_one(".fusion-single-line-meta span, time")
        raw = date.get("datetime") or date.get_text(" ", strip=True) if date else ""
        item = record("mercociudades", link.get_text(" ", strip=True), raw, link["href"], base)
        if item:
            rows.append(item)
    return rows


def collect_senado_federal(client: requests.Session) -> list[dict]:
    base = "https://www12.senado.leg.br/noticias/ultimas"
    soup = BeautifulSoup(fetch(client, base).text, "html.parser")
    rows = []
    for article in soup.select("ol.lista-resultados > li"):
        link = article.select_one('a[href*="/noticias/materias/"]')
        if not link:
            continue
        date = article.select_one(".text-muted.normalis.hidden-xs, .text-muted.normalis-xs")
        item = record("senado_federal", link.get_text(" ", strip=True),
                      date.get_text(" ", strip=True) if date else "", link["href"], base)
        if item:
            rows.append(item)
    return rows


COLLECTORS = {
    "nic": collect_nic, "edpb": collect_edpb,
    "mercociudades": collect_mercociudades, "senado_federal": collect_senado_federal,
}


def check_notebooks() -> dict:
    shell = InteractiveShell.instance()
    results = []
    for path in sorted(ROOT.rglob("*.ipynb")):
        relative = path.relative_to(ROOT).as_posix()
        errors = []
        code_count = 0
        try:
            notebook = json.loads(path.read_text(encoding="utf-8"))
            for index, cell in enumerate(notebook["cells"]):
                if cell.get("cell_type") != "code":
                    continue
                code_count += 1
                code = shell.input_transformer_manager.transform_cell("".join(cell.get("source", [])))
                try:
                    compile(code, f"{relative}:cell{index}", "exec")
                except SyntaxError as exc:
                    errors.append(f"Célula {index}: {exc.msg}")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"Estrutura do notebook: {exc}")
        results.append({"path": relative, "code_cells": code_count,
                        "status": "syntax_ok" if not errors else "invalid", "errors": errors,
                        "runtime_status": "not_executed"})
    return {"count": len(results), "syntax_ok": sum(r["status"] == "syntax_ok" for r in results),
            "results": results}


def read_history(path: Path) -> dict[tuple[str, str], dict]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {(row["source_id"], row["url"]): row for row in rows}


def run(output: Path, collectors: dict = COLLECTORS, client: requests.Session | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "news.csv"
    previous = read_history(csv_path)
    current = dict(previous)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    source_reports = []
    client = client or session()
    for source_id, collector in collectors.items():
        try:
            records = collector(client)
            unique = {(r["source_id"], r["url"]): r for r in records}
            if not unique:
                raise ValueError("Nenhuma notícia válida encontrada; verificar URL e seletores")
            added = 0
            for key, item in unique.items():
                if key in current:
                    item["first_seen"] = current[key]["first_seen"]
                    if not item["published_date"]:
                        item["published_date"] = current[key]["published_date"]
                        item["published_raw"] = current[key]["published_raw"]
                else:
                    item["first_seen"] = now
                    added += 1
                item["last_seen"] = now
                current[key] = item
            source_reports.append({"source_id": source_id, "status": "ok", "seen": len(unique), "new": added})
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            source_reports.append({"source_id": source_id, "status": "failed", "seen": 0, "new": 0,
                                   "error": f"{type(exc).__name__}: {exc}"[:400]})
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(current[key] for key in sorted(current))
    notebooks = check_notebooks()
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    recent = [r for r in current.values() if r["published_date"] and r["published_date"] >= week_ago]
    report = {"generated_at": now, "dataset": "data/news.csv", "total_records": len(current),
              "published_last_7_days": len(recent), "sources": source_reports, "notebooks": notebooks,
              "scope": "Coleta recente de 4 fontes; verificação sintática de todos os notebooks. Não executa Colab."}
    reports = output / "runs"
    reports.mkdir(exist_ok=True)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    (reports / "latest.json").write_text(text, encoding="utf-8")
    (reports / f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json").write_text(text, encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data")
    parser.add_argument("--check-report", type=Path)
    args = parser.parse_args()
    if args.check_report:
        report = json.loads(args.check_report.read_text(encoding="utf-8"))
    else:
        report = run(args.output)
    print(f"Notebooks válidos: {report['notebooks']['syntax_ok']}/{report['notebooks']['count']}")
    for item in report["sources"]:
        print(f"{item['source_id']}: {item['status']} ({item['seen']} vistos, {item['new']} novos)")
    return int(report["notebooks"]["count"] == 0 or
               report["notebooks"]["syntax_ok"] != report["notebooks"]["count"] or
               any(item["status"] != "ok" for item in report["sources"]))


if __name__ == "__main__":
    raise SystemExit(main())
