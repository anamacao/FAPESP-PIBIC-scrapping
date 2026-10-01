import csv
import json
import tempfile
import unittest
from pathlib import Path

import requests

from scripts.fapesp_weekly import (
    collect_edpb, collect_mercociudades, collect_nic, collect_senado_federal,
    date_iso, run,
)


class Response:
    def __init__(self, body):
        self.body = body
        self.text = body if isinstance(body, str) else ""

    def json(self):
        return self.body

    def raise_for_status(self):
        pass


class Client:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, timeout):
        return Response(self.pages[url])


class Forbidden(Response):
    status_code = 403

    def raise_for_status(self):
        raise requests.HTTPError("403 Forbidden", response=self)


class WeeklyTest(unittest.TestCase):
    def test_dates_and_four_sources(self):
        self.assertEqual(date_iso("31.10.2025"), "2025-10-31")
        self.assertEqual(date_iso("03 de noviembre de 2025"), "2025-11-03")
        self.assertEqual(date_iso("2026-09-25T12:00:00Z"), "2026-09-25")
        pages = {
            "https://www.nic.br/noticias/indice/todos/indice-1.json": [
                {"titulo": "Título NIC", "data": "2026-09-25", "permalink": "/noticia/1"}
            ],
            "https://www.edpb.europa.eu/news_en?type%5B1%5D=1":
                '<div class="node-article-card"><a class="node-article-card__link" href="/news/1">'
                '<span class="node-article-card__title">EDPB</span></a><time datetime="2026-09-24"></time></div>',
            "https://mercociudades.org/wp-json/wp/v2/posts?per_page=50&lang=pt-br&_fields=date,link,title": [
                {"date": "2026-09-24T12:45:32", "link": "https://mercociudades.org/pt-br/noticia/2",
                 "title": {"rendered": "Mercocidades"}}
            ],
            "https://www12.senado.leg.br/noticias/ultimas":
                '<ol class="lista-resultados"><li><a href="/noticias/materias/2026/09/23/x">Senado</a>'
                '<span class="text-muted normalis hidden-xs">23/09/2026 09h00</span></li></ol>',
        }
        client = Client(pages)
        for collector, expected in (
            (collect_nic, "2026-09-25"),
            (collect_edpb, "2026-09-24"),
            (collect_mercociudades, "2026-09-24"),
            (collect_senado_federal, "2026-09-23"),
        ):
            rows = collector(client)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["published_date"], expected)

    def test_failure_preserves_history_and_reports_it(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            good = {"source_id": "nic", "title": "Original", "published_date": "2026-09-25",
                    "published_raw": "2026-09-25", "url": "https://www.nic.br/noticia/1"}
            first = run(output, collectors={"nic": lambda _: [good]})
            self.assertEqual(first["total_records"], 1)
            failed = run(output, collectors={"nic": lambda _: []})
            self.assertEqual(failed["sources"][0]["status"], "failed")
            with (output / "news.csv").open(newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(rows[0]["title"], "Original")
            self.assertEqual(rows[0]["published_date"], "2026-09-25")
            latest = json.loads((output / "runs/latest.json").read_text())
            self.assertEqual(latest["notebooks"]["syntax_ok"], 22)

    def test_mercociudades_official_rss_after_api_403(self):
        api = "https://mercociudades.org/wp-json/wp/v2/posts?per_page=50&lang=pt-br&_fields=date,link,title"
        feed = "https://mercociudades.org/feed/"
        rss = '''<?xml version="1.0"?><rss version="2.0"><channel>
          <item><title>Notícia recente</title><link>https://mercociudades.org/noticia-recente/</link>
          <pubDate>Mon, 28 Sep 2026 16:22:03 +0000</pubDate></item>
          <item><title>Notícia anterior</title><link>https://mercociudades.org/noticia-anterior/</link>
          <pubDate>Mon, 14 Sep 2026 16:22:03 +0000</pubDate></item>
        </channel></rss>'''

        class FeedClient:
            def get(self, url, timeout):
                return Forbidden("") if url == api else Response(rss)

        rows = collect_mercociudades(FeedClient())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["published_date"], "2026-09-28")
        self.assertEqual(rows.method, "rss")
        self.assertTrue(rows.complete_week)
        with tempfile.TemporaryDirectory() as directory:
            report = run(Path(directory), collectors={"mercociudades": collect_mercociudades},
                         client=FeedClient())
            self.assertEqual(report["sources"][0]["status"], "ok")
            self.assertEqual(report["sources"][0]["method"], "official_rss_after_api_403")


if __name__ == "__main__":
    unittest.main()
