"""Build a self-contained Colab from the tested curator and a real data snapshot."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CELLS = []


def cell(kind, text):
    item = {"cell_type": kind, "metadata": {},
            "id": hashlib.sha256((str(len(CELLS)) + text).encode()).hexdigest()[:12],
            "source": text.strip("\n").splitlines(keepends=True)}
    if kind == "code":
        item.update(execution_count=None, outputs=[])
    CELLS.append(item)


def build() -> Path:
    cell("markdown", """
# Observatório FAPESP — agente da curadoria semanal
**Ana Beatriz Mação de Barros Ferreira · governança digital, proteção de dados e Mercosul**

Este notebook reúne coleta recente, catálogo de fontes, classificação por palavras-chave,
tabelas, gráficos interativos e uma lista de até cinco publicações para leitura.
Os cinco eixos são GDPR/LGPD, IA e dados, governança digital no Mercosul, UE–Mercosul e Sul Global.

**Como usar:** execute **Ambiente de execução → Executar tudo**. Para explorar depois,
abra o arquivo **painel_interativo.html** incluído no ZIP da última seção.
Edite os parâmetros abaixo para mudar o período ou acrescentar CSVs dos outros coletores.

O notebook inclui uma cópia real dos dados e do catálogo usados na criação: funciona também
sem rede, identificando a idade da base. A coleta ao vivo monitora **NIC.br, EDPB, Mercociudades
e Senado Federal**; os demais notebooks não são executados por esta rotina.
Nenhuma chave de API nem GPU é necessária. A análise usa regras transparentes e não cria notícias.
""")
    cell("code", """
#@title 1. Parâmetros da pesquisa
import os
from pathlib import Path
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

DATA_REFERENCIA = "" #@param {type:"date"}
JANELA_DIAS = 7 #@param {type:"integer"}
ATUALIZAR_NOTICIAS = True #@param {type:"boolean"}
BAIXAR_BASE_GITHUB = True #@param {type:"boolean"}
INCLUIR_NOTAS_DO_CATALOGO = False #@param {type:"boolean"}
CORPUS_GRAFICOS = "todos" #@param ["todos", "scrapers", "catalogo"]
PASTA_CSV_EXTRA = "" #@param {type:"string"}
CAMINHO_CATALOGO_PROPRIO = "" #@param {type:"string"}
SALVAR_NO_GOOGLE_DRIVE = False #@param {type:"boolean"}
PASTA_DRIVE = "/content/drive/MyDrive/FAPESP/Curadoria" #@param {type:"string"}
BAIXAR_ZIP_AO_TERMINAR = True #@param {type:"boolean"}

REFERENCIA = date.fromisoformat(DATA_REFERENCIA) if DATA_REFERENCIA else datetime.now(ZoneInfo("America/Sao_Paulo")).date()
if not 1 <= JANELA_DIAS <= 366:
    raise ValueError("Escolha uma janela de 1 a 366 dias.")
if CORPUS_GRAFICOS not in {"todos", "scrapers", "catalogo"}:
    raise ValueError("CORPUS_GRAFICOS deve ser todos, scrapers ou catalogo.")
MODO_TEXTO = "title_summary" if INCLUIR_NOTAS_DO_CATALOGO else "title"
BASE = Path("/content") if Path("/content").exists() else Path.cwd()
AGENTE = BASE / "agente_curadoria_fapesp"
AGENTE.mkdir(parents=True, exist_ok=True)
MODO_OFFLINE = os.getenv("CURADORIA_OFFLINE") == "1"
if MODO_OFFLINE:
    ATUALIZAR_NOTICIAS = BAIXAR_BASE_GITHUB = False
print("Referência:", REFERENCIA, "| Janela:", JANELA_DIAS, "dias | Texto:", MODO_TEXTO)
""")
    cell("code", """
#@title 2. Preparar as dependências
import importlib.util
import subprocess
import sys

pacotes = {"requests": "requests>=2.32,<3", "bs4": "beautifulsoup4>=4.12,<5",
           "IPython": "ipython>=8,<10", "matplotlib": "matplotlib>=3.7,<4",
           "plotly": "plotly>=5.20,<7"}
