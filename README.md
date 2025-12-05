### *Coleta, análise e exportação de notícias de múltiplas fontes institucionais*  
---

## Visão Geral

Este repositório contém **scrapers independentes** para coletar notícias e documentos oficiais:

| Fonte | URL Base | Tipo de Conteúdo |
|-------|----------|------------------|
| **CGI.br** | `https://cgi.br/noticias/indice/` | Notícias + atas de reuniões |
| **Mercociudades** | `https://mercociudades.org/noticias/` | Notícias de cidades da América Latina |
| **União Europeia** | `https://european-union.europa.eu/news-and-events/news-and-stories_en` | Notícias oficiais da UE |
| **CGD (Cidades e Governos Locais Unidos)** | `https://www.cglu.org/es/noticias` | Notícias globais de governos locais |

Cada scraper é **autônomo**, funciona em **Jupyter Notebook** e gera:  
- Tabelas interativas  
- Gráficos (Plotly)  
- Arquivos CSV  
- Esqueleto para banco SQLite

---

## Tecnologias Comuns

| Tecnologia | Uso |
|------------|-----|
| `requests` + `BeautifulSoup` | Coleta HTML |
| `Selenium` + `webdriver-manager` | Páginas com JavaScript |
| `pandas` | Manipulação de dados |
| `plotly` | Gráficos interativos |
| `SQLite` | Estrutura de banco (opcional) |

---

## Scrapers Disponíveis

### 1. **CGI.br Scraper**
- **Paginação**: `page:1`, `page:2`, … (com `:`)  
- **Coleta**: título, data, link, fonte  
- **Reuniões**: atas separadas  
- **Saída**: ~200 notícias + atas

### 2. **Mercociudades Scraper**
- **Paginação**: padrão `/page/N/`  
- **Coleta**: título, data, resumo, link  
- **Filtro**: palavras-chave em português  
- **Saída**: ~150 notícias

### 3. **União Europeia Scraper**
- **Paginação**: `?page=36` até `?page=1`  
- **Coleta**: título, data, tags, imagem, parágrafos completos  
- **Selenium**: para conteúdo dinâmico  
- **Saída**: ~360 notícias

### 4. **CGD (CGLU) Scraper**
- **Paginação**: `/page/N/` (ex: `/page/2/`)  
- **Coleta**: título, data, link, resumo, categoria  
- **Idioma**: espanhol (principal)  
- **Saída**: ~180 notícias (últimos 2 anos)

---
