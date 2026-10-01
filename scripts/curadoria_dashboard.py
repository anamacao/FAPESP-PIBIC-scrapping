"""Offline dashboard, reading shortlist and additional CSV import for the curator."""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
from collections import Counter
from datetime import date, timedelta
from itertools import combinations
from pathlib import Path

from curadoria_agent import contains, in_window, normalize, safe_url, write_csv


def import_csv(path: Path) -> list[dict]:
    """Accept ordinary exports from the existing notebooks without modifying them."""
    aliases = {
        "title": ("title", "titulo", "manchete", "news_title"),
        "url": ("url", "link", "permalink", "href"),
        "published_date": ("published_date", "data", "date", "fecha", "data_publicacao", "data_de_publicacao", "published"),
        "source_id": ("source_id", "fonte", "source", "origem", "instituicao"),
        "summary": ("summary", "resumo", "descricao", "abstract"),
    }
    text = path.read_text(encoding="utf-8-sig")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    fields = {normalize(k).replace(" ", "_"): k for k in (reader.fieldnames or [])}
    columns = {key: next((fields[a] for a in names if a in fields), None)
               for key, names in aliases.items()}
    if not columns["title"] or not columns["url"]:
        raise ValueError(f"{path.name}: CSV precisa de colunas título e URL/link")
    rows = []
    for raw in reader:
        row = {key: (raw.get(column) or "").strip() if column else ""
               for key, column in columns.items()}
        row["source_id"] = row["source_id"] or path.stem
        row.update(publication_type="CSV importado", corpus="scrapers", manually_selected=False,
                   first_seen="", last_seen="", input_file=path.name)
        rows.append(row)
    return rows


def merge_documents(corpus_data: dict) -> list[dict]:
    """Deduplicate across inputs; keep scraper title and preserve catalog provenance."""
    merged = {}
    for corpus, data in corpus_data.items():
        for raw in data["rows"]:
            row = dict(raw, corpora=[corpus])
            url = row["canonical_url"]
            if url not in merged:
                merged[url] = row
                continue
            old = merged[url]
            old["corpora"] = sorted(set(old["corpora"]) | {corpus})
            old["manually_selected"] = bool(old.get("manually_selected") or row.get("manually_selected"))
            if corpus == "catalogo":
                old["catalog_title"] = row["title"]
                old["catalog_summary"] = row.get("summary", "")
                old["catalog_source"] = row["source"]
            # Do not merge keyword sets from different titles: evidence stays reproducible.
    return list(merged.values())


def filter_documents(rows: list[dict], as_of: str, start: str = "", end: str = "",
                     source: str = "", topic: str = "", keyword: str = "",
                     query: str = "", include_uncertain: bool = True,
                     candidates_only: bool = True) -> list[dict]:
    if start and end and start > end:
        raise ValueError("Data inicial deve ser anterior ou igual à final")
    result = []
    end = min(end, as_of) if end else as_of
    for row in rows:
        precision, published = row["date_precision"], row["published_date"]
        if published and published > as_of:
            continue
        if candidates_only and not (row["candidate"] or row.get("manually_selected")):
            continue
        if source and row["source"] != source:
            continue
        if topic and topic not in row["topics"]:
            continue
        if keyword and keyword not in row["keywords"]:
            continue
        if query and normalize(query) not in normalize(" ".join([
                row["title"], row["source"], " ".join(row["keywords"]), " ".join(row["topics"])])):
            continue
        if precision == "day":
            if (start and published < start) or published > end:
                continue
        elif not include_uncertain:
            continue
        elif precision in {"month", "year"}:
            size = 7 if precision == "month" else 4
            if (start and published < start[:size]) or published > end[:size]:
                continue
        result.append(row)
    return sorted(result, key=lambda r: (r["published_date"], r["title"]), reverse=True)


def shortlist(rows: list[dict], as_of: date, days: int, limit: int = 5) -> list[dict]:
    start, end = (as_of - timedelta(days=days - 1)).isoformat(), as_of.isoformat()
    pool = [dict(r) for r in rows if in_window(r, start, end)
            and (r["candidate"] or r.get("manually_selected"))]
    for row in pool:
        row["priority_score"] = (min(5, len(row["keywords"])) + 2 * min(3, len(row["topics"]))
                                 + 3 * bool(row.get("manually_selected")))
    chosen, covered = [], set()
    while pool and len(chosen) < limit:
        row = max(pool, key=lambda r: (r["priority_score"] + 2 * len(set(r["topics"]) - covered),
                                      r["published_date"], r["title"]))
        pool.remove(row)
        covered.update(row["topics"])
        row["selection_reason"] = ("Termos identificados: " + (", ".join(row["keywords"]) or "nenhum no título")
                                   + ". Eixos: " + (", ".join(row["topics"]) or "revisão temática necessária")
                                   + (". Já selecionada no catálogo." if row.get("manually_selected") else "."))
        chosen.append(row)
    return chosen


