"""Agente reproduzível de tabelas e gráficos da curadoria FAPESP.

Analisa títulos, sem inferir o conteúdo integral das publicações. Lê a base dos
scrapers e, opcionalmente, o catálogo Markdown, mantendo os dois corpus separados.
Não consulta uma API de IA, não inventa dados e nunca escreve nos arquivos de entrada.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import json
import re
import sys
import textwrap
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MONTHS = dict(zip(
    "janeiro fevereiro marco abril maio junho julho agosto setembro outubro novembro dezembro".split(),
    range(1, 13)))
MONTHS.update(dict(zip(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(),
    range(1, 13))))
MONTHS.update(dict(zip(
    "january february march april may june july august september october november december".split(),
    range(1, 13))))


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value).lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


def contains(text: str, phrase: str) -> bool:
    """Whole words/phrases: 'IA' must not match 'viagem' or 'social'."""
    return bool(phrase) and f" {phrase} " in f" {text} "


def safe_url(raw: str) -> str:
    try:
        parsed = urlsplit(str(raw).strip())
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username:
            return ""
        query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(),
                           parsed.path or "/", urlencode(sorted(query)), ""))
    except ValueError:
        return ""


def publication_date(raw: str) -> tuple[str, str]:
    """Return an ISO day or month; never substitute first_seen for publication."""
    value = normalize(raw)
    iso = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:T.*)?", raw.strip())
    if iso:
        try:
            return date.fromisoformat(iso[1]).isoformat(), "day"
        except ValueError:
            return "", "unknown"
    numeric = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw.strip())
    named = re.fullmatch(r"(\d{1,2})(?:o)? de (\w+) de (\d{4})", value)
    try:
        if numeric:
            return date(int(numeric[3]), int(numeric[2]), int(numeric[1])).isoformat(), "day"
        if named and named[2] in MONTHS:
            return date(int(named[3]), MONTHS[named[2]], int(named[1])).isoformat(), "day"
        month = re.fullmatch(r"(\w+) de (\d{4})", value)
        if month and month[1] in MONTHS:
            return f"{int(month[2]):04d}-{MONTHS[month[1]]:02d}", "month"
        if re.fullmatch(r"\d{4}-\d{2}", raw.strip()):
            date.fromisoformat(raw.strip() + "-01")
            return raw.strip(), "month"
        if re.fullmatch(r"\d{4}", raw.strip()) and 1 <= int(raw.strip()) <= 9999:
            return raw.strip(), "year"
        for fmt in ("%d %B %Y", "%B %d, %Y", "%d %b %Y", "%B %Y"):
            try:
                parsed = datetime.strptime(raw.strip(), fmt)
                return (parsed.strftime("%Y-%m"), "month") if fmt == "%B %Y" else (parsed.date().isoformat(), "day")
            except ValueError:
                pass
    except ValueError:
        pass
    return "", "unknown"


def seen_date(raw: str) -> str:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo("America/Sao_Paulo")).date().isoformat()
    except (ValueError, AttributeError):
        return ""


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    known = set(config["keywords"])
    required = set(config["relevance_keywords"])
    for rule in config["axes"].values():
        required.update(rule.get("any_keywords", []))
        for group in rule.get("all_groups", []):
            required.update(group)
    if required - known:
        raise ValueError(f"Palavras-chave não definidas: {sorted(required - known)}")
    return config


def read_news(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not {"source_id", "title", "published_date", "url"}.issubset(reader.fieldnames or []):
            raise ValueError("CSV deve conter source_id, title, published_date e url")
        return [{**row, "publication_type": row.get("publication_type") or "Notícia coletada",
                 "summary": row.get("summary", ""), "access": row.get("access", ""),
                 "evidence": row.get("evidence", ""), "corpus": "scrapers",
                 "manually_selected": False} for row in reader]


def read_catalog(path: Path) -> list[dict]:
    """Parse existing ### entries without turning outline headings into records."""
    entries = []
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            if current:
                entries.append(current)
            current = {"title": line[4:].strip(), "links": []}
        elif re.match(r"^#{1,2} ", line):
            if current:
                entries.append(current)
            current = None
        elif current:
            match = re.match(r"^- \*\*(.+?):\*\*\s*(.*)", line)
            if match:
                key, value = normalize(match[1]), match[2].strip()
                current[key] = value
                if key in {"link", "texto integral", "apresentacao oficial da ue"}:
                    current["links"].extend(re.findall(r"https?://[^\s<>]+", value))
    if current:
        entries.append(current)
    rows = []
    for entry in entries:
        if not entry["links"]:
            raise ValueError(f"Entrada do catálogo sem link: {entry['title']}")
        source = next((entry[k] for k in ("instituicao", "instituicoes", "fonte", "autores", "autoras",
                      "autor", "autora", "instituicao responsavel pelas diretrizes") if entry.get(k)), "Não informada")
        published = entry.get("data", entry.get("atualizacao documental mais recente listada", ""))
        rows.append({"source_id": source, "title": entry["title"], "published_date": published,
                     "published_raw": published, "url": entry["links"][0],
                     "other_links": "; ".join(entry["links"][1:]), "first_seen": "", "last_seen": "",
                     "publication_type": entry.get("tipo", "Não informado"),
                     "summary": entry.get("uso no relatorio", ""),
                     "evidence": entry.get("classificacao", ""), "access": entry.get("acesso", ""),
                     "corpus": "catalogo", "manually_selected": True})
    return rows


