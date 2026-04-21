### *Coleta, análise e exportação de notícias de múltiplas fontes institucionais*  
---

## Visão Geral

Este repositório contém **scrapers independentes** para coleta, análise e visualização de notícias e documentos oficiais de **fontes institucionais nacionais e internacionais**.

Cada fonte possui:
- Notebook próprio (Jupyter)
- Lógica de scraping isolada
- Tratamento de dados com `pandas`
- Gráficos interativos (`plotly`)
- Exportação para CSV
- Estrutura opcional para SQLite

---

## Fontes Monitoradas

| Fonte | URL Base | Tipo de Conteúdo |
|------|---------|------------------|
| **CGI.br** | `https://cgi.br/noticias/indice/` | Notícias + atas de reuniões |
| **NIC.br** | `https://www.nic.br/noticias/` | Notícias institucionais sobre internet e governança |
| **ANPD** | `https://www.gov.br/anpd/pt-br/assuntos/noticias` | Notícias oficiais sobre proteção de dados |
| **Mercociudades** | `https://mercociudades.org/noticias/` | Notícias de cidades da América Latina |
| **União Europeia** | `https://european-union.europa.eu/news-and-events/news-and-stories_en` | Notícias oficiais da UE |
| **CGD (CGLU)** | `https://www.cglu.org/es/noticias` | Notícias globais de governos locais |

---

## Tecnologias Utilizadas

| Tecnologia | Uso |
|-----------|-----|
| `requests` + `BeautifulSoup` | Coleta de HTML estático |
| `Selenium` + `webdriver-manager` | Páginas com conteúdo dinâmico |
| `pandas` | Limpeza, estruturação e análise dos dados |
| `plotly` | Gráficos interativos |
| `SQLite` | Estrutura de banco de dados (opcional) |

---

## Scrapers Disponíveis

### 1. **CGI.br Scraper**
- **Paginação**: `page:1`, `page:2`, … (uso de `:`)
- **Coleta**:
  - Título
  - Data
  - Link
  - Tipo de conteúdo (notícia ou ata)
- **Observação**: atas de reuniões são coletadas separadamente
- **Saída média**: ~200 registros

---

### 2. **NIC.br Scraper**
- **Paginação**: navegação sequencial por páginas
- **Coleta**:
  - Título
  - Data
  - Link
  - Texto completo da notícia
- **Temas recorrentes**:
  - Governança da internet
  - Infraestrutura digital
  - Segurança e políticas públicas
- **Saída média**: ~100 notícias recentes
- **Extras**:
  - Filtro por palavras-chave
  - Gráficos de frequência temática

---

### 3. **ANPD Scraper**
- **Fonte**: Autoridade Nacional de Proteção de Dados (Brasil)
- **Paginação**: páginas institucionais padrão do `gov.br`
- **Coleta**:
  - Título
  - Data
  - Link
  - Conteúdo textual
- **Temas principais**:
  - LGPD
  - Fiscalização
  - Regulamentações
  - Autorizações e sanções
- **Saída média**: ~80–120 notícias
- **Observação técnica**:
  - Conteúdo majoritariamente estático (não exige Selenium)

---

### 4. **Mercociudades Scraper**
- **Paginação**: `/page/N/`
- **Coleta**:
  - Título
  - Data
  - Resumo
  - Link
- **Idioma**: espanhol
- **Filtro**: palavras-chave configuráveis
- **Saída média**: ~150 notícias

---

### 5. **União Europeia Scraper**
- **Paginação**: `?page=36` até `?page=1`
- **Tecnologia**: Selenium (conteúdo dinâmico)
- **Coleta**:
  - Título
  - Data
  - Tags
  - Imagem
  - Texto completo
- **Saída média**: ~360 notícias
- **Observação**: scraping mais pesado, execução mais lenta

---

### 6. **CGD (CGLU) Scraper**
- **Paginação**: `/page/N/`
- **Idioma**: espanhol (principal)
- **Coleta**:
  - Título
  - Data
  - Categoria
  - Resumo
  - Link
- **Escopo temporal**: últimos ~2 anos
- **Saída média**: ~180 notícias

---

## Saídas Geradas

Cada notebook gera:

- 📊 **Gráficos interativos** (Plotly)
- 📋 **DataFrames organizados para análise**

----

## Observação Importante

> Sites que aplicam **bloqueio ativo contra scraping automatizado** (HTTP 403, WAF, fingerprinting) **não são forçados** neste projeto, respeitando boas práticas técnicas e éticas.
