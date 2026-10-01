"""Protect document counts, date windows and transparent selection."""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import curadoria_agent as agent
import curadoria_dashboard as dashboard

CONFIG = agent.load_config(ROOT / "config/curadoria.json")


def item(title="LGPD e IA no Mercosul", url="https://example.org/1", published="2026-10-01", **extra):
    return dict(title=title, url=url, published_date=published, source_id="nic",
                corpus="scrapers", **extra)


class DashboardTests(unittest.TestCase):
    def test_cross_corpus_dedup_preserves_selection_without_merging_terms(self):
        news, _ = agent.prepare([item()], CONFIG)
        catalog, _ = agent.prepare([item("GDPR", manually_selected=True)], CONFIG)
        combined = dashboard.merge_documents({"scrapers": {"rows": news}, "catalogo": {"rows": catalog}})
        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0]["corpora"], ["catalogo", "scrapers"])
        self.assertTrue(combined[0]["manually_selected"])
        self.assertNotIn("GDPR", combined[0]["keywords"])

    def test_curated_entry_is_preserved_without_title_keyword(self):
        rows, _ = agent.prepare([item("Ata do Grupo Agenda Digital", manually_selected=True)], CONFIG)
        self.assertFalse(rows[0]["candidate"])
        self.assertEqual(len(dashboard.filter_documents(rows, "2026-10-01")), 1)

    def test_curated_mercosul_document_receives_axis_without_false_candidate(self):
        rows, _ = agent.prepare([item("Ata do Grupo Agenda Digital do Mercosul",
                                     manually_selected=True)], CONFIG)
        self.assertFalse(rows[0]["candidate"])
        self.assertIn("Governança digital no Mercosul", rows[0]["topics"])

    def test_exact_dates_required_in_shortlist(self):
        rows, _ = agent.prepare([item(), item(url="https://example.org/2", published="outubro de 2026"),
                                 item(url="https://example.org/3", published=""),
                                 item(url="https://example.org/4", published="2026-10-02")], CONFIG)
        selected = dashboard.shortlist(rows, date(2026, 10, 1), 7)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["published_date"], "2026-10-01")

    def test_filter_combines_source_term_and_dates(self):
        rows, _ = agent.prepare([item(), item("GDPR", "https://example.org/2", "2026-09-10")], CONFIG)
        chosen = dashboard.filter_documents(rows, "2026-10-01", start="2026-09-25",
                                            keyword="Inteligência artificial", source="NIC.br")
        self.assertEqual(len(chosen), 1)
        with self.assertRaises(ValueError):
            dashboard.filter_documents(rows, "2026-10-01", start="2026-10-01", end="2026-09-01")

    def test_context_is_opt_in_and_evidence_is_recorded(self):
        raw = [item("Ata regional", summary="Proteção de dados e IA")]
        titles, _ = agent.prepare(raw, CONFIG)
        context, _ = agent.prepare(raw, CONFIG, "title_summary")
        self.assertFalse(titles[0]["candidate"])
        self.assertTrue(context[0]["candidate"])
        self.assertIn("Inteligência artificial", context[0]["match_evidence"])

    def test_jaccard_and_frequency_use_document_counts(self):
        rows, _ = agent.prepare([item("LGPD LGPD e GDPR"), item("GDPR", "https://example.org/2")], CONFIG)
        data = dashboard.measures(rows, CONFIG, date(2026, 10, 1))
        pair = next(r for r in data["pairs"] if {r["termo_1"], r["termo_2"]} == {"LGPD", "GDPR"})
        self.assertEqual((pair["documentos"], pair["jaccard"]), (1, .5))
        term = next(r for r in data["keywords"] if r["palavra_chave"] == "LGPD")
        self.assertEqual(term["documentos"], 1)

    def test_import_portuguese_semicolon_csv_and_multiline_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "dados.csv"
            path.write_text('título;link;data;resumo\n"IA";"https://example.org/1";"01/10/2026";'
                            '"Resumo com\nsegunda linha"\n', encoding="utf-8-sig")
            row = dashboard.import_csv(path)[0]
            self.assertEqual(row["title"], "IA")
            self.assertIn("\n", row["summary"])
            parsed, _ = agent.prepare([row], CONFIG)
            self.assertEqual(parsed[0]["published_date"], "2026-10-01")

    def test_payload_cannot_close_script_tag(self):
        value = dashboard.json_for_html({"title": "</script><script>alert(1)</script>"})
        self.assertNotIn("</script>", value)

    def test_english_and_year_dates_do_not_invent_precision(self):
        self.assertEqual(agent.publication_date("September 18, 2026"), ("2026-09-18", "day"))
        self.assertEqual(agent.publication_date("2026"), ("2026", "year"))


if __name__ == "__main__":
    unittest.main()