def prepare(rows: list[dict], config: dict, analysis_text: str = "title") -> tuple[list[dict], dict]:
    if analysis_text not in {"title", "title_summary"}:
        raise ValueError("analysis_text deve ser title ou title_summary")
    unique = {}
    stats = {"input_rows": len(rows), "duplicates_removed": 0, "invalid_records": 0}
    aliases = {label: sorted({normalize(alias) for alias in phrases}, key=len, reverse=True)
               for label, phrases in config["keywords"].items()}
    for original in rows:
        row = dict(original)
        row["title"] = " ".join(str(row.get("title", "")).split())
        canonical = safe_url(row.get("url", ""))
        if not canonical or not row["title"]:
            stats["invalid_records"] += 1
            continue
        parsed, precision = publication_date(str(row.get("published_date", "")))
        row.update(canonical_url=canonical, published_date=parsed, date_precision=precision,
                   published_raw=row.get("published_raw") or original.get("published_date", ""),
                   source=config["source_names"].get(row["source_id"], row["source_id"]),
                   first_seen_date=seen_date(row.get("first_seen", "")))
        row["analysis_text"] = row["title"]
        if analysis_text == "title_summary" and row.get("summary"):
            row["analysis_text"] += " " + str(row["summary"])
        text = normalize(row["analysis_text"])
        matches = {label: [alias for alias in phrases if contains(text, alias)]
                   for label, phrases in aliases.items()}
        row["keywords"] = [label for label, hits in matches.items() if hits]
        row["candidate"] = bool(set(row["keywords"]) & set(config["relevance_keywords"]))
        topics = []
        if row["candidate"] or row.get("manually_selected"):
            for label, rule in config["axes"].items():
                any_ok = not rule.get("any_keywords") or bool(set(rule["any_keywords"]) & set(row["keywords"]))
                all_ok = all(set(group) & set(row["keywords"]) for group in rule.get("all_groups", []))
                if any_ok and all_ok:
                    topics.append(label)
        row["topics"] = topics
        row["match_evidence"] = "; ".join(f"{label}: {', '.join(hits)}" for label, hits in matches.items() if hits)
        if canonical in unique:
            stats["duplicates_removed"] += 1
            old = unique[canonical]
            # Duplicate URLs represent one document. Prefer usable dates, retain earliest detection.
            if old["date_precision"] == "day" and precision != "day":
                row.update(published_date=old["published_date"], date_precision=old["date_precision"],
                           published_raw=old["published_raw"])
            detections = sorted(x for x in [old.get("first_seen_date"), row["first_seen_date"]] if x)
            if detections:
                row["first_seen_date"] = detections[0]
                timestamps = [value for value in [old.get("first_seen"), row.get("first_seen")]
                              if value and seen_date(value) == detections[0]]
                if timestamps:
                    row["first_seen"] = min(timestamps)
            row["also_sources"] = sorted(set(old.get("also_sources", [old["source"]])) | {row["source"]})
        unique[canonical] = row
    return sorted(unique.values(), key=lambda r: (r["published_date"], r["title"]), reverse=True), stats


