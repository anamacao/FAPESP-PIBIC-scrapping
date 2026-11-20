"""Meaningful coverage checks for public APIs, dates and legacy integration."""
import json
from pathlib import Path
from unittest import TestCase, mock
import requests
import tempfile

from scripts.fapesp_agent import parse_date, prepare_collector, normalize_records, build_dashboard, export_results
from scripts.source_collectors import SOURCES, date_iso, metadata_date, listing, wp, record, repair_encoding, text, parliament_news, internetlab_sitemap, internetlab_html, icn_news, merge_public_records
from bs4 import BeautifulSoup


class Response:
    def __init__(self, data=None, body="", headers=None):
        self._data=data;self.text=body;self.headers=headers or {};self.encoding="utf-8";self.content=body.encode()
    def json(self):return self._data
    def raise_for_status(self):pass


class SourceCollectorTests(TestCase):
    def test_observacom_rejects_verified_spam_author_and_prunes_history(self):
        spam = {"id": 1, "author": 23, "title": {"rendered": "Casino promotion"},
                "date": "2026-11-16T08:00:00", "link": "https://www.observacom.org/casino-promotion"}
        article = {"id": 2, "author": 11, "title": {"rendered": "Regulación de plataformas digitales"},
                   "date": "2026-11-16T09:00:00", "link": "https://www.observacom.org/regulacion-plataformas"}
        validation = Response([{"id": 1, "author": 23, "link": spam["link"]}],
                              headers={"X-WP-TotalPages": "1"})
        listing_page = Response([spam, article], headers={"X-WP-TotalPages": "1", "X-WP-Total": "2"})
        s = mock.Mock(); s.get.side_effect = [validation, listing_page]
        report = {"pages_ok": 0, "errors": [], "warnings": []}

        rows = wp(s, "observacom", SOURCES["observacom"][3], 1, report)
        old_spam = record("observacom", "Casino promotion", "2026-11-12", "https://www.observacom.org/old-casino")
        old_spam["category"] = "1"
        valid_history = record("observacom", "Integridad electoral", "2026-11-11", "https://www.observacom.org/integridad-electoral")
        valid_history["category"] = "279"
        stale_aaip = record(
            "aaip",
            "13 de abril de 2026 La AAIP investiga protección de datos",
            "2026-11-12",
            "https://www.argentina.gob.ar/noticias/investigacion-aaip",
        )
        observacom_report = {"source_id": "observacom", **report}
        aaip_report = {"source_id": "aaip", "warnings": []}
        merged = merge_public_records([
            record("observacom", "Casino promotion", "2026-11-16", spam["link"]),
            old_spam,
            valid_history,
            stale_aaip,
        ], rows, [observacom_report, aaip_report])

        self.assertEqual([row["title"] for row in rows], ["Regulación de plataformas digitales"])
        self.assertNotIn(spam["link"], merged)
        self.assertNotIn(old_spam["url"], merged)
        self.assertIn(valid_history["url"], merged)
        self.assertEqual(merged[stale_aaip["url"]]["published_date"], "2026-04-13")
        self.assertEqual(aaip_report["repaired_historical_dates"], 1)
        self.assertEqual(report["verified_rejected_urls"], 1)
        self.assertEqual(report["discarded_records"], 1)

    def test_anchor_wrapped_cards_keep_each_aaip_title_and_date(self):
        body = """
        <div class="row panels-row">
          <a class="panel" href="/noticias/primera-noticia"><time datetime="2026-11-16 09:00:00">16 de noviembre</time><h3>Primera noticia sobre protección de datos</h3><p>Resumen uno</p></a>
          <a class="panel" href="/noticias/segunda-noticia"><time datetime="2026-11-12 10:00:00">12 de noviembre</time><h3>Segunda noticia sobre transparencia pública</h3><p>Resumen dos</p></a>
        </div>"""
        s = mock.Mock(); s.get.return_value = Response(body=body)
        report = {"pages_ok": 0, "detail_pages_ok": 0, "warnings": []}

        rows = listing(s, "aaip", SOURCES["aaip"][3], report)

        self.assertEqual([row["title"] for row in rows], [
            "Primera noticia sobre protección de datos",
            "Segunda noticia sobre transparencia pública",
        ])
        self.assertEqual([row["published_date"] for row in rows], ["2026-11-16", "2026-11-12"])

    def test_icn_uses_official_home_page_after_news_archive_timeout(self):
        report = {"pages_ok": 0, "detail_pages_ok": 0, "warnings": []}
        recent = [record(
            "icn_argentina",
            "Patria Mía: la nueva colección de la Imprenta del Congreso de la Nación",
            "22 de octubre de 2026",
            "https://icn.gob.ar/noticias/patria-mia",
        )]
        with mock.patch(
            "scripts.source_collectors.listing",
            side_effect=[requests.Timeout("timeout"), recent],
        ) as fetch_listing:
            rows = icn_news(mock.Mock(), SOURCES["icn_argentina"][3], report)

        self.assertEqual(rows, recent)
        self.assertEqual(fetch_listing.call_count, 2)
        self.assertEqual(report["effective_endpoint"], "https://icn.gob.ar/")
        self.assertFalse(report["coverage_complete"])
        self.assertTrue(report["warnings"])

    def test_blocked_parliament_news_never_becomes_library_events(self):
        report={"pages_ok":0,"detail_pages_ok":0,"warnings":[]}
        with mock.patch("scripts.source_collectors.listing",side_effect=requests.HTTPError("403 Forbidden")) as fetch_listing:
            with self.assertRaises(requests.HTTPError):
                parliament_news(mock.Mock(), SOURCES["parlamento_uy"][3], report)
        self.assertEqual(fetch_listing.call_count,3)
        self.assertEqual(len(report["attempts"]),3)
        self.assertTrue(all('/eventos/' not in r['endpoint'] for r in report['attempts']))
        self.assertTrue(report['warnings'])

    def test_encoding_repair_precedes_whitespace_collapse(self):
        self.assertEqual(text("<p>Proteção Ã\u00a0 privacidade</p>"), "Proteção à privacidade")
        self.assertEqual(repair_encoding("COOPERAÇÃO ANPD & DATA PRIVACY BRASIL"), "COOPERAÇÃO ANPD & DATA PRIVACY BRASIL")
        self.assertEqual(repair_encoding("ProteÃ§Ã£o de dados e usuÃ¡rios"), "Proteção de dados e usuários")

    def test_zero_page_limit_follows_complete_wordpress_archive(self):
        posts = [[{"id":1,"title":{"rendered":"Primeiro artigo"},"date":"2026-09-01T08:00:00","link":"https://mitic.gov.py/primeiro"}],
                 [{"id":2,"title":{"rendered":"Segundo artigo"},"date":"2026-08-01T08:00:00","link":"https://mitic.gov.py/segundo"}]]
        s=mock.Mock();s.get.side_effect=[Response(items,headers={"X-WP-TotalPages":"2","X-WP-Total":"2"}) for items in posts]
        report={"pages_ok":0,"errors":[]}
        with mock.patch("scripts.source_collectors.time.sleep"):
            rows=wp(s,"mitic_paraguai",SOURCES["mitic_paraguai"][3],0,report)
        self.assertEqual(len(rows),2)
        self.assertEqual(s.get.call_count,2)
        self.assertTrue(report["coverage_complete"])
        self.assertEqual(report["site_items_collected"],2)

    def test_iso_timestamp_and_portuguese_abbreviation(self):
        self.assertEqual(date_iso("2026-10-06T12:45:00"),"2026-10-06")
        self.assertEqual(str(parse_date("2026-10-06T12:45:00").date()),"2026-10-06")
        self.assertEqual(date_iso("02 OUT 2026"),"2026-10-02")
        self.assertEqual(date_iso("31/02/2026"),"")

    def test_wordpress_page_limit_and_dates_not_crawl_date(self):
        data=[{"title":{"rendered":"IA &amp; proteção de dados"},"date":"2026-09-01T08:00:00", "link":"https://www.dataprivacybr.org/teste", "excerpt":{"rendered":"<p>Resumo</p>"}}]
        s=mock.Mock();s.get.return_value=Response(data,headers={"X-WP-TotalPages":"1","X-WP-Total":"1"})
        report={"pages_ok":0,"errors":[]}
        rows=wp(s,"dataprivacy",SOURCES["dataprivacy"][3],10,report)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]["published_date"],"2026-09-01")
        self.assertEqual(rows[0]["record_type"],"Publicação institucional");self.assertEqual(report["pages_ok"],1)
        self.assertEqual(rows[0]["title"],"IA & proteção de dados")

    def test_later_page_failure_preserves_successful_posts(self):
        data=[{"title":{"rendered":"Primeiro artigo"},"date":"2026-09-01T08:00:00","link":"https://www.dataprivacybr.org/primeiro"}]
        s=mock.Mock();s.get.side_effect=[Response(data,headers={"X-WP-TotalPages":"2"}),requests.Timeout("timeout")]
        report={"pages_ok":0,"errors":[]}
        with mock.patch("scripts.source_collectors.time.sleep"):
            rows=wp(s,"dataprivacy",SOURCES["dataprivacy"][3],10,report)
        self.assertEqual(len(rows),1);self.assertEqual(len(report["errors"]),1)

    def test_blank_edpb_anchor_uses_heading_and_card_date(self):
        body='<div class="node-article-card__content"><h3>Guidance on data protection</h3><time datetime="2026-09-01T12:00:00Z">1 September</time><a href="/news/guidance_en"></a></div>'
        s=mock.Mock();s.get.return_value=Response(body=body)
        report={"pages_ok":0,"detail_pages_ok":0,"warnings":[]}
        rows=listing(s,"edpb",SOURCES["edpb"][3],report)
        self.assertEqual(rows[0]["title"],"Guidance on data protection");self.assertEqual(rows[0]["published_date"],"2026-09-01")

    def test_internetlab_sitemap_fallback_keeps_recent_official_posts(self):
        sitemap = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://internetlab.org.br/pt/noticias/escola-internetlab/</loc><lastmod>2026-10-14T12:00:00+00:00</lastmod></url>
          <url><loc>https://internetlab.org.br/pt/opiniao/nota-papo-de-ia/</loc><lastmod>2026-10-16T12:00:00+00:00</lastmod></url>
          <url><loc>https://internetlab.org.br/pt/semanario/23-10-2026/</loc><lastmod>2026-10-23T12:00:00+00:00</lastmod></url>
        </urlset>"""
        opinion = '<div id="content"><h2>Nota sobre pesquisa Papo de IA</h2></div><meta property="article:published_time" content="2026-10-16T09:00:00-03:00">'
        news = '<article><h2>Escola InternetLab de Governança Democrática</h2></article><time datetime="2026-10-14T09:00:00-03:00"></time>'
        s = mock.Mock()
        s.get.side_effect = [Response(body=sitemap), Response(body=opinion), Response(body=news)]
        report = {"pages_ok":0, "detail_pages_ok":0, "warnings":[]}
        with mock.patch("scripts.source_collectors.time.sleep"):
            rows = internetlab_sitemap(s, "internetlab", report)
        self.assertEqual([row["published_date"] for row in rows], ["2026-10-16", "2026-10-14"])
        self.assertEqual(report["method"], "Sitemap oficial após API/feed indisponíveis")
        self.assertFalse(report["coverage_complete"])
        self.assertEqual(report["detail_pages_ok"], 2)

    def test_internetlab_html_fallback_deduplicates_and_requires_dates(self):
        blog = """
        <article><span>Notícias | 14.10.2026</span>
          <a href="/pt/noticias/escola-internetlab/"><h2>Escola InternetLab de Governança Democrática</h2></a>
        </article>"""
        archive = """
        <article><span>Notícias | 14.10.2026</span>
          <a href="/pt/noticias/escola-internetlab/"><h2>Escola InternetLab de Governança Democrática</h2></a>
        </article>
        <article><span>Opinião | 16.10.2026</span>
          <a href="/pt/opiniao/nota-papo-de-ia/"><h2>Nota sobre pesquisa Papo de IA</h2></a>
        </article>
        <article><a href="/pt/pesquisa/sem-data/"><h2>Registro sem data não confirmado</h2></a></article>"""
        s = mock.Mock()
        s.get.side_effect = [Response(body=blog), Response(body=archive), Response(body="<html></html>")]
        report = {"pages_ok":0, "detail_pages_ok":0, "warnings":[]}
        rows = internetlab_html(s, "internetlab", report)
        self.assertEqual([row["published_date"] for row in rows], ["2026-10-14", "2026-10-16"])
        self.assertEqual(report["method"], "Arquivos HTML oficiais após API/feed/sitemap indisponíveis")
        self.assertFalse(report["coverage_complete"])

    def test_structured_date_ignores_modified_date(self):
        soup=BeautifulSoup('<script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-09-01T10:00:00","dateModified":"2026-10-01"}</script>',"html.parser")
        self.assertEqual(metadata_date(soup),"2026-09-01")

    def test_legacy_setup_cell_is_not_executed(self):
        item={"name":"nic_.ipynb","book":{"cells":[{"cell_type":"code","source":["pass"]},{"cell_type":"code","source":["raise RuntimeError('database/browser setup must not execute')"]}]}}
        prepared=prepare_collector(item);self.assertEqual(prepared["source_id"],"nic")
        self.assertTrue(callable(prepared["scope"]["collect"]))

    def test_reference_has_no_invented_publication_date(self):
        row=record("meta_transparency","Reference","","https://transparency.meta.com/reports/",record_type="Página institucional")
        self.assertEqual(row["published_date"],"");self.assertEqual(row["record_type"],"Página institucional")

    def test_colab_export_has_one_updateable_html(self):
        rows=[record("dataprivacy","IA e proteção de dados","2026-10-01T12:00:00","https://www.dataprivacybr.org/teste")]
        data,quality=normalize_records(rows)
        dashboard=build_dashboard(data,[],days=None)
        with tempfile.TemporaryDirectory() as directory:
            output=export_results(data,[],dashboard,Path(directory),quality)
            self.assertEqual(len(list(Path(directory).glob("*.html"))),1)
            page=output["Painel_FAPESP_interativo.html"].read_text()
            self.assertIn('id="import-file"',page)
            self.assertIn('id="save-html"',page)
            self.assertNotIn('__CURADORIA_DATA__',page)
