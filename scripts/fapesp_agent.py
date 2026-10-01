"""Consolidate the original FAPESP notebooks into an auditable research dashboard.

The Drive notebooks remain the collectors of record. This module reads their
current collector configuration, runs each distinct collection once, and adds
the cumulative weekly CSV. Published dates are never replaced by crawl dates.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from html import escape
from io import BytesIO
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests


FOLDER_ID = "1SpKKCSz99_V6OsMLzN7XNYFHXXullzvu"
WEEKLY_CSV = "https://raw.githubusercontent.com/anamacao/FAPESP-PIBIC-scrapping/main/data/news.csv"
SELF_NAME = "agente_fapesp_unificado.ipynb"
ANALYSIS_NAMES = {"charts (1).ipynb", "database_analysis (1).ipynb"}

# País/região se refere à instituição publicadora, não ao assunto da notícia.
SOURCE_META = {
    "aaip": ("Argentina", "Mercosul", "AAIP"),
    "icn_argentina": ("Argentina", "Mercosul", "ICN Congreso"),
    "anpd": ("Brasil", "Mercosul", "ANPD"),
    "camara_federal": ("Brasil", "Mercosul", "Câmara dos Deputados"),
    "cgi": ("Brasil", "Mercosul", "CGI.br"),
    "dataprivacy": ("Brasil", "Mercosul", "Data Privacy Brasil"),
    "internetlab": ("Brasil", "Mercosul", "InternetLab"),
    "nic": ("Brasil", "Mercosul", "NIC.br"),
    "senado": ("Brasil", "Mercosul", "Senado Federal"),
    "senado_federal": ("Brasil", "Mercosul", "Agência Senado"),
    "agesic": ("Uruguai", "Mercosul", "AGESIC"),
    "parlamento_uy": ("Uruguai", "Mercosul", "Parlamento do Uruguai"),
    "impo_uruguay": ("Uruguai", "Mercosul", "IMPO"),
    "urcdp": ("Uruguai", "Mercosul", "URCDP"),
    "mitic_paraguai": ("Paraguai", "Mercosul", "MITIC"),
    "mercociudades": ("Regional", "Mercosul", "Mercociudades"),
    "observacom": ("Regional", "América Latina", "OBSERVACOM"),
    "ue_news": ("União Europeia", "UE", "Portal da União Europeia"),
    "comissao_europeia": ("União Europeia", "UE", "Comissão Europeia (verificar URL)"),
    "edpb": ("União Europeia", "UE", "EDPB"),
    "dsa_transparency": ("União Europeia", "UE", "DSA Transparency Database"),
    "google_transparency": ("Global", "Global", "Google Transparency"),
    "meta_transparency": ("Global", "Global", "Meta Transparency"),
    "icann": ("Global", "Global", "ICANN"),
}

MONTHS = {
    "janeiro": 1, "enero": 1, "february": 2, "fevereiro": 2, "febrero": 2,
    "marco": 3, "marzo": 3, "march": 3, "abril": 4, "april": 4,
    "maio": 5, "mayo": 5, "may": 5, "junho": 6, "junio": 6, "june": 6,
    "julho": 7, "julio": 7, "july": 7, "agosto": 8, "august": 8,
    "setembro": 9, "septiembre": 9, "setiembre": 9, "september": 9,
    "outubro": 10, "octubre": 10, "october": 10, "novembro": 11,
    "noviembre": 11, "november": 11, "dezembro": 12, "diciembre": 12,
    "december": 12, "january": 1,
}

TOPICS = {
    "Proteção de dados": [r"\bgdpr\b", r"\brgpd\b", r"\blgpd\b", r"\bprivacy\b",
        r"\bprivacid", r"\bdata protection\b", r"\bprote[cct]+ao de dados\b",
        r"\bproteccion de datos\b", r"\bdados pessoais\b", r"\bdatos personales\b"],
    "IA e algoritmos": [r"\binteligencia artificial\b", r"\bartificial intelligence\b",
        r"\balgoritm", r"\bai act\b", r"\bai\b", r"\bia\b", r"\bgenerativ"],
    "Plataformas e moderação": [r"\bplatform", r"\bplataforma", r"\bmoderac",
        r"\bmoderation\b", r"\bdesinform", r"\bdisinform", r"\bdsa\b",
        r"\bdigital services act\b", r"\bredes sociais\b", r"\bredes sociales\b"],
    "Internet e infraestrutura": [r"\binternet\b", r"\bdns\b", r"\bicann\b",
        r"\bcibersegur", r"\bcyber", r"\bconectividad", r"\bconectividade"],
    "Mercosul e integração": [r"\bmercosul\b", r"\bmercosur\b", r"\bintegracion",
        r"\bintegracao", r"\binterregional", r"\buniao europeia\b", r"\beuropean union\b"],
    "Infância e verificação de idade": [r"\bcriancas?\b", r"\bchildren\b",
        r"\bmenores\b", r"\bminors\b", r"\badolescent", r"\bverificac[a-z]* de idade\b",
        r"\bage verification\b", r"\bchild safety\b"],
}
STOPWORDS = set("""sobre entre para pela pelos pelas como mais menos este esta estes estas
essa esse esses essas todos todas toda todo una uno unas unos para desde hasta hacia
with from that this these those about into when what will have been were being the
and are not por com sem que del los las uma das dos pelo da de do em no na nos nas
o a e y el la en un los news noticia noticias noticias sobre comunicado publica
publico publica official oficial brasileira brasileiro brazil brasil european union
europa uruguay uruguai argentina parliament parlamento congreso comision european
""".split())


def plain(text: object) -> str:
    return unicodedata.normalize("NFKD", str(text or "").lower()).encode("ascii", "ignore").decode("ascii")


def parse_date(raw: object) -> pd.Timestamp | pd.NaT:
    text = plain(raw).strip()
    if not text or text in {"nan", "none", "na", "nat"}:
        return pd.NaT
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if match:
        return pd.to_datetime(match.group(1), format="%Y-%m-%d", errors="coerce")
    match = re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b", text)
    if match:
        return pd.to_datetime(match.group(), dayfirst=True, errors="coerce")
    match = re.search(r"\b(\d{1,2})\s+(?:de\s+)?([a-z]+)\s+(?:de\s+)?(\d{4})\b", text)
    if match and match.group(2) in MONTHS:
        try:
            return pd.Timestamp(int(match.group(3)), MONTHS[match.group(2)], int(match.group(1)))
        except ValueError:
            return pd.NaT
    match = re.search(r"\b([a-z]+)\s+(\d{1,2}),?\s+(\d{4})\b", text)
    if match and match.group(1) in MONTHS:
        try:
            return pd.Timestamp(int(match.group(3)), MONTHS[match.group(1)], int(match.group(2)))
        except ValueError:
            return pd.NaT
    return pd.NaT


def canonical_url(value: object) -> str:
    try:
        parsed = urlsplit(str(value).strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        filtered = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                    if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
        path = parsed.path.rstrip("/") or "/"
        return urlunsplit(("https", parsed.netloc.lower(), path, urlencode(sorted(filtered)), ""))
    except (TypeError, ValueError):
        return ""


def list_drive_notebooks(service, folder_id: str = FOLDER_ID) -> tuple[list[dict], list[dict]]:
    """Read current notebook bytes; keep download failures visible in diagnostics."""
    notebooks, errors, token = [], [], None
    while True:
        response = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken,files(id,name,mimeType)", pageSize=1000,
            pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        for item in response.get("files", []):
            name = item.get("name", "")
            if not name.lower().endswith(".ipynb") or name == SELF_NAME:
                continue
            if name in ANALYSIS_NAMES:
                continue
            try:
                raw = service.files().get_media(fileId=item["id"], supportsAllDrives=True).execute()
                book = json.loads(raw)
                notebooks.append({"id": item["id"], "name": name, "book": book})
            except Exception as exc:
                errors.append({"notebook": name, "status": "download_failed", "error": str(exc)[:350]})
        token = response.get("nextPageToken")
        if not token:
            break
    return notebooks, errors


def prepare_collector(item: dict) -> dict:
    cells = [cell for cell in item["book"]["cells"] if cell["cell_type"] == "code"]
    if len(cells) < 2:
        raise ValueError("Notebook sem célula de coleta")
    code = "".join(cells[1]["source"])
    # dataclass checks __module__ in sys.modules while Record is defined.
    # Some collectors use json in a helper while importing it in the next cell.
    scope: dict = {"__name__": "__main__", "json": json}
    exec(compile(code, item["name"], "exec"), scope)
    source_id = scope.get("source_id")
    configs = scope.get("sources") or ([scope["cfg"]] if "cfg" in scope else [])
    if not source_id or not configs or not callable(scope.get("collect")):
        raise ValueError("source_id, cfg/sources ou collect() ausente")
    signature = tuple(sorted((c["url"], tuple(c.get("include", []))) for c in configs))
    return {"item": item, "scope": scope, "source_id": source_id,
            "configs": configs, "signature": signature}


def collect_one(prepared: dict, max_pages: int | None = None) -> tuple[list[dict], dict]:
    item = prepared["item"]
    scope = prepared["scope"]
    attempts: list[dict] = []
    final_rows: list[dict] = []
    active_cfg: dict = {}
    for original in prepared["configs"]:
        cfg = dict(original)
        if max_pages is not None:
            cfg["pages"] = min(max_pages, int(cfg.get("pages", 1)))
        try:
            rows, result = scope["collect"](prepared["source_id"], cfg, delay=0.25)
        except Exception as exc:
            rows, result = [], {"source": cfg.get("name", ""), "source_id": prepared["source_id"],
                                "status": "failed", "pages_ok": 0, "pages_requested": cfg.get("pages", 1),
                                "records": 0, "errors": [{"error": f"{type(exc).__name__}: {exc}"[:350]}]}
        if result.get("errors") and rows:
            result["status"] = "partial"
        if not result.get("pages_ok") and rows:
            result["status"] = "reference_only"
        attempts.append(result)
        if rows:
            final_rows, active_cfg = rows, cfg
            break
    references = {canonical_url(url) for _, url in active_cfg.get("static_links", [])}
    if final_rows and references and all(canonical_url(row.get("url")) in references for row in final_rows):
        attempts[-1]["status"] = "reference_only"
    elif final_rows and len(attempts) > 1:
        attempts[-1]["status"] = "fallback"
    for row in final_rows:
        row["origin_notebook"] = item["name"]
        row["origin"] = "Drive collector"
        row["reference_link"] = canonical_url(row.get("url")) in references
    last = attempts[-1] if attempts else {}
    report = {"notebook": item["name"], "source_id": prepared["source_id"],
              "source": last.get("source", ""), "status": last.get("status", "failed"),
              "records": len(final_rows), "pages_ok": last.get("pages_ok", 0),
              "pages_requested": last.get("pages_requested", 0), "attempts": attempts,
              "errors": [err for attempt in attempts for err in attempt.get("errors", [])]}
    return final_rows, report


def collect_drive(notebooks: list[dict], max_pages: int | None = None,
                  workers: int = 3) -> tuple[list[dict], list[dict]]:
    """Run distinct original collectors; keep duplicates and failures in the log."""
    prepared, diagnostics = [], []
    for item in notebooks:
        try:
            prepared.append(prepare_collector(item))
        except Exception as exc:
            diagnostics.append({"notebook": item["name"], "status": "invalid",
                                "records": 0, "error": f"{type(exc).__name__}: {exc}"[:350]})
    # The Commission-labeled Drive notebook currently points at the same EU
    # portal as ue_news. Prefer the direct portal label over a false publisher.
    def priority(p: dict):
        sid = p["source_id"]
        return (sid == "comissao_europeia", "- Ana" in p["item"]["name"], p["item"]["name"])
    unique, signatures = [], {}
    for p in sorted(prepared, key=priority):
        if p["signature"] in signatures:
            diagnostics.append({"notebook": p["item"]["name"], "source_id": p["source_id"],
                                "status": "duplicate_source", "records": 0,
                                "same_listing_as": signatures[p["signature"]]})
            continue
        signatures[p["signature"]] = p["item"]["name"]
        unique.append(p)
    rows = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 4))) as executor:
        futures = {executor.submit(collect_one, p, max_pages): p for p in unique}
        for future in as_completed(futures):
            p = futures[future]
            try:
                found, report = future.result()
                rows.extend(found)
                diagnostics.append(report)
                print(f"{report['status'].upper():<15} {p['item']['name']}: {len(found)} registros")
            except Exception as exc:
                diagnostics.append({"notebook": p["item"]["name"], "source_id": p["source_id"],
                                    "status": "failed", "records": 0,
                                    "error": f"{type(exc).__name__}: {exc}"[:350]})
                print(f"FALHA {p['item']['name']}: {exc}")
    return rows, sorted(diagnostics, key=lambda d: d["notebook"])


def weekly_rows(csv_bytes: bytes) -> list[dict]:
    table = pd.read_csv(BytesIO(csv_bytes), dtype=str, keep_default_na=False)
    required = {"source_id", "title", "url", "published_date"}
    if not required.issubset(table.columns):
        raise ValueError(f"CSV semanal sem colunas: {sorted(required - set(table.columns))}")
    rows = table.to_dict("records")
    for row in rows:
        row["date"] = row["published_date"] or row.get("published_raw", "")
        row["origin"] = "GitHub weekly"
        row["origin_notebook"] = "workflow semanal"
        row["reference_link"] = False
    return rows


def session_csv_rows(directory: Path) -> list[dict]:
    """Optionally ingest outputs produced by original Colabs in this session."""
    rows = []
    for path in sorted(directory.glob("*.csv")):
        if path.name in {"news.csv", "noticias_unificadas.csv", "parlamento_uy_analise.csv"}:
            continue
        try:
            table = pd.read_csv(path, dtype=str, keep_default_na=False)
            if not {"source_id", "title", "url"}.issubset(table.columns):
                continue
            for row in table.to_dict("records"):
                row["origin"] = "CSV da sessão"
                row["origin_notebook"] = path.name
                rows.append(row)
        except (OSError, ValueError):
            continue
    return rows


def normalize_records(records: list[dict]) -> tuple[pd.DataFrame, dict]:
    columns = ["source_id", "source", "country", "region", "institution", "record_type",
               "title", "published_date", "raw_date", "url", "summary", "origins", "notebooks"]
    cleaned = []
    for row in records:
        url = canonical_url(row.get("url", ""))
        title = re.sub(r"\s+", " ", str(row.get("title", ""))).strip()
        if not url or not title:
            continue
        sid = str(row.get("source_id", "unknown"))
        country, region, institution = SOURCE_META.get(sid, ("Outra", "Outra", sid))
        raw_date = row.get("published_date") or row.get("date") or row.get("published_raw") or ""
        published = parse_date(raw_date)
        source = str(row.get("source") or institution)
        if sid == "comissao_europeia" and urlsplit(url).hostname == "european-union.europa.eu":
            source = "Portal da União Europeia (configurado como Comissão)"
        if row.get("reference_link"):
            record_type = "Referência institucional"
        elif "biblioteca.parlamento.gub.uy/eventos/" in url:
            record_type = "Evento da Biblioteca"
        elif sid in {"dsa_transparency", "meta_transparency", "google_transparency", "impo_uruguay"}:
            record_type = "Página institucional"
        elif pd.isna(published):
            record_type = "Registro sem data"
        else:
            record_type = "Notícia/comunicado"
        cleaned.append({"source_id": sid, "source": source, "country": country,
                        "region": region, "institution": institution, "record_type": record_type,
                        "title": title, "published_date": published, "raw_date": str(raw_date),
                        "url": url, "summary": str(row.get("summary") or ""),
                        "origin": str(row.get("origin") or ""),
                        "notebook": str(row.get("origin_notebook") or "")})
    if not cleaned:
        return pd.DataFrame(columns=columns), {"input_records": len(records), "valid": 0, "duplicates": 0}
    working = pd.DataFrame(cleaned)
    working["score"] = (working["published_date"].notna().astype(int) * 100
                        + working["summary"].str.len().clip(upper=100).div(10)
                        + working["origin"].eq("GitHub weekly").astype(int) * 2)
    chosen = working.sort_values("score", ascending=False).drop_duplicates("url").copy()
    origins = working.groupby("url").agg(
        origins=("origin", lambda s: ", ".join(sorted(set(filter(None, s))))),
        notebooks=("notebook", lambda s: ", ".join(sorted(set(filter(None, s)))))
    )
    chosen = chosen.drop(columns=["origin", "notebook", "score"]).join(origins, on="url")
    chosen = chosen.sort_values("published_date", ascending=False, na_position="last").reset_index(drop=True)
    chosen["published_date"] = pd.to_datetime(chosen["published_date"], errors="coerce")
    return chosen[columns], {"input_records": len(records), "valid": len(cleaned),
                             "unique": len(chosen), "duplicates": len(cleaned) - len(chosen)}


def matched_topics(title: object) -> list[str]:
    text = plain(title)
    return [topic for topic, patterns in TOPICS.items()
            if any(re.search(pattern, text) for pattern in patterns)]


def terms(title: object) -> set[str]:
    return {word for word in re.findall(r"[a-z]{4,}", plain(title))
            if word not in STOPWORDS}


def topic_evidence(data: pd.DataFrame) -> pd.DataFrame:
    rows = [{"tema": topic, "fonte": record.source, "país": record.country,
             "data": record.published_date, "título": record.title, "url": record.url}
            for record in data.itertuples(index=False)
            for topic in matched_topics(record.title)]
    return pd.DataFrame(rows, columns=["tema", "fonte", "país", "data", "título", "url"])


def keyword_counts(data: pd.DataFrame, top: int = 30) -> pd.DataFrame:
    counts = Counter(word for title in data["title"] for word in terms(title))
    return pd.DataFrame(counts.most_common(top), columns=["termo", "títulos"])


def source_health(data: pd.DataFrame, diagnostics: list[dict]) -> pd.DataFrame:
    counts = data.groupby("source_id").agg(
        registros=("url", "size"), datados=("published_date", "count"),
        ultima_data=("published_date", "max")
    ) if not data.empty else pd.DataFrame(columns=["registros", "datados", "ultima_data"])
    rows = []
    for d in diagnostics:
        sid = d.get("source_id")
        item = counts.loc[sid] if sid in counts.index else None
        n = int(item["registros"]) if item is not None else 0
        dated = int(item["datados"]) if item is not None else 0
        rows.append({"notebook": d.get("notebook"), "source_id": sid,
                     "status": d.get("status"), "coletados_nesta_rodada": d.get("records", 0),
                     "registros_unicos": n,
                     "datas_%": round(100 * dated / n, 1) if n else 0,
                     "ultima_publicacao": str(item["ultima_data"].date()) if item is not None and pd.notna(item["ultima_data"]) else "—",
                     "paginas": f"{d.get('pages_ok', 0)}/{d.get('pages_requested', 0)}",
                     "erros": len(d.get("errors", [])) + bool(d.get("error"))})
    return pd.DataFrame(rows).sort_values(["status", "notebook"]) if rows else pd.DataFrame()


def build_dashboard(data: pd.DataFrame, diagnostics: list[dict], *,
                    days: int | None = 365, countries: list[str] | None = None,
                    source_ids: list[str] | None = None,
                    include_other_types: bool = False, query: str = "") -> dict:
    """Return figures, evidence and rule-based observations for a selected view."""
    selected = data.copy()
    if not include_other_types:
        selected = selected[selected["record_type"] == "Notícia/comunicado"]
    today = pd.Timestamp.now(tz="America/Sao_Paulo").date()
    if days is not None:
        start = pd.Timestamp(today - timedelta(days=days - 1))
        mask = selected["published_date"].ge(start)
        if include_other_types:
            mask |= selected["published_date"].isna()
        selected = selected[mask]
    if countries:
        selected = selected[selected["country"].isin(countries)]
    if source_ids:
        selected = selected[selected["source_id"].isin(source_ids)]
    if query.strip():
        selected = selected[selected["title"].map(plain).str.contains(plain(query.strip()), regex=False)]
    selected = selected.copy()
    evidence = topic_evidence(selected)
    keywords = keyword_counts(selected)
    health = source_health(data, diagnostics)
    n = len(selected)
    topics = (evidence.groupby("tema").size().reindex(TOPICS, fill_value=0)
              .rename("títulos").reset_index().rename(columns={"index": "tema"}))
    topics["% dos títulos"] = (topics["títulos"] * 100 / n).round(1) if n else 0.0
    regional_rows = []
    for region, subset in selected.groupby("region"):
        for topic in TOPICS:
            hits = sum(topic in matched_topics(title) for title in subset["title"])
            regional_rows.append({"região": region, "tema": topic, "títulos": hits,
                                  "total": len(subset), "% dos títulos": round(100 * hits / len(subset), 1),
                                  "amostra pequena": len(subset) < 10})
    regional = pd.DataFrame(regional_rows, columns=["região", "tema", "títulos", "total",
                                                   "% dos títulos", "amostra pequena"])
    recent = selected.sort_values("published_date", ascending=False).head(40)
    figures = []
    if n:
        by_source = (selected.groupby(["source", "country"]).size().reset_index(name="registros")
                     .sort_values("registros", ascending=False).head(20))
        figures.append(px.bar(by_source, x="registros", y="source", color="country", orientation="h",
                              title="Registros por fonte (amostra filtrada)",
                              labels={"registros": "Registros", "source": "Fonte", "country": "País da fonte"}))
        dated = selected.dropna(subset=["published_date"]).copy()
        if not dated.empty:
            dated["mês"] = dated["published_date"].dt.to_period("M").dt.to_timestamp()
            monthly = dated.groupby(["mês", "region"]).size().reset_index(name="registros")
            figures.append(px.line(monthly, x="mês", y="registros", color="region", markers=True,
                                   title="Publicações coletadas por mês e região",
                                   labels={"region": "Região", "registros": "Registros"}))
        figures.append(px.bar(topics, x="tema", y="% dos títulos", text="títulos",
                              title="Temas mencionados nos títulos (% da amostra)",
                              labels={"tema": "Tema"}))
        if not keywords.empty:
            figures.append(px.bar(keywords.sort_values("títulos"), x="títulos", y="termo",
                                  orientation="h", title="Termos mais frequentes nos títulos",
                                  labels={"títulos": "Títulos com o termo", "termo": "Termo"}))
        groups = selected.groupby("country").size()
        eligible = groups[groups >= 5].index.tolist()
        if eligible:
            grid = []
            for country in eligible:
                subset = selected[selected["country"] == country]
                for topic in TOPICS:
                    matching = sum(topic in matched_topics(title) for title in subset["title"])
                    grid.append({"país": f"{country} (n={len(subset)})", "tema": topic,
                                 "% títulos": round(100 * matching / len(subset), 1)})
            matrix = pd.DataFrame(grid).pivot(index="país", columns="tema", values="% títulos")
            figures.append(px.imshow(matrix, text_auto=".1f", aspect="auto", color_continuous_scale="Blues",
                                     title="Prevalência temática por país da fonte (%)"))
            top_terms = keywords.head(10)["termo"].tolist()
            if top_terms:
                word_grid = []
                for country in eligible:
                    subset = selected[selected["country"] == country]
                    token_sets = [terms(title) for title in subset["title"]]
                    for word in top_terms:
                        word_grid.append({"país": f"{country} (n={len(subset)})", "termo": word,
                                          "% títulos": round(100 * sum(word in tokens for tokens in token_sets) / len(subset), 1)})
                word_matrix = pd.DataFrame(word_grid).pivot(index="país", columns="termo", values="% títulos")
                figures.append(px.imshow(word_matrix, text_auto=".1f", aspect="auto", color_continuous_scale="Teal",
                                         title="Palavras-chave por país da fonte (% de títulos)"))
        if not evidence.empty:
            co = pd.DataFrame(0, index=list(TOPICS), columns=list(TOPICS))
            for title in selected["title"]:
                found = matched_topics(title)
                for a in found:
                    for b in found:
                        co.loc[a, b] += 1
            figures.append(px.imshow(co, text_auto=True, aspect="auto", color_continuous_scale="Purples",
                                     title="Títulos que mencionam cada par de temas"))
    for fig in figures:
        fig.update_layout(template="plotly_white", height=430, margin=dict(l=30, r=25, t=70, b=45))
    failed = [d for d in diagnostics if d.get("status") in {"failed", "empty", "invalid", "download_failed", "list_failed", "access_failed", "partial", "reference_only", "fallback"}]
    observations = [f"Amostra exibida: {n} registros; {selected['published_date'].notna().sum()} com data reconhecida."]
    if failed:
        observations.append(f"{len(failed)} fontes com falha, cobertura parcial ou apenas links de referência; consulte a tabela de saúde.")
    duplicated_listings = [d for d in diagnostics if d.get("status") == "duplicate_source"]
    if duplicated_listings:
        observations.append(f"{len(duplicated_listings)} notebooks apontam para listagens já coletadas; não foram contados como fontes independentes.")
    if n:
        top = topics.sort_values("títulos", ascending=False).iloc[0]
        observations.append(f"Tema mais frequente nos títulos: {top['tema']} ({int(top['títulos'])}/{n}, {top['% dos títulos']}%).")
    if not regional.empty:
        pairs = regional[regional["região"].isin(["Mercosul", "UE"])].pivot(
            index="tema", columns="região", values="% dos títulos")
        sample_sizes = selected.groupby("region").size()
        if {"Mercosul", "UE"}.issubset(pairs.columns) and min(
            sample_sizes.get("Mercosul", 0), sample_sizes.get("UE", 0)) >= 10:
            difference = (pairs["Mercosul"] - pairs["UE"]).abs().sort_values(ascending=False)
            if not difference.empty:
                topic = difference.index[0]
                observations.append(
                    f"Maior diferença temática observada entre Mercosul e UE: {topic} "
                    f"({pairs.loc[topic, 'Mercosul']:.1f}% de {sample_sizes['Mercosul']} títulos "
                    f"vs. {pairs.loc[topic, 'UE']:.1f}% de {sample_sizes['UE']}).")
    publication_days = selected["published_date"].dt.date
    recent_week = selected[publication_days.between(today - timedelta(days=6), today)]
    previous = selected[publication_days.between(today - timedelta(days=34), today - timedelta(days=7))]
    current_terms = Counter(word for title in recent_week["title"] for word in terms(title))
    prior_terms = Counter(word for title in previous["title"] for word in terms(title))
    candidates = [(word, count, prior_terms[word]) for word, count in current_terms.items()
                  if count >= 3 and (count / max(len(recent_week), 1)) >= 1.5 *
                  (prior_terms[word] / max(len(previous), 1))]
    if candidates:
        rising = ", ".join(word for word, _, _ in sorted(candidates, key=lambda x: -x[1])[:5])
        observations.append(f"Termos mais presentes na última semana em relação às quatro anteriores: {rising} (apenas na amostra coletada).")
    observations.append("Comparações usam títulos e datas de publicação disponíveis; não medem toda a atividade institucional nem o conteúdo integral dos textos.")
    return {"selected": selected, "evidence": evidence, "keywords": keywords,
            "topics": topics, "regional": regional, "health": health, "recent": recent,
            "figures": figures, "observations": observations}


def export_results(data: pd.DataFrame, diagnostics: list[dict], dashboard: dict,
                   output: Path, quality: dict, *, embed_plotly_js: bool = True) -> dict[str, Path]:
    output.mkdir(parents=True, exist_ok=True)
    paths = {name: output / name for name in (
        "noticias_unificadas.csv", "evidencias_tematicas.csv", "comparacao_regional.csv", "saude_fontes.csv",
        "diagnostico.json", "painel_fapesp.html")}
    csv = data.copy()
    csv["published_date"] = csv["published_date"].dt.strftime("%Y-%m-%d").fillna("")
    csv.to_csv(paths["noticias_unificadas.csv"], index=False)
    ev = dashboard["evidence"].copy()
    if not ev.empty:
        ev["data"] = ev["data"].dt.strftime("%Y-%m-%d").fillna("")
    ev.to_csv(paths["evidencias_tematicas.csv"], index=False)
    dashboard["regional"].to_csv(paths["comparacao_regional.csv"], index=False)
    dashboard["health"].to_csv(paths["saude_fontes.csv"], index=False)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "quality": quality,
               "sources": diagnostics, "scope": "Coletas acessíveis nesta execução; títulos e links, sem inferência de conteúdo integral."}
    paths["diagnostico.json"].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    parts = ["<!doctype html><html lang='pt-BR'><meta charset='utf-8'>",
             "<title>Agente FAPESP — painel de notícias</title>",
             "<style>body{font:16px system-ui;max-width:1200px;margin:32px auto;padding:0 16px;color:#182439}h1{color:#153a69}table{border-collapse:collapse;width:100%}td,th{padding:6px;border-bottom:1px solid #ddd;text-align:left}small{color:#556}</style>",
             "<h1>Agente FAPESP — painel de notícias</h1>",
             f"<p><small>Gerado em {escape(datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC'))}. Filtro inicial do notebook; abra o Colab para alterar os filtros.</small></p>",
             "<h2>Leituras automáticas da amostra</h2><ul>"]
    parts.extend(f"<li>{escape(message)}</li>" for message in dashboard["observations"])
    parts.append("</ul><h2>Saúde das fontes</h2>")
    parts.append(dashboard["health"].to_html(index=False, escape=True) if not dashboard["health"].empty else "<p>Sem diagnóstico de fontes.</p>")
    for index, fig in enumerate(dashboard["figures"]):
        parts.append(fig.to_html(full_html=False, include_plotlyjs=(True if embed_plotly_js else "cdn") if index == 0 else False))
    parts.append("<h2>Registros recentes da amostra</h2>")
    recent = dashboard["recent"][["published_date", "title", "country", "source", "record_type", "url"]].copy()
    if not recent.empty:
        recent["published_date"] = recent["published_date"].dt.strftime("%Y-%m-%d").fillna("")
    parts.append(recent.to_html(index=False, escape=True))
    parts.append("<p><small>Eventos, referências e dados sem data ficam separados. O CSV contém os links e a proveniência integral.</small></p></html>")
    paths["painel_fapesp.html"].write_text("\n".join(parts), encoding="utf-8")
    return paths
