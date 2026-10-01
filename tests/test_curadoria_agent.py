"""Checks that protect research counts and provenance, using small known inputs."""
import csv
import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("curadoria_agent", ROOT / "scripts/curadoria_agent.py")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)
CONFIG = agent.load_config(ROOT / "config/curadoria.json")


def news(title, published="2026-10-01", url="https://example.org/news", **extra):
    return {"source_id": "nic", "title": title, "published_date": published, "url": url,
            "first_seen": "2026-10-01T00:30:00+00:00", **extra}


class CuradoriaTests(unittest.TestCase):
    def test_aliases_and_word_boundaries(self):
        rows, _ = agent.prepare([news("IA, GDPR e protección de datos"),
                                 news("Viagem social no Mercosul", url="https://example.org/other")], CONFIG)
        relevant = next(r for r in rows if r["candidate"])
        self.assertIn("Inteligência artificial", relevant["keywords"])
        self.assertIn("Proteção de dados", relevant["keywords"])
        other = next(r for r in rows if not r["candidate"])
        self.assertNotIn("Inteligência artificial", other["keywords"])
        self.assertFalse(other["topics"])

    def test_publication_window_not_detection_window(self):
        raw = [news("LGPD antiga", "2020-01-01"), news("IA recente", "2026-09-25", "https://example.org/start"),
               news("GDPR hoje", url="https://example.org/end"),
               news("LGPD futura", "2026-10-02", "https://example.org/future"),
               news("LGPD sem data", "", "https://example.org/undated")]
        rows, _ = agent.prepare(raw, CONFIG)
        result = agent.summarize(rows, CONFIG, date(2026, 10, 1), 7)
        self.assertEqual(result["counts"]["published_window"], 2)
        self.assertEqual(result["counts"]["without_exact_date"], 1)
        self.assertEqual(result["counts"]["future_publications"], 1)
        self.assertEqual(result["sources"][0]["links_detectados_janela"], 5)
        self.assertEqual(rows[0]["first_seen_date"], "2026-09-30")

    def test_dedup_url_tracking_and_earliest_detection(self):
        rows, stats = agent.prepare([
            news("GDPR", url="https://example.org/news?utm_source=test#x", first_seen="2026-09-01T10:00:00Z"),
            news("GDPR", "", "https://example.org/news", first_seen="2026-10-01T10:00:00Z")], CONFIG)
        self.assertEqual(len(rows), 1)
        self.assertEqual(stats["duplicates_removed"], 1)
        self.assertEqual(rows[0]["published_date"], "2026-10-01")
        self.assertEqual(rows[0]["first_seen_date"], "2026-09-01")
        self.assertEqual(rows[0]["first_seen"], "2026-09-01T10:00:00Z")

    def test_month_precision_is_not_assigned_a_day(self):
        self.assertEqual(agent.publication_date("fevereiro de 2026"), ("2026-02", "month"))
        self.assertEqual(agent.publication_date("1º de setembro de 2026"), ("2026-09-01", "day"))
        self.assertEqual(agent.publication_date("2026-02-30"), ("", "unknown"))
        rows, _ = agent.prepare([news("LGPD", "outubro de 2026")], CONFIG)
        result = agent.summarize(rows, CONFIG, date(2026, 10, 1), 7)
        self.assertEqual(result["counts"]["published_window"], 0)
        self.assertEqual(result["monthly"], [{"mes": "2026-10", "candidatas": 1}])

    def test_multilabel_and_regional_conjunction(self):
        rows, _ = agent.prepare([news("GDPR e IA no Mercosul e na União Europeia")], CONFIG)
        self.assertEqual(len(rows[0]["topics"]), 4)
        rows, _ = agent.prepare([news("IA na União Europeia")], CONFIG)
        self.assertNotIn("UE–Mercosul", rows[0]["topics"])

    def test_one_term_once_per_document_and_cooccurrence(self):
        rows, _ = agent.prepare([news("GDPR GDPR e LGPD"),
                                 news("GDPR", url="https://example.org/second")], CONFIG)
        data = agent.summarize(rows, CONFIG, date(2026, 10, 1), 7)
        gdpr = next(r for r in data["keywords"] if r["palavra_chave"] == "GDPR")
        self.assertEqual(gdpr["documentos_historico"], 2)
        pair = next(r for r in data["cooccurrences"] if {r["termo_1"], r["termo_2"]} == {"GDPR", "LGPD"})
        self.assertEqual(pair["documentos"], 1)
        word = next(r for r in data["words"] if r["palavra"] == "gdpr")
        self.assertEqual((word["ocorrencias"], word["documentos"]), (3, 2))

    def test_empty_dataset_and_failed_source_remain_visible(self):
        result = agent.summarize([], CONFIG, date(2026, 10, 1), 7,
                                 {"sources": [{"source_id": "nic", "status": "failed", "error": "HTTP 403"}]})
        self.assertEqual(len(result["daily"]), 7)
        self.assertEqual(result["counts"]["candidates_window"], 0)
        self.assertEqual(result["sources"][0]["status_ultima_coleta"], "failed")
        self.assertEqual(result["sources"][0]["observacao"], "HTTP 403")

    def test_catalog_parser_preserves_links_type_and_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalog.md"
            path.write_text("# Catálogo\n### Parceria digital\n- **Instituições:** Brasil e UE\n"
                            "- **Data:** fevereiro de 2026\n- **Tipo:** relatório\n"
                            "- **Texto integral:** https://example.org/full\n"
                            "- **Apresentação oficial da UE:** https://example.org/news\n"
                            "- **Uso no relatório:** Evidência para comparação.\n"
                            "## Critérios\n### Sem conteúdo de notícia\n", encoding="utf-8")
            # A malformed catalog entry is reported rather than silently included or dropped.
            with self.assertRaisesRegex(ValueError, "sem link"):
                agent.read_catalog(path)
            path.write_text(path.read_text().split("## Critérios")[0], encoding="utf-8")
            row = agent.read_catalog(path)[0]
            self.assertEqual(row["publication_type"], "relatório")
            self.assertEqual(row["other_links"], "https://example.org/news")
            self.assertEqual(row["published_date"], "fevereiro de 2026")

    def test_rejects_unsafe_links_and_missing_titles(self):
        rows, stats = agent.prepare([news("GDPR", url="javascript:alert(1)"), news("")], CONFIG)
        self.assertEqual(rows, [])
        self.assertEqual(stats["invalid_records"], 2)

    def test_csv_neutralizes_formula_but_keeps_negative_counts_numeric(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.csv"
            agent.write_csv(path, [{"title": "=SUM(A1:A2)", "delta": -2}], ["title", "delta"])
            with path.open(encoding="utf-8-sig") as handle:
                row = next(csv.DictReader(handle))
            self.assertTrue(row["title"].startswith("'="))
            self.assertEqual(row["delta"], "-2")

    def test_html_escapes_untrusted_text(self):
        result = agent.html_table([{"title": "<script>alert(1)</script>", "url": "javascript:x"}], [("title", "Título")])
        self.assertNotIn("<script>", result)
        self.assertNotIn("href=", result)

    def test_prior_window_is_adjacent_and_nonoverlapping(self):
        rows, _ = agent.prepare([news("GDPR", "2026-09-24"),
                                 news("GDPR", "2026-09-25", "https://example.org/new")], CONFIG)
        result = agent.summarize(rows, CONFIG, date(2026, 10, 1), 7)
        self.assertEqual(result["counts"]["candidates_previous_window"], 1)
        self.assertEqual(result["counts"]["candidates_window"], 1)


if __name__ == "__main__":
    unittest.main()
