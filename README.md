# 🤖 Validador de Expedição Shopee / Bling com Inteligência Artificial Integrada

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![OpenAI](https://img.shields.io/badge/AI-GPT--4o--mini-412991.svg?style=flat&logo=openai&logoColor=white)](https://openai.com/)
[![Tkinter](https://img.shields.io/badge/GUI-Tkinter_/_TTK-blue.svg?style=flat)]()
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/Database-SQLite-003B57.svg?style=flat&logo=sqlite&logoColor=white)](https://sqlite.org/)

> ### 🎯 Contexto & Evolução com IA
> Evolução do **Validador de Expedição Shopee / Bling** com um **Assistente de Auditoria Logística baseado em IA (`GPT-4o-mini`)** acoplado diretamente ao banco de dados SQLite.
> Além de validar 100% da saída de mercadorias com leitores de código de barras, alertas sonoros e trava de cooldown de 300s entre bips, o auditor pode consultar a IA com 1 clique ou em linguagem natural para:
> - **Listar todas as notas que ainda faltam bipar** (`🔴 Não Bipadas`);
> - **Listar todas as notas já bipadas** (`🟡 Em Separação` e `🟢 Prontas para Coleta`);
> - **Obter um diagnóstico e status geral completo do lote** (progresso percentual, horários, gargalos e alertas de Cooldown/Fora do Lote).

---

## 📁 Arquitetura em Camadas (Padrão Java MVC / DAO / Service)

| Arquivo / Pacote | Para que serve? | Como funciona? |
| :--- | :--- | :--- |
| [`src/Main.py`](../src/Main.py) | **Ponto de Entrada (`main`)** | Inicializa os pacotes da aplicação e abre a janela principal do sistema. |
| [`src/view/TelaPrincipal.py`](../src/view/TelaPrincipal.py) | **Interface Gráfica & Painel IA (View)** | Construída em Tkinter/TTK; gerencia a bipagem em tempo real e inclui o painel **🤖 Assistente IA de Auditoria** dentro da janela de Auditoria. |
| [`src/service/AuditoriaIAService.py`](../src/service/AuditoriaIAService.py) | **Serviço de Inteligência Artificial (AI Service)** | Extrai o contexto estruturado do lote no SQLite e consulta o modelo `gpt-4o-mini` (com fallback local automático). |
| [`src/dao/PedidoDAO.py`](../src/dao/PedidoDAO.py) | **Camada de Dados & Persistência (DAO / SQLite)** | Controla o banco de dados, lotes, histórico de bips, cooldown de 300s e exportação CSV. |
| [`src/service/XmlService.py`](../src/service/XmlService.py) | **Serviço Observador e Leitor de XML (Service)** | Monitora a pasta `xml_entrada/` e extrai a chave de 44 dígitos e número da NF-e. |
| [`src/controller/RedeController.py`](../src/controller/RedeController.py) | **Controlador de Sincronização em Rede (Controller)** | Servidor FastAPI + WebSockets para múltiplas estações em tempo real (< 50ms). |

---

## 🚀 Como Executar

1. Crie um arquivo `.env` na raiz do projeto contendo sua chave:
   ```env
   OPENAI_API_KEY=sua_chave_aqui
   ```
2. Instale as dependências e inicie o sistema:
   ```bash
   pip install -r requirements.txt
   python src/Main.py
   ```