def in_window(row: dict, start: str, end: str) -> bool:
    return row["date_precision"] == "day" and start <= row["published_date"] <= end


def summarize(rows: list[dict], config: dict, as_of: date, days: int, diagnostics: dict | None = None) -> dict:
    start = (as_of - timedelta(days=days - 1)).isoformat()
    end = as_of.isoformat()
    week = [r for r in rows if in_window(r, start, end)]
    eligible = [r for r in rows if r["candidate"] and
                (not r["published_date"] or r["published_date"] <= end)]
    recent = [r for r in week if r["candidate"]]
    prior_start = (as_of - timedelta(days=2 * days - 1)).isoformat()
    prior_end = (as_of - timedelta(days=days)).isoformat()
    prior = [r for r in eligible if in_window(r, prior_start, prior_end)]
    report_sources = {r["source_id"]: r for r in (diagnostics or {}).get("sources", [])}
    source_rows = []
    source_ids = set(r["source_id"] for r in rows) | set(report_sources)
    for source_id in sorted(source_ids):
        selected = [r for r in rows if r["source_id"] == source_id]
        status = report_sources.get(source_id, {})
        source_rows.append({"fonte": config["source_names"].get(source_id, source_id),
                            "total_base": len(selected),
                            "candidatas_base": sum(r["candidate"] for r in selected),
                            "publicadas_janela": sum(in_window(r, start, end) for r in selected),
                            "candidatas_janela": sum(r["candidate"] and in_window(r, start, end) for r in selected),
                            "links_detectados_janela": sum(start <= r["first_seen_date"] <= end for r in selected),
                            "sem_data_exata": sum(r["date_precision"] != "day" for r in selected),
                            "status_ultima_coleta": status.get("status", "não informado"),
                            "observacao": status.get("error", status.get("coverage_note", ""))})
    topic_rows = [{"tema": axis, "candidatas_historico": sum(axis in r["topics"] for r in eligible),
                   "candidatas_janela": sum(axis in r["topics"] for r in recent)} for axis in config["axes"]]
    daily = [{"data": (as_of - timedelta(days=days - 1 - i)).isoformat(),
              "publicadas": sum(r["published_date"] == (as_of - timedelta(days=days - 1 - i)).isoformat() for r in week),
              "candidatas": sum(r["published_date"] == (as_of - timedelta(days=days - 1 - i)).isoformat() for r in recent)}
             for i in range(days)]
    monthly = Counter(r["published_date"][:7] for r in eligible if r["date_precision"] in {"day", "month"})
    terms = []
    for label in config["keywords"]:
        historical = sum(label in r["keywords"] for r in eligible)
        current = sum(label in r["keywords"] for r in recent)
        previous = sum(label in r["keywords"] for r in prior)
        terms.append({"palavra_chave": label, "documentos_historico": historical,
                      "documentos_janela": current, "documentos_janela_anterior": previous,
                      "variacao_documentos": current - previous,
                      "percentual_candidatas_janela": round(100 * current / len(recent), 2) if recent else ""})
    terms.sort(key=lambda r: (-r["documentos_historico"], r["palavra_chave"]))
    stopwords = set(normalize(config["stopwords"]).split())
    occurrences, documents = Counter(), Counter()
    for row in eligible:
        words = [w for w in normalize(row.get("analysis_text", row["title"])).split()
                 if len(w) >= 3 and not w.isdigit() and w not in stopwords]
        occurrences.update(words)
        documents.update(set(words))
    words = [{"palavra": w, "ocorrencias": n, "documentos": documents[w]}
             for w, n in occurrences.most_common(100)]
    pairs = Counter()
    for row in eligible:
        pairs.update(combinations(sorted(set(row["keywords"])), 2))
    cooccurrences = [{"termo_1": a, "termo_2": b, "documentos": n}
                     for (a, b), n in sorted(pairs.items(), key=lambda p: (-p[1], p[0]))]
    return {"start": start, "end": end, "prior_start": prior_start, "prior_end": prior_end,
            "rows": rows, "week": week, "eligible": eligible, "recent": recent,
            "sources": source_rows, "topics": topic_rows, "daily": daily,
            "monthly": [{"mes": m, "candidatas": n} for m, n in sorted(monthly.items())],
            "keywords": terms, "words": words, "cooccurrences": cooccurrences,
            "counts": {"documents": len(rows), "candidates": len(eligible), "published_window": len(week),
                       "candidates_window": len(recent), "candidates_previous_window": len(prior),
                       "without_exact_date": sum(r["date_precision"] != "day" for r in rows),
                       "future_publications": sum(r["published_date"] > end for r in rows),
                       "candidates_without_axis": sum(not r["topics"] for r in eligible)}}


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            # Neutralize spreadsheet formulas when CSVs are opened in Excel/Sheets.
            clean = {}
            for key in fields:
                value = row.get(key, "")
                if isinstance(value, list):
                    value = "; ".join(value)
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    value = "'" + value
                clean[key] = value
            writer.writerow(clean)