faltantes = [spec for module, spec in pacotes.items() if importlib.util.find_spec(module) is None]
if faltantes:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *faltantes])
print("Dependências disponíveis. CPU é suficiente.")
""")
    bundled = {f"scripts/{name}": (ROOT / "scripts" / name).read_text(encoding="utf-8")
               for name in ("curadoria_agent.py", "curadoria_dashboard.py",
                            "curadoria_dashboard.html", "fapesp_weekly.py")}
    bundled["config/curadoria.json"] = (ROOT / "config/curadoria.json").read_text(encoding="utf-8")
    snapshots = {name: (ROOT / name).read_text(encoding="utf-8")
                 for name in ("data/news.csv", "data/runs/latest.json",
                              "data/curadoria/Catalogo_de_fontes_FAPESP.md")}
    code = (
        "#@title 3. Carregar o agente e a base real incluída\nimport json\n"
        "ARQUIVOS_AGENTE = " + repr(bundled) + "\n"
        "BASE_INCLUIDA = " + repr(snapshots) + "\n"
        "for nome, conteudo in ARQUIVOS_AGENTE.items():\n"
        "    destino = AGENTE / nome\n    destino.parent.mkdir(parents=True, exist_ok=True)\n"
        "    if nome != 'config/curadoria.json' or not destino.exists():\n"
        "        destino.write_text(conteudo, encoding='utf-8')\n"
        "for nome, conteudo in BASE_INCLUIDA.items():\n"
        "    destino = AGENTE / nome\n    destino.parent.mkdir(parents=True, exist_ok=True)\n"
        "    if not destino.exists():\n        destino.write_text(conteudo, encoding='utf-8')\n"
        "if str(AGENTE / 'scripts') not in sys.path:\n    sys.path.insert(0, str(AGENTE / 'scripts'))\n"
        "import curadoria_agent as agente\nimport curadoria_dashboard as painel\n"
        "import fapesp_weekly as coletor\n"
        "from IPython.display import display, HTML, FileLink, Markdown\n"
        "print('Código carregado; histórico local preservado ao reexecutar.')\n")
    cell("code", code)
    cell("markdown", """
## Atualizar e ampliar as entradas
O catálogo reúne fontes já selecionadas; a base dos scrapers reúne notícias coletadas.
A tabela registra os dois tipos. As palavras-chave são calculadas no título por padrão.
Se você habilitar as notas do catálogo, os números passam a incluir também essas notas editoriais.

Para importar outros notebooks, exporte seus resultados em CSV, coloque-os numa pasta e
preencha **PASTA_CSV_EXTRA**. O agente reconhece título/title, link/url, data/date e fonte/source.
Datas sem confirmação permanecem sem data; nenhum arquivo de entrada é alterado.
""")
    cell("code", """
#@title 4. Buscar o histórico mais recente do GitHub
import csv
import io
import requests

URL_BASE = "https://raw.githubusercontent.com/anamacao/FAPESP-PIBIC-scrapping/main/"
AVISOS_ENTRADA = []
if BAIXAR_BASE_GITHUB:
    for relativo in ("data/news.csv", "data/runs/latest.json"):
        try:
            resposta = requests.get(URL_BASE + relativo, timeout=20)
            resposta.raise_for_status()
            destino = AGENTE / relativo
            if relativo.endswith(".csv"):
                novas = list(csv.DictReader(io.StringIO(resposta.content.decode("utf-8-sig"))))
                if not novas or not set(coletor.FIELDS).issubset(novas[0]):
                    raise ValueError("O CSV remoto não tem a estrutura esperada.")
                historico = coletor.read_history(destino)
                for item in novas:
                    chave = (item["source_id"], item["url"])
                    antiga = historico.get(chave)
                    if antiga:
                        if antiga.get("last_seen", "") > item.get("last_seen", ""):
                            continue
                        vistas = [v for v in (antiga.get("first_seen"), item.get("first_seen")) if v]
                        if vistas:
                            item["first_seen"] = min(vistas)
                    historico[chave] = {k: item.get(k, "") for k in coletor.FIELDS}
                with destino.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=coletor.FIELDS)
                    writer.writeheader()
                    writer.writerows(historico.values())
            else:
                diagnostico = resposta.json()
                if not isinstance(diagnostico.get("sources"), list):
                    raise ValueError("Diagnóstico remoto inválido.")
                destino.write_text(json.dumps(diagnostico, ensure_ascii=False, indent=2), encoding="utf-8")
            print("Atualizado:", relativo)
        except (requests.RequestException, ValueError, UnicodeError) as exc:
            aviso = "Atualização do GitHub indisponível para " + relativo + ": " + str(exc)[:180]
            AVISOS_ENTRADA.append(aviso)
            print(aviso, "— usando a cópia disponível.")
else:
    print("Usando a base local incluída; consulte a data da coleta no relatório.")
""")
    cell("code", """
