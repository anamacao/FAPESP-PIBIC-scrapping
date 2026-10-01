# FAPESP PIBIC — coleta e análise de notícias

O projeto mantém **21 notebooks originais** em [`Mercosul/`](Mercosul/) e [`UE/`](UE/). Eles fazem coleta, análise ou gráficos. Em outubro de 2026, foi acrescentado um notebook separado para consolidar a pesquisa; os 21 originais permanecem nos caminhos anteriores.

## Agente de análise unificada

[`Analise/agente_fapesp_unificado.ipynb`](Analise/agente_fapesp_unificado.ipynb) lê os coletores originais da pasta compartilhada no Drive, acrescenta o histórico de quatro fontes do [CSV semanal](data/news.csv), elimina URLs repetidas e apresenta tabelas, séries mensais, temas, palavras-chave por país, coocorrência e evidências com links. Ele registra erros e páginas incompletas por fonte. Eventos da Biblioteca e páginas de referência ficam identificados separadamente das notícias. Os títulos são pistas para a análise documental, não um resumo do conteúdo integral.

Execute o novo Colab e autorize o Drive quando solicitado. O modo `completo` percorre as páginas configuradas em cada coletor; `rapido` usa uma página por fonte. Os arquivos CSV, JSON e HTML ficam na subpasta **Resultados - agente FAPESP** dentro da pasta compartilhada, atualizados sem criar versões repetidas. A coleta semanal automática alimenta o CSV de quatro fontes e gera o [painel semanal](data/analysis/painel_fapesp.html) e tabelas com [`scripts/generate_weekly_dashboard.py`](scripts/generate_weekly_dashboard.py). A rodada completa dos outros portais acontece quando este Colab é executado. O código compartilhado está em [`scripts/fapesp_agent.py`](scripts/fapesp_agent.py).

## Código do agente da curadoria semanal

[`scripts/curadoria_agent.py`](scripts/curadoria_agent.py) transforma o histórico semanal em tabelas, gráficos PNG, resumo e um painel HTML com oito gráficos interativos. Os filtros cobrem período, fonte, eixo, palavra-chave e busca. A análise inclui frequência de termos, evolução mensal, comparação de janelas e coocorrência por contagem ou Jaccard.

    python -m pip install -r requirements-analytics.txt
    python scripts/curadoria_agent.py
    python scripts/curadoria_agent.py --catalog CAMINHO_DO_CATALOGO.md

O catálogo é uma entrada opcional fornecida pela pesquisadora. Quando informado, as fontes selecionadas são preservadas mesmo sem correspondências lexicais no título. A seleção de até cinco publicações exige datas exatas e usa uma pontuação transparente. O dicionário editável está em [`config/curadoria.json`](config/curadoria.json). O modo padrão analisa títulos; a opção `--analysis-text title_summary` inclui notas fornecidas. Eixos são multilabel e coocorrência não demonstra influência regulatória.

O workflow ativo executa a análise após a coleta de quatro fontes e oferece o artefato `curadoria-fapesp`. O gerador de notebook em [`scripts/build_curadoria_notebook.py`](scripts/build_curadoria_notebook.py) utiliza o código e os arquivos de entrada disponíveis localmente para criar um Colab independente.

## Como executar

1. Abra o notebook desejado no Google Colab e execute **Ambiente de execução → Executar tudo**. Cada coletor usa um banco SQLite temporário próprio da sessão; reiniciar a sessão apaga esse banco.
2. Os coletores com muitas páginas históricas começam pela página mais recente. A variável `TOTAL_PAGES`, `MAX_PAGES` ou argumento `max_pages` no notebook controla quantas páginas visitar. Aumente-a apenas quando precisar recuperar o histórico; uma página pode abrir dezenas de notícias.
3. [`UE/charts.ipynb`](UE/charts.ipynb) e [`UE/database_analysis.ipynb`](UE/database_analysis.ipynb) conseguem usar o [CSV acumulado](data/news.csv) do GitHub quando nenhum banco SQLite está disponível na sessão. O CSV cobre inicialmente NIC.br, EDPB, Mercociudades e Senado Federal; não inclui automaticamente os outros coletores.
4. Confira as mensagens de coleta e a quantidade de linhas antes de interpretar os gráficos. Células executadas sem erro e com zero notícias não confirmam que a fonte está funcionando.

