"""Check provenance, date handling and denominators of the unified analysis."""

import unittest

from scripts.fapesp_agent import build_dashboard, normalize_records, parse_date


class UnifiedAgentTests(unittest.TestCase):
    def test_spanish_date_dedup_and_reference_separation(self):
        records = [
            {"source_id": "parlamento_uy", "source": "Biblioteca do Poder Legislativo — eventos",
             "title": "Debate sobre inteligencia artificial", "date": "21 de septiembre de 2026",
             "url": "https://biblioteca.parlamento.gub.uy/eventos/ver/77?utm_source=mail",
             "origin": "Drive collector", "origin_notebook": "parlamento_uy.ipynb"},
            {"source_id": "parlamento_uy", "source": "Biblioteca do Poder Legislativo — eventos",
             "title": "Debate sobre inteligencia artificial", "date": "21 de septiembre de 2026",
             "url": "https://biblioteca.parlamento.gub.uy/eventos/ver/77",
             "origin": "CSV da sessão", "origin_notebook": "parlamento_uy.csv"},
            {"source_id": "meta_transparency", "title": "Relatório de pedidos governamentais",
             "url": "https://transparency.meta.com/reports/government-data-requests/",
             "reference_link": True, "origin": "Drive collector"},
        ]
        data, quality = normalize_records(records)
        self.assertEqual((len(data), quality["duplicates"]), (2, 1))
        self.assertEqual(str(parse_date("21 de septiembre de 2026").date()), "2026-09-21")
        self.assertEqual(set(data["record_type"]), {"Evento da Biblioteca", "Referência institucional"})
        self.assertIn("CSV da sessão", data.loc[data["record_type"] == "Evento da Biblioteca", "origins"].iloc[0])

    def test_regional_topic_percent_uses_titles_as_denominator(self):
        records = [
            {"source_id": "anpd", "title": "Proteção de dados pessoais e inteligência artificial",
             "date": "2026-09-29", "url": "https://www.gov.br/anpd/noticia-1"},
            {"source_id": "anpd", "title": "Consulta pública sobre governança da internet",
             "date": "2026-09-30", "url": "https://www.gov.br/anpd/noticia-2"},
            {"source_id": "edpb", "title": "GDPR and data protection guidance",
             "date": "2026-09-29", "url": "https://www.edpb.europa.eu/news/1"},
        ]
        data, _ = normalize_records(records)
        result = build_dashboard(data, [], days=None)
        subset = result["regional"]
        mercosul = subset[(subset["região"] == "Mercosul") & (subset["tema"] == "Proteção de dados")]
        self.assertEqual(float(mercosul["% dos títulos"].iloc[0]), 50.0)
        self.assertEqual(len(result["selected"]), 3)
        self.assertTrue(len(result["evidence"]) >= 3)
        self.assertTrue(result["figures"])


if __name__ == "__main__":
    unittest.main()