def measures(rows: list[dict], config: dict, as_of: date, days: int = 7) -> dict:
    """Counts always use documents; word occurrences are separately recorded."""
    terms = Counter(k for r in rows for k in set(r["keywords"]))
    topics = Counter(t for r in rows for t in set(r["topics"]))
    sources = Counter(r["source"] for r in rows)
    stop = set(normalize(config["stopwords"]).split())
    words, occurrences = Counter(), Counter()
    pairs = Counter()
    for row in rows:
        tokens = [w for w in normalize(row.get("analysis_text", row["title"])).split()
                  if len(w) >= 3 and not w.isdigit() and w not in stop]
        words.update(set(tokens))
        occurrences.update(tokens)
        pairs.update(combinations(sorted(set(row["keywords"])), 2))
    start = (as_of - timedelta(days=days - 1)).isoformat()
    old_start = (as_of - timedelta(days=2 * days - 1)).isoformat()
    old_end = (as_of - timedelta(days=days)).isoformat()
    comparison = []
    for label in config["keywords"]:
        current = sum(label in r["keywords"] and in_window(r, start, as_of.isoformat()) for r in rows)
        previous = sum(label in r["keywords"] and in_window(r, old_start, old_end) for r in rows)
        comparison.append(dict(palavra_chave=label, atual=current, anterior=previous, diferenca=current - previous))
    return dict(
        keywords=[dict(palavra_chave=k, documentos=n) for k, n in terms.most_common()],
        topics=[dict(tema=k, documentos=topics[k]) for k in config["axes"]],
        sources=[dict(fonte=k, documentos=n) for k, n in sources.most_common()],
        words=[dict(palavra=k, documentos=n, ocorrencias=occurrences[k]) for k, n in words.most_common()],
        pairs=[dict(termo_1=a, termo_2=b, documentos=n,
                    jaccard=round(n / (terms[a] + terms[b] - n), 4))
               for (a, b), n in pairs.most_common()],
        comparison=comparison,
        months=[dict(mes=k, documentos=n) for k, n in sorted(Counter(
            r["published_date"][:7] for r in rows if r["date_precision"] in {"day", "month"}).items())],
        days=[dict(data=k, documentos=n) for k, n in sorted(Counter(
            r["published_date"] for r in rows if r["date_precision"] == "day").items())])


def notebook_figures(rows: list[dict], config: dict, as_of: date, days: int = 7,
                     comparison_rows: list[dict] | None = None) -> dict:
    import plotly.graph_objects as go
    data, figures = measures(rows, config, as_of, days), {}

    def bar(key, label, title, color="#237c83"):
        selected = data[key][:15][::-1]
        fig = go.Figure(go.Bar(x=[r["documentos"] for r in selected],
                              y=[html.escape(r[label]) for r in selected], orientation="h",
                              marker_color=color, text=[r["documentos"] for r in selected],
                              textposition="auto"))
        fig.update_layout(title=title, template="plotly_white", height=max(380, 24 * len(selected) + 170),
                          xaxis_title="Documentos", xaxis=dict(rangemode="tozero", dtick=1),
                          margin=dict(l=220, r=35, t=70, b=70))
        return fig
    figures["palavras_chave"] = bar("keywords", "palavra_chave", "Palavras-chave • uma contagem por documento")
    figures["temas"] = bar("topics", "tema", "Eixos da pesquisa • um documento pode ter vários eixos")
    figures["fontes"] = bar("sources", "fonte", "Publicações por fonte no recorte observado")
    figures["palavras_livres"] = bar("words", "palavra", "Palavras frequentes • documentos com cada palavra")
    monthly_counts = {r["mes"]: r["documentos"] for r in data["months"]}
    month_labels = []
    if monthly_counts:
        cursor = date.fromisoformat(min(monthly_counts) + "-01")
        last = max(monthly_counts)
        while cursor.strftime("%Y-%m") <= last:
            month_labels.append(cursor.strftime("%Y-%m"))
            cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    monthly = go.Figure(go.Scatter(x=month_labels,
                                  y=[monthly_counts.get(m) for m in month_labels], mode="lines+markers",
                                  line_color="#237c83", connectgaps=False))
    monthly.update_layout(title="Publicações por mês • meses não observados não são zeros verificados",
                          template="plotly_white", yaxis_title="Documentos", yaxis=dict(rangemode="tozero"))
    figures["evolucao"] = monthly
    labels = [r["palavra_chave"] for r in data["keywords"][:10]]
    matrix = [[sum(a in r["keywords"] and b in r["keywords"] for r in rows) for b in labels] for a in labels]
    figures["coocorrencias"] = go.Figure(go.Heatmap(
        z=matrix, x=labels, y=labels, colorscale="Blues", colorbar=dict(title="Documentos"),
        text=matrix, texttemplate="%{text}", hovertemplate="%{y} + %{x}: %{z} documentos<extra></extra>"))
    figures["coocorrencias"].update_layout(title="Coocorrência de termos • presença no mesmo documento",
                                          template="plotly_white", height=620, margin=dict(l=170, b=170))
    comparative = measures(comparison_rows, config, as_of, days)["comparison"] if comparison_rows is not None else data["comparison"]
    comparison = sorted(comparative, key=lambda r: -(r["atual"] + r["anterior"]))[:12]
    figures["comparacao"] = go.Figure([
        go.Bar(name="Janela anterior", x=[r["palavra_chave"] for r in comparison],
               y=[r["anterior"] for r in comparison], marker_color="#aabcc6"),
        go.Bar(name="Janela atual", x=[r["palavra_chave"] for r in comparison],
               y=[r["atual"] for r in comparison], marker_color="#237c83")])
    figures["comparacao"].update_layout(title=f"Comparação de duas janelas de {days} dias",
                                        template="plotly_white", barmode="group", height=470,
                                        xaxis=dict(tickangle=-35), yaxis=dict(rangemode="tozero"))
    return figures


