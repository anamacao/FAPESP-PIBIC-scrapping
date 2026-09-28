import csv
import json
import tempfile
import unittest
from pathlib import Path

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
            "https://mercociudades.org/pt-br/noticias/":
                '<article class="post"><h2><a href="/noticia/2">Mercocidades</a></h2>'
                '<span class="fusion-single-line-meta"><span>24.09.2026</span></span></article>',
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
            self.assertEqual(latest["notebooks"]["syntax_ok"], 21)


if __name__ == "__main__":
    unittest.main()
