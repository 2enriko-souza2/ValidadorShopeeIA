# 🤖 Validador de Expedição Shopee / Bling com Agente IA & Pesquisa RAG (XML / PDF)

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![AI Agent](https://img.shields.io/badge/AI_Agent-RAG_XML_/_PDF-8be9fd.svg?style=flat)]()
[![Tkinter](https://img.shields.io/badge/GUI-Tkinter_/_TTK_2_Abas-blue.svg?style=flat)]()
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/Database-SQLite-003B57.svg?style=flat&logo=sqlite&logoColor=white)](https://sqlite.org/)

> ### 🎯 Contexto & Evolução com Agente IA + RAG
> Evolução do **Validador de Expedição Shopee / Bling** dividido em **duas abas integradas** na janela principal:
> 1. **Aba 1 (`📦 Conferência & Bipagem de Expedição`)**: Controle operacional de bancada com leitor de código de barras (44 dígitos), sinalização visual por cores (🔴 Não Bipado, 🟡 Em Separação, 🟢 Pronto para Coleta), alertas sonoros e trava de **Cooldown de 300 segundos** entre o 1º e o 2º bip.
> 2. **Aba 2 (`🤖 Agente IA & Pesquisa RAG (XML / PDF)`)**: Motor de **Retrieval-Augmented Generation (RAG)** acoplado a um leitor automático de **XML (NF-e 4.00)** e **PDF (DANFE via PyPDF2)** que varre a pasta de importação (`xml_entrada/` e `xml_entrada/processados/`), cruza com o banco SQLite e retorna instantaneamente:
>    - 📄 **Número da Nota Fiscal (`nNF`)** e Chave de Acesso;
>    - 👤 **Nome do Cliente / Destinatário**, CPF/CNPJ e Cidade/UF;
>    - 📦🚗 **Produto / Item / Veículo que foi vendido**, SKU, quantidade e Valor Total (`R$`);
>    - 🕒 **Hora exata em que foi adicionado na pasta de importação**;
>    - 🚦 **Status atual de bipagem** (`🔴 Não Bipado`, `🟡 Em Separação` ou `🟢 Pronto para Coleta`).

---

## 📁 Arquitetura em Camadas (Padrão Java MVC / DAO / Service)

| Arquivo / Pacote | Equivalente Java | Para que serve? |
| :--- | :--- | :--- |
| [`src/Main.py`](../src/Main.py) | `Main.java` | Ponto de entrada que inicializa o classpath (`src/`) e abre a aplicação. |
| [`src/view/TelaPrincipal.py`](../src/view/TelaPrincipal.py) | Pacote `view` | Interface Gráfica com **2 Abas (`ttk.Notebook`)**: Aba 1 (Bipagem) e Aba 2 (Agente IA & RAG Explorer) + Janela Modal de Auditoria. |
| [`src/service/DocumentoParserService.py`](../src/service/DocumentoParserService.py) | Pacote `service` | Leitor e extrator estruturado de arquivos **XML (NF-e)** e **PDF (DANFE)** da pasta de importação (extrai Nº NF, Cliente, Produto/Veículo vendido, Valor e Horário de entrada na pasta). |
| [`src/service/AgenteRAGService.py`](../src/service/AgenteRAGService.py) | Pacote `service` | Motor **RAG (Indexação + Busca Semântica/Léxica BM25)** integrado a modelo LLM gratuito (sem necessidade de chave paga) + Sintetizador RAG Local instantâneo. |
| [`src/service/AuditoriaIAService.py`](../src/service/AuditoriaIAService.py) | Pacote `service` | Assistente de Auditoria focado na análise estatística de lotes específicos. |
| [`src/dao/PedidoDAO.py`](../src/dao/PedidoDAO.py) | Pacote `dao` | Camada de persistência SQLite (`pedidos.db`), gestão de lotes, trava de cooldown de 300s e exportação CSV. |
| [`src/service/XmlService.py`](../src/service/XmlService.py) | Pacote `service` | Watcher em segundo plano da pasta `xml_entrada/`. |
| [`src/controller/RedeController.py`](../src/controller/RedeController.py) | Pacote `controller` | Servidor FastAPI + WebSockets para sincronização multi-PC em tempo real (< 50ms). |