def json_for_html(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace(
        "<", r"\u003c").replace(">", r"\u003e").replace("&", r"\u0026")


def export_dashboard(output: Path, corpus_data: dict, config: dict, metadata: dict) -> None:
    from plotly.offline import get_plotlyjs
    rows = merge_documents(corpus_data)
    as_of = date.fromisoformat(metadata["as_of"])
    observed = filter_documents(rows, metadata["as_of"])
    chosen = shortlist(observed, as_of, metadata["days"])
    write_csv(output / "selecionadas_semana.csv", chosen, [
        "title", "source", "published_date", "url", "priority_score", "selection_reason", "keywords", "topics"])
    data = measures(observed, config, as_of, metadata["days"])
    write_csv(output / "coocorrencias_jaccard.csv", data["pairs"],
              ["termo_1", "termo_2", "documentos", "jaccard"])
    template = Path(__file__).with_name("curadoria_dashboard.html").read_text(encoding="utf-8")
    payload = dict(documents=rows, corpora={k: d["rows"] for k, d in corpus_data.items()},
                   config=config, metadata=metadata)
    page = template.replace("__CURADORIA_DATA__", json_for_html(payload)).replace("__PLOTLY_JS__", get_plotlyjs())
    (output / "painel_interativo.html").write_text(page, encoding="utf-8")
    lines = [
        "# Curadoria FAPESP — resumo automático",
        "",
        f"Janela: {metadata['window_start']} a {metadata['as_of']} (America/Sao_Paulo).",
        f"Escopo textual: {metadata['analysis_text']}. Regras lexicais editáveis; sem API de IA.",
        "",
        "## Base e cobertura",
        "",
    ]
    for corpus, counts in metadata["corpus"].items():
        lines.append(f"- {corpus}: {counts['documents']} registros; {counts['published_window']} publicações "
                     f"datadas na janela; {counts['candidates_window']} candidatas lexicais na janela.")
    lines += ["", "## Até cinco publicações para leitura", "",
              "Ordem: termos (até 5 pontos), eixos (2 por eixo, até 6), seleção prévia no catálogo (3) "
              "e diversidade de eixos (2 por eixo ainda não coberto). A pontuação orienta a leitura.", ""]
    if not chosen:
        lines.append("Não há candidatas com data exata nesta janela. Não foram preenchidas vagas com notícias antigas.")
    for index, row in enumerate(chosen, 1):
        lines += [f"{index}. {row['title']}", f"   - Publicação: {row['published_date']} · {row['source']}",
                  f"   - Fonte: {row['url']}", f"   - Critério: {row['selection_reason']}", ""]
    lines += ["", "## Cuidados de interpretação", "",
              "- Volume observado depende da cobertura dos coletores. O corpus não representa toda a agenda pública.",
              "- Coocorrência não demonstra causalidade, influência europeia ou mediação brasileira.",
              "- Os textos completos não foram analisados. O modo title_summary também usa notas editoriais do catálogo.",
              "- Datas apenas mensais ou anuais e datas ausentes não entram na seleção semanal.",
              "- Todas as fontes do catálogo permanecem na base, mesmo sem correspondência lexical no título.", ""]
    lines += ["- " + warning for warning in metadata["warnings"]]
    (output / "resumo_semanal.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    metadata["interactive_dashboard"] = "painel_interativo.html"
    metadata["shortlist_count"] = len(chosen)
    metadata["combined_unique_documents"] = len(rows)
    metadata["dashboard_sha256"] = hashlib.sha256(page.encode("utf-8")).hexdigest()