def save_tables(folder: Path, data: dict) -> None:
    document_fields = ["title", "source", "publication_type", "published_date", "date_precision",
                       "published_raw", "url", "other_links", "candidate", "topics", "keywords",
                       "match_evidence", "first_seen", "first_seen_date", "last_seen", "summary", "evidence", "access",
                       "manually_selected", "analysis_text"]
    for filename, key in [("documentos", "rows"), ("publicadas_janela", "week"), ("candidatas_janela", "recent")]:
        write_csv(folder / f"{filename}.csv", data[key], document_fields)
    for filename, key, fields in [
        ("por_fonte", "sources", ["fonte", "total_base", "candidatas_base", "publicadas_janela", "candidatas_janela", "links_detectados_janela", "sem_data_exata", "status_ultima_coleta", "observacao"]),
        ("por_tema", "topics", ["tema", "candidatas_historico", "candidatas_janela"]),
        ("por_dia", "daily", ["data", "publicadas", "candidatas"]),
        ("por_mes", "monthly", ["mes", "candidatas"]),
        ("palavras_chave", "keywords", ["palavra_chave", "documentos_historico", "documentos_janela", "documentos_janela_anterior", "variacao_documentos", "percentual_candidatas_janela"]),
        ("palavras_frequentes", "words", ["palavra", "ocorrencias", "documentos"]),
        ("coocorrencias", "cooccurrences", ["termo_1", "termo_2", "documentos"])]:
        write_csv(folder / f"{filename}.csv", data[key], fields)


