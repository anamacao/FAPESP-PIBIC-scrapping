"""Public-source collection with article dates and visible coverage diagnostics.

This registry covers the institutions in the original notebooks. It does not
execute setup, browser, database or plotting cells in legacy notebooks.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Country and scope describe the publisher, never the subject of an article.
SOURCES = {
    "nic": ("NIC.br", "Brasil", "Mercosul", "https://www.nic.br/noticias/indice/todos/indice-1.json", "nic"),
    "dataprivacy": ("Data Privacy Brasil", "Brasil", "Mercosul", "https://www.dataprivacybr.org/wp-json/wp/v2/posts", "wp"),
    "mercociudades": ("Mercociudades", "Regional", "Mercosul", "https://mercociudades.org/wp-json/wp/v2/posts", "wp"),
    "observacom": ("OBSERVACOM", "Regional", "América Latina", "https://www.observacom.org/wp-json/wp/v2/posts", "wp"),
    "internetlab": ("InternetLab", "Brasil", "Mercosul", "https://internetlab.org.br/wp-json/wp/v2/posts", "wp"),
    "mitic_paraguai": ("MITIC Paraguai", "Paraguai", "Mercosul", "https://mitic.gov.py/wp-json/wp/v2/posts", "wp"),
    "edpb": ("European Data Protection Board", "União Europeia", "UE", "https://www.edpb.europa.eu/news_en", "html"),
    "anpd": ("Autoridade Nacional de Proteção de Dados", "Brasil", "Mercosul", "https://www.gov.br/anpd/++api++/pt-br/assuntos/noticias/@search", "plone"),
    "agesic": ("AGESIC Uruguai", "Uruguai", "Mercosul", "https://www.gub.uy/agencia-gobierno-electronico-sociedad-informacion-conocimiento/comunicacion/noticias", "html"),
    "urcdp": ("URCDP Uruguai", "Uruguai", "Mercosul", "https://www.gub.uy/unidad-reguladora-control-datos-personales/comunicacion/noticias", "html"),
    "aaip": ("AAIP Argentina", "Argentina", "Mercosul", "https://www.argentina.gob.ar/aaip/noticias", "html"),
    "camara_federal": ("Câmara dos Deputados", "Brasil", "Mercosul", "https://www.camara.leg.br/noticias/noticias-institucionais", "html"),
    "cgi": ("CGI.br", "Brasil", "Mercosul", "https://cgi.br/noticias/indice/", "html"),
    "senado_federal": ("Agência Senado", "Brasil", "Mercosul", "https://www12.senado.leg.br/noticias/ultimas", "html"),
    "icn_argentina": ("ICN Congreso Argentina", "Argentina", "Mercosul", "https://icn.gob.ar/noticias", "html"),
    "icann": ("ICANN", "Global", "Global", "https://www.icann.org/en/announcements", "html"),
    "ue_news": ("União Europeia", "União Europeia", "UE", "https://european-union.europa.eu/news-and-events/news-and-stories_en", "html"),
    "parlamento_uy": ("Parlamento do Uruguai", "Uruguai", "Mercosul", "https://parlamento.gub.uy/noticiasyeventos/noticias", "html"),
    "google_transparency": ("Google Transparency", "Global", "Global", "https://transparency.google/accountability/", "reference"),
    "meta_transparency": ("Meta Transparency Center", "Global", "Global", "https://transparency.meta.com/reports/", "reference"),
    "dsa_transparency": ("DSA Transparency Database", "União Europeia", "UE", "https://transparency.dsa.ec.europa.eu/", "reference"),
}


def canonical(value):
    try:
        u = urlsplit(str(value))
        if u.scheme not in {"http", "https"} or not u.hostname:
            return ""
        query = [(k, v) for k, v in parse_qsl(u.query) if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
        return urlunsplit((u.scheme, u.netloc.lower(), u.path.rstrip("/") or "/", urlencode(sorted(query)), ""))
    except ValueError:
        return ""


def text(value):
    return re.sub(r"\s+", " ", BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)).strip()


def date_iso(raw):
    abbreviations = {"jan":"janeiro","fev":"fevereiro","mar":"marco","abr":"abril","mai":"maio","jun":"junho","jul":"julho","ago":"agosto","set":"setembro","out":"outubro","nov":"novembro","dez":"dezembro"}
    abbreviated = re.fullmatch(r"\s*(\d{1,2})\s+([a-zA-Z]{3})\s+(\d{4})\s*", str(raw or ""))
    if abbreviated and abbreviated[2].lower() in abbreviations:
        raw = f"{abbreviated[1]} de {abbreviations[abbreviated[2].lower()]} de {abbreviated[3]}"
    # ISO timestamps have no word boundary between the day and the letter T.
    match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:T|\s|$)", str(raw or ""))
    if match:
        try:
            return datetime.strptime(match[1], "%Y-%m-%d").date().isoformat()
        except ValueError:
            return ""
    from fapesp_agent import parse_date
    parsed = parse_date(raw)
    return "" if str(parsed) == "NaT" else parsed.date().isoformat()


def client():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; FAPESP research monitor; +https://github.com/anamacao/FAPESP-PIBIC-scrapping)"})
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=1, backoff_factor=.4, status_forcelist=[429, 500, 502, 503, 504])))
    return s


def fetch(s, url, **kwargs):
    response = s.get(url, timeout=20, **kwargs)
    response.raise_for_status()
    if response.encoding and response.encoding.lower() in {"iso-8859-1", "latin-1"}:
        try:
            response.content.decode("utf-8")
            response.encoding = "utf-8"
        except UnicodeDecodeError:
            pass
    return response


def record(sid, title, date, url, summary="", category="", record_type=""):
    name, country, region, _, _ = SOURCES[sid]
    return {"source_id": sid, "source": name, "country": country, "region": region,
            "title": text(title), "published_date": date_iso(date), "raw_date": str(date or ""),
            "url": canonical(url), "summary": text(summary), "category": category,
            "record_type": record_type or (("Publicação institucional" if sid == "dataprivacy" else "Notícia/comunicado") if date_iso(date) else "Registro sem data"),
            "origin": "Coleta pública GitHub", "origin_notebook": "registro de coletores",
            "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def wp(s, sid, endpoint, pages, report):
    rows, total_pages = [], None
    for page in range(1, pages + 1):
        if total_pages and page > total_pages:
            break
        try:
            r = fetch(s, endpoint, params={"per_page": 100, "page": page, "orderby": "date", "order": "desc",
                      "_fields": "id,date,link,title,excerpt,categories"})
        except requests.RequestException as exc:
            if not rows:
                raise
            report["errors"].append(f"Página {page} não coletada: {exc}"[:250])
            break
        items = r.json()
        if not isinstance(items, list):
            raise ValueError("API não retornou lista de publicações")
        total_pages = int(r.headers.get("X-WP-TotalPages", "0")) or None
        report.update(site_total_pages=total_pages, site_total_records=r.headers.get("X-WP-Total"))
        report["pages_ok"] += 1
        for item in items:
            rows.append(record(sid, item.get("title", {}).get("rendered"), item.get("date"), item.get("link"),
                               item.get("excerpt", {}).get("rendered"), " | ".join(map(str, item.get("categories", [])))))
        report["coverage"] = "Todas as páginas informadas pela API" if total_pages and page >= total_pages else "Recorte paginado da API; histórico completo não confirmado"
        if not items:
            break
        time.sleep(.2)
    return rows


def rss(s, sid, url, report):
    root = ET.fromstring(fetch(s, url).text)
    report["pages_ok"] += 1
    rows = []
    for item in root.findall("./channel/item"):
        raw = item.findtext("pubDate", "")
        try:
            day = parsedate_to_datetime(raw).date().isoformat()
        except (ValueError, TypeError):
            day = ""
        rows.append(record(sid, item.findtext("title"), day, item.findtext("link"), item.findtext("description")))
    report.update(method="RSS oficial", coverage="Últimos itens do feed; não representa todo o histórico")
    return rows


def plone(s, sid, endpoint, pages, report):
    rows=[]
    for page in range(pages):
        try:
            data=fetch(s, endpoint, headers={"Accept":"application/json"}, params={"portal_type":"News Item",
                "sort_on":"effective", "sort_order":"descending", "b_size":100, "b_start":page*100,
                "metadata_fields":["effective","description"]}).json()
        except (requests.RequestException, ValueError) as exc:
            if not rows:
                raise
            report["errors"].append(f"Página {page+1}: {exc}"[:250]);break
        items=data.get("items",[])
        report["pages_ok"]+=1
        total=data.get("items_total",len(items));report["site_total_records"]=total
        for item in items:
            rows.append(record(sid,item.get("title"),item.get("effective"),str(item.get("@id","")).replace("/++api++/","/"),item.get("description")))
        if not data.get("batching",{}).get("next") or not items:
            break
    report["coverage"]="API pública Plone, ordenada por publicação; até 100 itens por página"
    if report.get("site_total_records",0)>len(rows):
        report["warnings"].append("Limite de páginas atingido; o histórico da API não foi coletado por completo")
    return rows


def metadata_date(soup):
    for selector, attr in [('meta[property="article:published_time"]', "content"),
                           ('meta[name="date"]', "content"), ('meta[name="DC.date.issued"]', "content"),
                           ('meta[itemprop="datePublished"]', "content"), ('time[datetime]', "datetime")]:
        for el in soup.select(selector):
            day = date_iso(el.get(attr))
            if day:
                return day
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        def find(value):
            if isinstance(value, dict):
                day = date_iso(value.get("datePublished"))
                if day:
                    return day
                for child in value.values():
                    if isinstance(child, (dict, list)) and (day := find(child)):
                        return day
            if isinstance(value, list):
                for child in value:
                    if day := find(child):
                        return day
            return ""
        if day := find(data):
            return day
    for el in soup.select(".documentPublished, .documentByLine, .fecha, .Article-date, .published, .entry-date, .date-display-single, .date-post, time"):
        if day := date_iso(el.get_text(" ", strip=True)):
            return day
    return ""


def listing(s, sid, endpoint, report, details=12):
    soup = BeautifulSoup(fetch(s, endpoint).text, "html.parser")
    report["pages_ok"] += 1
    # Some portals expose an empty main shell while the listing lives outside it.
    body = soup
    if sid == "icn_argentina":
        rows = []
        for panel in body.select(".panel[data-slug]"):
            heading, date = panel.select_one("h4,h3,h2"), panel.select_one("time")
            if heading:
                rows.append(record(sid, heading.get_text(" ", strip=True), date.get_text(" ", strip=True) if date else "", urljoin(endpoint + "/", panel["data-slug"])))
        report["coverage"] = "Notícias da listagem oficial, com data e identificador de artigo"
        return rows
    patterns = {
        "edpb": "/news/", "anpd": "/noticias/", "agesic": "/comunicacion/noticias/",
        "urcdp": "/comunicacion/noticias/", "aaip": "/noticias/", "camara_federal": "/assessoria-de-imprensa/",
        "cgi": "/noticia/", "senado_federal": "/noticias/materias/", "icn_argentina": "/noticias/",
        "icann": "/announcements/details/", "ue_news": "/news-and-events/news-and-stories/",
        "parlamento_uy": "/noticiasyeventos/noticias/"}
    rows, seen, remaining = [], set(), details
    host = urlsplit(endpoint).hostname.removeprefix("www.")
    for a in body.select("a[href]"):
        url = canonical(urljoin(endpoint, a["href"]))
        u = urlsplit(url)
        external_eu = sid == "ue_news" and u.hostname and u.hostname.endswith(".europa.eu") and any(p in u.path for p in ["/news-and-media/news/", "/en/news/", "/news/en/press-room/", "/presscorner/detail/"])
        if not u.hostname or (not external_eu and (u.hostname.removeprefix("www.") != host or patterns[sid] not in u.path)):
            continue
        title = a.get_text(" ", strip=True)
        parent = a.find_parent(class_=re.compile(r"node-article-card__content|views-row|item-noticia|box-noticia", re.I)) or a.find_parent(["article", "li"]) or a.find_parent(class_=re.compile(r"card|tile|news|noticia|Box", re.I)) or a.parent
        if not title:
            heading = parent.select_one("h2,h3,h4,.titulo")
            title = heading.get_text(" ", strip=True) if heading else ""
        if len(title) < 18 or url in seen or url == canonical(endpoint):
            continue
        seen.add(url)
        day = metadata_date(parent)
        if not day:
            day = date_iso(parent.get_text(" ", strip=True))
        summary = ""
        if not day and remaining:
            remaining -= 1
            try:
                article = BeautifulSoup(fetch(s, url).text, "html.parser")
                day = metadata_date(article)
                heading = article.select_one("main h1, #content h1, h1.entry-title, h1.documentFirstHeading")
                if heading:
                    title = heading.get_text(" ", strip=True)
                description = article.select_one('meta[name="description"], meta[property="og:description"]')
                summary = description.get("content", "") if description else ""
                report["detail_pages_ok"] += 1
                time.sleep(.12)
            except (requests.RequestException, ValueError) as exc:
                report["warnings"].append("Artigo sem metadados acessíveis: " + url + " — " + str(exc)[:90])
        rows.append(record(sid, title, day, url, summary))
        if len(rows) >= 100:
            break
    report["coverage"] = "Primeira listagem; até 12 artigos sem data conferidos individualmente"
    return rows


def collect_source(sid, pages=10):
    name, country, region, endpoint, method = SOURCES[sid]
    report = {"source_id": sid, "source": name, "country": country, "region": region, "endpoint": endpoint,
              "method": method, "pages_ok": 0, "detail_pages_ok": 0, "warnings": [], "errors": [],
              "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    s = client()
    rows = []
    try:
        if method == "wp":
            try:
                rows = wp(s, sid, endpoint, pages, report)
                report["method"] = "API pública WordPress"
            except (requests.RequestException, ValueError) as exc:
                report["warnings"].append("API indisponível: " + str(exc)[:180])
                feed = urlunsplit((*urlsplit(endpoint)[:2], "/feed/", "", ""))
                rows = rss(s, sid, feed, report)
        elif method == "plone":
            rows = plone(s, sid, endpoint, pages, report)
        elif method == "nic":
            items = fetch(s, endpoint).json()
            if not isinstance(items, list):
                raise ValueError("Índice NIC.br inválido")
            rows = [record(sid, x.get("titulo"), x.get("data"), urljoin(endpoint, x.get("permalink", ""))) for x in items[:600]]
            report.update(pages_ok=1, coverage="Até 600 itens do índice oficial; não representa todo o histórico")
        elif method == "reference":
            soup = BeautifulSoup(fetch(s, endpoint).text, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else name
            rows = [record(sid, title, "", endpoint, record_type="Página institucional")]
            report.update(pages_ok=1, coverage="Página institucional acessível; nenhuma coleta de notícias confirmada")
        else:
            rows = listing(s, sid, endpoint, report)
        rows = [r for r in rows if r["title"] and r["url"]]
        rows = list({r["url"]: r for r in rows}.values())
        dated = sum(bool(r["published_date"]) for r in rows)
        incomplete = bool(report["errors"]) or bool(report.get("site_total_pages") and report["site_total_pages"] > pages) or bool(report.get("site_total_records") and int(report["site_total_records"]) > len(rows))
        report.update(records=len(rows), dated=dated, undated=len(rows)-dated,
                      status="reference_only" if method == "reference" else "ok" if dated and dated == len(rows) and not incomplete else "partial" if rows else "empty")
    except (requests.RequestException, ValueError, TypeError, KeyError, ET.ParseError) as exc:
        report.update(status="failed", records=len(rows), dated=sum(bool(r["published_date"]) for r in rows), undated=sum(not r["published_date"] for r in rows))
        report["errors"].append(f"{type(exc).__name__}: {exc}"[:300])
        report["coverage"] = "Coleta não confirmada nesta rodada; manter o histórico anterior"
    finally:
        s.close()
    return rows, report


def collect_all(pages=10, workers=4):
    rows, reports = [], []
    with ThreadPoolExecutor(max_workers=min(4, max(1, workers))) as pool:
        futures = {pool.submit(collect_source, sid, pages): sid for sid in SOURCES}
        for future in as_completed(futures):
            found, report = future.result()
            rows.extend(found)
            reports.append(report)
            print(f"{report['source_id']}: {report['status']} — {len(found)} registros, {report['dated']} datados", flush=True)
    return rows, sorted(reports, key=lambda r: r["source"])


def main():
    import argparse
    import csv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1]/"data/unified")
    parser.add_argument("--pages", type=int, default=10)
    args = parser.parse_args()
    rows, reports = collect_all(args.pages)
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "public_records.csv"
    existing = list(csv.DictReader(path.open(encoding="utf-8-sig"))) if path.exists() else []
    merged = {canonical(r["url"]): r for r in existing}
    for row in rows:
        old = merged.get(row["url"], {})
        if old.get("published_date") and not row.get("published_date"):
            continue
        merged[row["url"]] = row
    fields = list(record("nic", "", "", ""))
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(merged.values())
    diagnostic = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "sources": reports, "total_records": len(merged), "preservation": "Falhas não apagam registros históricos"}
    (args.output/"diagnostico.json").write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
