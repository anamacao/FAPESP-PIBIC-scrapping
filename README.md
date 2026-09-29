# FAPESP PIBIC — coleta e análise de notícias

O projeto mantém **21 notebooks originais** em [`Mercosul/`](Mercosul/) e [`UE/`](UE/). Eles fazem coleta, análise ou gráficos. Nenhum notebook novo foi criado na atualização de setembro de 2026.

## Como executar

1. Abra o notebook desejado no Google Colab e execute **Ambiente de execução → Executar tudo**. Cada coletor usa um banco SQLite temporário próprio da sessão; reiniciar a sessão apaga esse banco.
2. Os coletores com muitas páginas históricas começam pela página mais recente. A variável `TOTAL_PAGES`, `MAX_PAGES` ou argumento `max_pages` no notebook controla quantas páginas visitar. Aumente-a apenas quando precisar recuperar o histórico; uma página pode abrir dezenas de notícias.
3. [`UE/charts.ipynb`](UE/charts.ipynb) e [`UE/database_analysis.ipynb`](UE/database_analysis.ipynb) conseguem usar o [CSV acumulado](data/news.csv) do GitHub quando nenhum banco SQLite está disponível na sessão. O CSV cobre inicialmente NIC.br, EDPB, Mercociudades e Senado Federal; não inclui automaticamente os outros coletores.
4. Confira as mensagens de coleta e a quantidade de linhas antes de interpretar os gráficos. Células executadas sem erro e com zero notícias não confirmam que a fonte está funcionando.

Os notebooks atualizados usam `requests`, `beautifulsoup4`, `pandas` e `plotly`; alguns gráficos também usam `matplotlib`, `seaborn` e `wordcloud`. `UE/uniaoEuropeia.ipynb` lê o HTML público sem Chrome ou Selenium. `google_transparency.ipynb` mostra apenas contagens de links realmente coletados, sem valores regionais simulados.

## Coleta semanal

O [workflow semanal](.github/workflows/fapesp-weekly.yml) roda às sextas-feiras às 07h de Brasília e pode ser iniciado manualmente. Ele atualiza `data/news.csv` para **quatro fontes**: NIC.br, EDPB, Mercociudades e Senado Federal. [`data/runs/latest.json`](data/runs/latest.json) registra erros, registros novos e a checagem de sintaxe dos 21 notebooks. A checagem de sintaxe não executa as células.

O domínio de Mercociudades respondeu HTTP 403 no ambiente do GitHub Actions pela API pública, embora o notebook tenha coletado dados em uma execução local. A rotina semanal agora tenta o [RSS oficial](https://mercociudades.org/feed/) quando a API retorna 403. O relatório identifica `method: official_rss_after_api_403`; só considera a janela de sete dias coberta quando o item mais antigo do feed antecede o início dela. Se o RSS também falhar ou trouxer poucos itens, o workflow preserva as notícias antigas e sinaliza cobertura parcial ou falha.

## Validação local dos notebooks

[`scripts/check_notebooks.py`](scripts/check_notebooks.py) executa as células originais em ordem, em um diretório temporário por notebook, e considera falha tanto uma exceção quanto um conjunto de dados vazio. Ele usa um interpretador IPython no processo porque este ambiente não permite iniciar o kernel Jupyter por sockets locais. Para reproduzir a verificação local:

```bash
python -m pip install requests beautifulsoup4 pandas plotly ipython nbformat jinja2 matplotlib seaborn wordcloud
python scripts/check_notebooks.py Mercosul/nic_.ipynb UE/charts.ipynb --output resultado.json
```

A opção `--diagnostic` reduz temporariamente a coleta a uma página e pula células de instalação no teste; **não altera os arquivos** e não deve ser usada como prova de execução integral. O relatório versionado em [`data/runs/notebooks-20260929.json`](data/runs/notebooks-20260929.json) identifica ambiente, células, notícias e bloqueios observados. Uma validação local não comprova que a sessão hospedada do Google Colab executou o notebook; essa confirmação requer uma execução na interface do Colab.

## Fontes bloqueadas

`Mercosul/Parlamento uruguaio/parlamento_uy.ipynb` tenta primeiro a página oficial de notícias do Parlamento. Em 29/09/2026 ela respondeu HTTP 403 neste ambiente. Nesse caso, o mesmo notebook recorre a [`biblioteca.parlamento.gub.uy/eventos/`](https://biblioteca.parlamento.gub.uy/eventos/), outro endereço oficial do Poder Legislativo. A execução local obteve 18 eventos com título, data e link, separados pela coluna `source` e pela categoria `Eventos da Biblioteca`. **Eventos da Biblioteca não substituem as notícias legislativas**; os gráficos distinguem o tipo de registro. O arquivo original na pasta compartilhada também consulta essa fonte alternativa.