def charts(folder: Path, data: dict, label: str) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    paths = []

    def save(fig, filename, note):
        fig.text(0.02, 0.02, textwrap.fill(note, 120), fontsize=8, color="#526173")
        fig.tight_layout(rect=(0.02, 0.09, 0.98, 0.98))
        path = folder / filename
        fig.savefig(path, dpi=160, facecolor="white")
        plt.close(fig)
        paths.append(path)

    def bar(rows, xkey, value, title, filename, note):
        selected = [r for r in rows if r[value] > 0][:15]
        fig, ax = plt.subplots(figsize=(10.2, max(4.5, 0.38 * len(selected) + 2.3)))
        ax.set_title(title, loc="left", pad=18, fontweight="bold")
        if selected:
            labels = [textwrap.fill(str(r[xkey]), 42) for r in selected][::-1]
            values = [r[value] for r in selected][::-1]
            bars = ax.barh(labels, values, color="#287d8e")
            ax.bar_label(bars, padding=4)
            ax.set_xlim(0, max(values) * 1.2 + 0.5)
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            ax.set_xlabel("Documentos")
        else:
            ax.text(0.5, 0.5, "Sem documentos disponíveis neste recorte", ha="center", transform=ax.transAxes)
            ax.set_axis_off()
        save(fig, filename, note)

    window = f"{data['start']} a {data['end']}"
    caution = "Contagem de documentos observados; cobertura depende dos scrapers. Zero observado não prova ausência de publicações."
    bar(sorted(data["sources"], key=lambda r: -r["candidatas_janela"]), "fonte", "candidatas_janela",
        f"{label} · candidatas por fonte\n{window}", "fontes_janela.png", caution)
    bar(data["topics"], "tema", "candidatas_historico", f"{label} · eixos de pesquisa no histórico",
        "temas_historico.png", "Classificação lexical dos títulos. Um documento pode integrar vários eixos; as barras não somam o total de documentos.")
    bar(data["keywords"], "palavra_chave", "documentos_historico", f"{label} · palavras-chave no histórico",
        "palavras_chave_historico.png", "Sinônimos em português, inglês e espanhol são agrupados. Cada termo conta uma vez por documento; somente candidatas lexicais.")
    bar(sorted(data["words"], key=lambda r: -r["documentos"]), "palavra", "documentos",
        f"{label} · palavras frequentes nos títulos", "palavras_frequentes_historico.png",
        "Número de documentos com cada palavra após remoção de palavras funcionais. Grafia normalizada; frequências brutas estão no CSV.")
    fig, ax = plt.subplots(figsize=(10.2, 4.7))
    ax.plot(range(len(data["daily"])), [r["publicadas"] for r in data["daily"]], label="Todas as publicações observadas", marker="o", color="#99a8b5")
    ax.plot(range(len(data["daily"])), [r["candidatas"] for r in data["daily"]], label="Candidatas para leitura", marker="o", color="#287d8e")
    step = max(1, len(data["daily"]) // 10)
    ticks = list(range(0, len(data["daily"]), step))
    ax.set_xticks(ticks, [data["daily"][i]["data"][5:] for i in ticks], rotation=30)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True)); ax.set_ylim(bottom=0)
    ax.set_title(f"{label} · data de publicação\n{window}", loc="left", fontweight="bold", pad=18)
    ax.set_ylabel("Documentos"); ax.legend(frameon=False)
    save(fig, "publicacoes_janela.png", caution + " Datas ausentes ou apenas mensais ficam fora da janela diária.")
    fig, ax = plt.subplots(figsize=(10.2, 4.7))
    if data["monthly"]:
        months = [r["mes"] for r in data["monthly"]]
        ax.bar(range(len(months)), [r["candidatas"] for r in data["monthly"]], color="#287d8e")
        step = max(1, len(months) // 12)
        ticks = list(range(0, len(months), step))
        ax.set_xticks(ticks, [months[i] for i in ticks], rotation=45, ha="right")
        ax.yaxis.set_major_locator(MaxNLocator(integer=True)); ax.set_ylabel("Candidatas")
    else:
        ax.text(0.5, 0.5, "Sem publicações com mês identificável", ha="center", transform=ax.transAxes)
        ax.set_axis_off()
    ax.set_title(f"{label} · publicações candidatas por mês", loc="left", fontweight="bold", pad=18)
    save(fig, "publicacoes_mensais.png", "Agrupamento pela publicação: aceita datas com precisão de dia ou mês. Datas desconhecidas e futuras ficam fora. Meses exibidos são os observados na base.")
    labels = [r["palavra_chave"] for r in data["keywords"] if r["documentos_historico"] > 0][:10]
    fig, ax = plt.subplots(figsize=(10.4, 8.4))
    ax.set_title(f"{label} · coocorrência de palavras-chave nos títulos", loc="left", fontweight="bold", pad=18)
    if labels:
        matrix = [[sum(a in r["keywords"] and b in r["keywords"] for r in data["eligible"])
                   for b in labels] for a in labels]
        im = ax.imshow(matrix, cmap="Blues", vmin=0)
        ax.set_xticks(range(len(labels)), [textwrap.fill(x, 20) for x in labels], rotation=60, ha="right")
        ax.set_yticks(range(len(labels)), [textwrap.fill(x, 23) for x in labels])
        maximum = max(max(row) for row in matrix)
        for i, row in enumerate(matrix):
            for j, n in enumerate(row):
                ax.text(j, i, str(n), ha="center", va="center", color="white" if n > maximum / 2 else "#163047", fontsize=9)
        fig.colorbar(im, ax=ax, shrink=0.65, label="Documentos")
    else:
        ax.text(0.5, 0.5, "Sem palavras-chave identificadas", ha="center", transform=ax.transAxes); ax.set_axis_off()
    save(fig, "coocorrencias_historico.png", "Termos presentes no mesmo título; não indica causalidade ou influência regulatória. A diagonal mostra documentos com o próprio termo.")
    return paths


def html_table(rows: list[dict], fields: list[tuple[str, str]], searchable: bool = False) -> str:
    headers = "".join(f"<th>{html.escape(label)}</th>" for _, label in fields)
    body = []
    for row in rows:
        cells = []
        for key, _ in fields:
            value = row.get(key, "")
            if key == "candidate":
                value = "Sim" if value else "Sem correspondência"
            elif key == "date_precision":
                value = {"day": "Dia", "month": "Mês", "year": "Ano", "unknown": "Não informada"}.get(value, value)
            if isinstance(value, list):
                value = "; ".join(value)
            if key == "title" and safe_url(row.get("url", "")):
                cell = f'<a href="{html.escape(row["url"], quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(str(value))}</a>'
            else:
                cell = html.escape(str(value))
            cells.append(f"<td>{cell}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    empty = f'<tr><td colspan="{len(fields)}">Sem documentos neste recorte.</td></tr>'
    return f'<div class="table-wrap"><table class="{"searchable" if searchable else "summary-table"}"><thead><tr>{headers}</tr></thead><tbody>{"".join(body) or empty}</tbody></table></div>'


def render_report(output: Path, corpus_data: dict, image_paths: dict, metadata: dict) -> None:
    blocks = []
    esc = html.escape
    for corpus, data in corpus_data.items():
        label = "Notícias dos scrapers" if corpus == "scrapers" else "Fontes selecionadas no catálogo"
        counts = data["counts"]
        cards = "".join(f'<div class="card"><strong>{n}</strong><span>{esc(text)}</span></div>' for n, text in [
            (counts["documents"], "Documentos na base"), (counts["candidates"], "Candidatas lexicais no histórico"),
            (counts["published_window"], "Publicadas na janela"), (counts["candidates_window"], "Candidatas na janela")])
        images = []
        for path in image_paths[corpus]:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            images.append(f'<figure><img src="data:image/png;base64,{encoded}" alt="{esc(path.stem)}" loading="lazy"></figure>')
        source_table = html_table(data["sources"], [("fonte", "Fonte"), ("total_base", "Base"),
            ("publicadas_janela", "Publicadas na janela"), ("candidatas_janela", "Candidatas na janela"),
            ("links_detectados_janela", "Primeira detecção na janela"), ("status_ultima_coleta", "Última coleta"), ("observacao", "Observação")])
        keywords = html_table(data["keywords"], [("palavra_chave", "Palavra-chave"), ("documentos_historico", "Histórico"),
            ("documentos_janela", "Janela atual"), ("documentos_janela_anterior", "Janela anterior"), ("variacao_documentos", "Variação observada")])
        documents = html_table(data["rows"], [("title", "Título e link"), ("source", "Fonte"),
            ("publication_type", "Tipo"), ("published_date", "Publicação"), ("date_precision", "Precisão"),
            ("candidate", "Candidata lexical"), ("topics", "Eixos"), ("keywords", "Palavras-chave"),
            ("match_evidence", "Termos encontrados")], searchable=True)
        downloads = " · ".join(f'<a href="{corpus}/{name}">{esc(name)}</a>' for name in [
            "documentos.csv", "candidatas_janela.csv", "por_fonte.csv", "por_tema.csv", "por_dia.csv", "por_mes.csv", "palavras_chave.csv", "palavras_frequentes.csv", "coocorrencias.csv"])
        blocks.append(f'<section><h2>{label}</h2><div class="cards">{cards}</div><p>Sem data exata: {counts["without_exact_date"]}. '
                      f'Publicações futuras excluídas do histórico e da janela: {counts["future_publications"]}. Candidatas sem eixo correspondente: {counts["candidates_without_axis"]}.</p>'
                      f'<h3>Cobertura e fontes</h3>{source_table}<div class="charts">{"".join(images)}</div>'
                      f'<h3>Palavras-chave e comparação com a janela anterior</h3><p>{data["prior_start"]} a {data["prior_end"]}; as diferenças dependem também da cobertura da coleta.</p>{keywords}'
                      f'<h3>Documentos e evidências da classificação</h3>{documents}<details><summary>Baixar tabelas CSV</summary><p>{downloads}</p></details></section>')
    warnings = "".join(f"<li>{esc(w)}</li>" for w in metadata["warnings"])
    document = '''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Curadoria FAPESP — tabelas e gráficos</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f6f9;color:#203146;font:15px/1.55 system-ui,sans-serif}main{max-width:1250px;margin:auto;padding:32px 24px}h1{font-size:32px;line-height:1.2}h2{font-size:24px}h3{margin-top:28px}a{color:#17677e}header,section{background:white;border:1px solid #e0e6ee;border-radius:14px;padding:28px;margin-bottom:24px}.eyebrow{color:#287d8e;font-weight:700;letter-spacing:.12em;text-transform:uppercase;font-size:12px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{background:#eff6f7;border-radius:9px;padding:16px}.card strong{font-size:28px;display:block}.card span{font-size:13px}.table-wrap{overflow:auto;max-height:520px;border:1px solid #e0e6ee;border-radius:8px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:10px 12px;border-bottom:1px solid #e0e6ee;text-align:left;vertical-align:top;min-width:100px}td:first-child{min-width:250px}th{background:#edf2f7;position:sticky;top:0}tbody tr:hover{background:#f6f9fc}.charts{display:grid;grid-template-columns:1fr 1fr;gap:12px}figure{margin:18px 0 0}img{width:100%;height:auto}input{padding:12px;border:1px solid #a6b7c7;border-radius:7px;width:100%;font:inherit}.warning{background:#fff7e5;padding:14px;border-radius:8px}summary{cursor:pointer;color:#17677e}footer{font-size:13px;color:#526173}@media(max-width:800px){main{padding:16px 10px}header,section{padding:18px}.cards{grid-template-columns:1fr 1fr}.charts{grid-template-columns:1fr}}
</style></head><body><main><header><div class="eyebrow">Pesquisa FAPESP · Governança digital</div><h1>Curadoria: notícias, temas e palavras-chave</h1>'''
    document += f'<p>Janela de publicação: <strong>{metadata["window_start"]} a {metadata["as_of"]}</strong> · horário de Brasília. Gerado em {metadata["generated_at"]}.</p>'
    scope = "títulos" if metadata["analysis_text"] == "title" else "títulos e notas editoriais fornecidas (não o texto integral)"
    document += f'<p>Os gráficos analisam os <strong>{scope}</strong>. “Candidata” significa correspondência lexical para leitura; a pertinência acadêmica requer revisão. Os cinco eixos são multilabel. Os corpus dos scrapers e do catálogo aparecem separadamente.</p>'
    document += '<p><a href="painel_interativo.html">Abrir painel com filtros e gráficos interativos</a> · <a href="resumo_semanal.md">Resumo automático e sugestões de leitura</a></p>'
    document += '<p>Palavras-chave usam um dicionário editável com sinônimos em português, inglês e espanhol. Coocorrência mostra termos no mesmo título e não demonstra influência regulatória.</p>'
    if warnings:
        document += f'<div class="warning"><strong>Limites da base</strong><ul>{warnings}</ul></div>'
    document += '<p><label for="search">Buscar nos títulos, fontes, temas ou palavras-chave das tabelas de documentos</label></p><input id="search" type="search" placeholder="Ex.: LGPD, inteligência artificial, Mercosul…"></header>'
    document += "".join(blocks)
    document += f'<footer>Entradas e versões de configuração estão registradas em <a href="resumo.json">resumo.json</a>. A base é uma amostra das fontes monitoradas, sem pretensão de cobertura universal. Catálogo: metadados fornecidos no arquivo; o agente não verifica o conteúdo dos links.</footer>'
    document += '''</main><script>document.getElementById('search').addEventListener('input',e=>{const norm=s=>s.normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();const q=norm(e.target.value);document.querySelectorAll('table.searchable tbody tr').forEach(r=>{r.hidden=!norm(r.textContent).includes(q)})});</script></body></html>'''
    (output / "index.html").write_text(document, encoding="utf-8")


def run(news: Path, output: Path, config_path: Path, as_of: date, days: int = 7,
        catalog: Path | None = None, report_path: Path | None = None,
        analysis_text: str = "title") -> dict:
    if not 1 <= days <= 366:
        raise ValueError("days deve estar entre 1 e 366")
    config = load_config(config_path)
    diagnostics, warnings = {}, []
    if report_path and report_path.exists():
        diagnostics = json.loads(report_path.read_text(encoding="utf-8"))
        generated = seen_date(diagnostics.get("generated_at", ""))
        if not generated:
            warnings.append("Diagnóstico da coleta sem data válida.")
        elif (as_of - date.fromisoformat(generated)).days > 1:
            warnings.append(f"A última coleta registrada é de {generated}; a janela atual pode estar incompleta.")
        for source in diagnostics.get("sources", []):
            if source.get("status") != "ok":
                warnings.append(f"Fonte {source['source_id']}: {source.get('status', 'unknown')}; {source.get('error', source.get('coverage_note', 'cobertura incompleta'))}")
            elif source.get("coverage_note"):
                warnings.append(f"{source['source_id']}: {source['coverage_note']}")
    else:
        warnings.append("Diagnóstico da coleta não fornecido; funcionamento e cobertura das fontes não confirmados.")
    inputs = {"scrapers": news}
    raw = {"scrapers": read_news(news)}
    if catalog:
        inputs["catalogo"] = catalog
        raw["catalogo"] = read_catalog(catalog)
    output.mkdir(parents=True, exist_ok=True)
    corpus_data, image_paths, quality = {}, {}, {}
    for corpus, rows in raw.items():
        clean, stats = prepare(rows, config, analysis_text)
        data = summarize(clean, config, as_of, days, diagnostics if corpus == "scrapers" else None)
        stats.update(data["counts"])
        quality[corpus] = stats
        folder = output / corpus
        folder.mkdir(parents=True, exist_ok=True)
        save_tables(folder, data)
        label = "Scrapers" if corpus == "scrapers" else "Catálogo"
        image_paths[corpus] = charts(folder, data, label)
        corpus_data[corpus] = data
    if not catalog:
        warnings.append("O catálogo da curadoria não foi fornecido: estas saídas cobrem somente as notícias dos scrapers.")
    source_metadata = {corpus: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                       for corpus, path in inputs.items()}
    metadata = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "as_of": as_of.isoformat(), "window_start": (as_of - timedelta(days=days - 1)).isoformat(),
                "days": days, "timezone": "America/Sao_Paulo", "analysis_text": analysis_text,
                "config_version": config["version"], "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                "inputs": source_metadata, "corpus": quality, "warnings": warnings,
                "collection_generated_at": diagnostics.get("generated_at"),
                "method": "Correspondências lexicais com sinônimos; multilabel; URL canônica deduplicada por corpus; publicação distinta de primeira detecção."}
    render_report(output, corpus_data, image_paths, metadata)
    # The offline interactive dashboard also supplies a weekly reading shortlist.
    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    from curadoria_dashboard import export_dashboard
    export_dashboard(output, corpus_data, config, metadata)
    (output / "resumo.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--news", type=Path, default=ROOT / "data/news.csv")
    saved_catalog = ROOT / "data/curadoria/Catalogo_de_fontes_FAPESP.md"
    parser.add_argument("--catalog", type=Path, default=saved_catalog if saved_catalog.exists() else None)
    parser.add_argument("--collection-report", type=Path, default=ROOT / "data/runs/latest.json")
    parser.add_argument("--config", type=Path, default=ROOT / "config/curadoria.json")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/curadoria/latest")
    parser.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(ZoneInfo("America/Sao_Paulo")).date())
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--analysis-text", choices=("title", "title_summary"), default="title",
                        help="title_summary inclui notas editoriais; não representa texto integral")
    args = parser.parse_args()
    metadata = run(args.news, args.output, args.config, args.as_of, args.days, args.catalog,
                   args.collection_report, args.analysis_text)
    print(f"Relatório: {args.output / 'index.html'}")
    for corpus, counts in metadata["corpus"].items():
        print(f"{corpus}: {counts['documents']} documentos, {counts['candidates']} candidatas no histórico, {counts['candidates_window']} na janela")
    for warning in metadata["warnings"]:
        print(f"ATENÇÃO: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