#@title 5. Executar a coleta recente e consultar o diagnóstico
if ATUALIZAR_NOTICIAS:
    print("Coletando NIC.br, EDPB, Mercociudades e Senado Federal…")
    diagnostico = coletor.run(AGENTE / "data")
    for fonte in diagnostico["sources"]:
        print(fonte["source_id"], fonte["status"], "| vistos:", fonte["seen"], "| novos:", fonte["new"])
else:
    diagnostico = json.loads((AGENTE / "data/runs/latest.json").read_text(encoding="utf-8"))
    AVISOS_ENTRADA.append("Coleta ao vivo desativada nesta execução; resultados usam o histórico disponível.")
print("Coleta registrada em:", diagnostico.get("generated_at", "não informada"))
print("A rotina coleta notícias; não executa os outros notebooks.")
""")
    cell("code", """
#@title 6. Fontes adicionais, catálogo e palavras-chave personalizadas
import shutil

if SALVAR_NO_GOOGLE_DRIVE:
    try:
        from google.colab import drive
    except ImportError as exc:
        raise RuntimeError("Montagem do Drive disponível na sessão do Google Colab.") from exc
    drive.mount("/content/drive")

CONFIGURACAO = AGENTE / "config/curadoria.json"
config = agente.load_config(CONFIGURACAO)
# Exemplo: {"Auditoria algorítmica": ["auditoria algorítmica", "algorithmic audit"]}
PALAVRAS_EXTRAS = {}
for termo, sinonimos in PALAVRAS_EXTRAS.items():
    config["keywords"][termo] = sinonimos
    if termo not in config["relevance_keywords"]:
        config["relevance_keywords"].append(termo)
CONFIGURACAO.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

CATALOGO = Path(CAMINHO_CATALOGO_PROPRIO) if CAMINHO_CATALOGO_PROPRIO else AGENTE / "data/curadoria/Catalogo_de_fontes_FAPESP.md"
ENTRADA_NOTICIAS = AGENTE / "data/news.csv"
if PASTA_CSV_EXTRA:
    pasta = Path(PASTA_CSV_EXTRA)
    arquivos = sorted(pasta.glob("*.csv"))
    if not arquivos:
        raise ValueError("Nenhum CSV encontrado em PASTA_CSV_EXTRA.")
    todas = agente.read_news(ENTRADA_NOTICIAS)
    for arquivo in arquivos:
        adicionais = painel.import_csv(arquivo)
        todas.extend(adicionais)
        print(arquivo.name, ":", len(adicionais), "linhas")
    ENTRADA_NOTICIAS = AGENTE / "data/noticias_com_importacoes.csv"
    # Grava apenas uma entrada derivada; mantém intactos os CSVs originais e o histórico.
    campos = ["source_id", "title", "published_date", "url", "first_seen", "last_seen",
              "summary", "publication_type"]
    with ENTRADA_NOTICIAS.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=campos, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(todas)
if not CATALOGO.is_file():
    raise FileNotFoundError("Catálogo não encontrado: " + str(CATALOGO))
print("Entradas:", ENTRADA_NOTICIAS.name, "|", CATALOGO.name, "|", len(config["keywords"]), "termos no dicionário")
""")
    cell("code", """
#@title 7. Gerar as tabelas, os gráficos e o relatório completo
SAIDA = AGENTE / "resultados" / REFERENCIA.isoformat()
metadata = agente.run(ENTRADA_NOTICIAS, SAIDA, CONFIGURACAO, REFERENCIA, JANELA_DIAS,
                      CATALOGO, AGENTE / "data/runs/latest.json", MODO_TEXTO)
metadata["warnings"].extend(AVISOS_ENTRADA)
# Recria o painel com os avisos de rede desta sessão e os mesmos insumos.
corpus_data = {}
for corpus, bruto in (("scrapers", agente.read_news(ENTRADA_NOTICIAS)), ("catalogo", agente.read_catalog(CATALOGO))):
    registros, qualidade = agente.prepare(bruto, config, MODO_TEXTO)
    corpus_data[corpus] = agente.summarize(registros, config, REFERENCIA, JANELA_DIAS,
                                         diagnostico if corpus == "scrapers" else None)