Os notebooks atualizados usam `requests`, `beautifulsoup4`, `pandas` e `plotly`; alguns gráficos também usam `matplotlib`, `seaborn` e `wordcloud`. `UE/uniaoEuropeia.ipynb` lê o HTML público sem Chrome ou Selenium. `google_transparency.ipynb` mostra apenas contagens de links realmente coletados, sem valores regionais simulados.

## Coleta semanal

O [workflow semanal](.github/workflows/fapesp-weekly.yml) roda às sextas-feiras às 07h de Brasília e pode ser iniciado manualmente. Ele atualiza `data/news.csv` para **quatro fontes**: NIC.br, EDPB, Mercociudades e Senado Federal. [`data/runs/latest.json`](data/runs/latest.json) registra erros, registros novos e a checagem de sintaxe dos 21 originais e do novo agente (22 notebooks). A checagem de sintaxe não executa as células.

O domínio de Mercociudades respondeu HTTP 403 no ambiente do GitHub Actions pela API pública, embora o notebook tenha coletado dados em uma execução local. A rotina semanal agora tenta o [RSS oficial](https://mercociudades.org/feed/) quando a API retorna 403. O relatório identifica `method: official_rss_after_api_403`; só considera a janela de sete dias coberta quando o item mais antigo do feed antecede o início dela. Se o RSS também falhar ou trouxer poucos itens, o workflow preserva as notícias antigas e sinaliza cobertura parcial ou falha.

## Validação local dos notebooks

[`scripts/check_notebooks.py`](scripts/check_notebooks.py) executa as células originais em ordem, em um diretório temporário por notebook, e considera falha tanto uma exceção quanto um conjunto de dados vazio. Ele usa um interpretador IPython no processo porque este ambiente não permite iniciar o kernel Jupyter por sockets locais. Para reproduzir a verificação local:

```bash
python -m pip install requests beautifulsoup4 pandas plotly ipython nbformat jinja2 matplotlib seaborn wordcloud
python scripts/check_notebooks.py Mercosul/nic_.ipynb UE/charts.ipynb --output resultado.json
```

A opção `--diagnostic` reduz temporariamente a coleta a uma página e pula células de instalação no teste; **não altera os arquivos** e não deve ser usada como prova de execução integral. O [relatório de 01/10](data/runs/notebooks-20261001.json) reúne a validação integral anterior e a nova execução local do notebook do Parlamento, com ambiente, células, registros e bloqueios observados. Uma validação local não comprova que a sessão hospedada do Google Colab executou o notebook; essa confirmação requer uma execução na interface do Colab.

## Fontes bloqueadas

`Mercosul/Parlamento uruguaio/parlamento_uy.ipynb` tenta primeiro as [notícias do Parlamento](https://parlamento.gub.uy/noticiasyeventos/noticias) e depois as [notícias da Câmara de Representantes](https://www.diputados.gub.uy/noticias/). Em 01/10/2026, esses portais responderam HTTP 403 e 502, respectivamente, nesta rede. Se ambos falharem, o mesmo notebook percorre até 15 páginas dos [eventos da Biblioteca do Poder Legislativo](https://biblioteca.parlamento.gub.uy/eventos/), com limite ajustável em `MAX_LIBRARY_PAGES`. No teste local, foram 256 eventos com data em 15 páginas, apresentados em tabelas, séries temporais e gráficos de títulos. **Eventos da Biblioteca não substituem as notícias legislativas**: fonte e tipo permanecem identificados. O arquivo original na pasta compartilhada usa a mesma ordem de fontes e registra as tentativas no diagnóstico.