painel.export_dashboard(SAIDA, corpus_data, config, metadata)
(SAIDA / "resumo.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
for corpus, totais in metadata["corpus"].items():
    print(corpus, ":", totais["documents"], "registros,", totais["candidates_window"], "candidatas lexicais na janela")
for aviso in metadata["warnings"]:
    print("Cobertura:", aviso)
print("Saídas:", SAIDA)
""")
    cell("markdown", """
## Tabelas e gráficos da pesquisa
Os números descrevem os documentos observados nas fontes monitoradas.
O catálogo foi selecionado previamente e não é uma amostra aleatória de notícias.
Um documento pode integrar mais de um eixo. A coocorrência não comprova influência regulatória.
Datas apenas mensais entram no gráfico mensal, mas ficam fora da comparação semanal.
""")
    cell("code", """
#@title 8. Tabelas de fontes, termos e documentos
if CORPUS_GRAFICOS == "todos":
    registros = painel.merge_documents(corpus_data)
else:
    registros = corpus_data[CORPUS_GRAFICOS]["rows"]
observados = painel.filter_documents(registros, REFERENCIA.isoformat())
medidas = painel.measures(observados, config, REFERENCIA, JANELA_DIAS)
display(Markdown("### Frequência das palavras-chave"))
display(HTML(agente.html_table(medidas["keywords"], [("palavra_chave", "Palavra-chave"), ("documentos", "Documentos")])))
display(Markdown("### Cobertura dos scrapers"))
display(HTML(agente.html_table(corpus_data["scrapers"]["sources"],
    [("fonte", "Fonte"), ("total_base", "Base"), ("publicadas_janela", "Publicadas na janela"),
     ("candidatas_janela", "Candidatas"), ("status_ultima_coleta", "Coleta"), ("observacao", "Observação")])))
display(Markdown("### Documentos para leitura — todos os registros nas tabelas CSV"))
display(HTML(agente.html_table(observados[:30],
    [("title", "Título e link"), ("source", "Fonte"), ("published_date", "Publicação"),
     ("topics", "Eixos"), ("keywords", "Palavras-chave"), ("match_evidence", "Evidência lexical")])))
print("Prévia: até 30 linhas. O painel HTML e os CSVs contêm todas as linhas.")
""")
    cell("code", """
#@title 9. Gráficos interativos — passe o mouse, amplie e baixe imagens
import plotly.io as pio
try:
    EM_COLAB = importlib.util.find_spec("google.colab") is not None
except ModuleNotFoundError:
    EM_COLAB = False
if EM_COLAB:
    pio.renderers.default = "colab"
else:
    pio.renderers.default = "plotly_mimetype"
FIGURAS = painel.notebook_figures(observados, config, REFERENCIA, JANELA_DIAS)
for nome, figura in FIGURAS.items():
    figura.show()
print("O painel HTML acrescenta filtros globais e a matriz normalizada de palavras-chave por fonte.")
""")
    cell("code", """
#@title 10. Resumo semanal e até cinco publicações para leitura
display(Markdown((SAIDA / "resumo_semanal.md").read_text(encoding="utf-8")))
""")
    cell("code", """
#@title 11. Salvar e baixar o pacote de resultados
ARQUIVO_ZIP = Path(shutil.make_archive(str(AGENTE / ("Curadoria_FAPESP_" + REFERENCIA.isoformat())), "zip", SAIDA))
if SALVAR_NO_GOOGLE_DRIVE:
    destino = Path(PASTA_DRIVE) / REFERENCIA.isoformat()
    destino.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SAIDA, destino, dirs_exist_ok=True)
    shutil.copy2(ARQUIVO_ZIP, destino.parent / ARQUIVO_ZIP.name)
    print("Resultados salvos em:", destino)
print("Abra painel_interativo.html depois de extrair o ZIP.")
display(FileLink(str(ARQUIVO_ZIP)))
if BAIXAR_ZIP_AO_TERMINAR and EM_COLAB:
    from google.colab import files
    files.download(str(ARQUIVO_ZIP))
print("Inclui: painel HTML, CSVs, gráficos PNG, resumo semanal e registro dos insumos.")
""")
    cell("markdown", """
## Executar toda semana
O Colab serve para executar e explorar. O repositório já tem uma rotina de coleta por
GitHub Actions às **sextas-feiras às 07h de Brasília**, antes da curadoria das 08h.
A integração deste painel está ativa: os gráficos e tabelas são gerados após cada coleta
agendada e ficam disponíveis no artefato `curadoria-fapesp` do GitHub Actions.

O catálogo incluído é uma cópia datada, não uma sincronização automática com conversas.
Atualize o arquivo do catálogo ou indique um catálogo próprio para incorporar novas seleções.
As publicações sugeridas devem ser lidas antes de virar evidência no relatório FAPESP.
""")
    document = {
        "nbformat": 4, "nbformat_minor": 5, "cells": CELLS,
        "metadata": {"colab": {"name": "Agente_curadoria_FAPESP.ipynb", "provenance": []},
                     "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python", "version": "3.11.0"}}}
    path = ROOT / "Curadoria/Agente_curadoria_FAPESP.ipynb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(build())
