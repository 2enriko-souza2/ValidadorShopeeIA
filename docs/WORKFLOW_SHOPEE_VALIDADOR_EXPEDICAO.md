# 📌 WORKFLOW & CONTEXTO DO PROJETO: VALIDADOR DE EXPEDIÇÃO (SHOPEE / BLING)

> **Data de Atualização**: 02 de Setembro de 2026  
> **Status do Projeto**: Versão 2.0 Concluída, Testada, Zerada e Entregue.

---

## 📍 Localização dos Projetos e Arquivos Chave

- **Pasta Raiz do Projeto**: `C:\Users\enrik\Desktop\TesteShopee`
- **Executável Final (`.exe`)**: `C:\Users\enrik\Desktop\TesteShopee\dist\ValidadorExpedicao.exe`
- **Atalho na Área de Trabalho**: `C:\Users\enrik\Desktop\Validador de Expedição.lnk`
- **Pasta de Entrada de XMLs**: `C:\Users\enrik\Desktop\TesteShopee\xml_entrada`
- **Pasta de XMLs Processados**: `C:\Users\enrik\Desktop\TesteShopee\xml_entrada\processados`
- **Banco de Dados SQLite**: `C:\Users\enrik\Desktop\TesteShopee\pedidos.db`
- **Documentação Local**: `C:\Users\enrik\Desktop\TesteShopee\README.md`

---

## 🎯 Onde Paramos (Estado Atual do Desenvolvimento)

Todas as funcionalidades solicitadas para a **Versão 2.0** foram desenvolvidas, integradas e validadas com sucesso.

### 📋 Os 5 Parâmetros Atendidos:

1. **Importação de XMLs**:
   - Suporte a leitura de XMLs da Shopee / Bling (extração automática de chave de 44 dígitos e `nNF`).
   - Leitura de arquivos pela pasta monitorada `xml_entrada/`, pelo botão `🔄 Sincronizar Pasta` ou pelo seletor `📂 Carregar XMLs`.

2. **Exibição Permanente na Tela**:
   - Nenhuma nota é removida da tela durante a bipagem para evitar furos de estoque/conferência.
   - Tabela permanente (`ttk.Treeview`) com colunas: `#`, `Nº NF`, `Status`, `Chave de Acesso (44 dígitos)`, `Data Importação`, `Último Bip`.

3. **Status por Cores & Modo Tela Cheia**:
   - 🔴 **Vermelho (Não Bipado)**: XML importado / DANFE impresso.
   - 🟡 **Amarelo (Em Separação)**: 1º Bip efetuado (entrada na separação).
   - 🟢 **Verde (Pronto para Coleta)**: 2º Bip efetuado (pedido conferido e liberado).
   - Modo **Tela Cheia** alternável por `F11`, `Esc` ou pelo botão `🖥️ Tela Cheia`.

4. **Alertas Sonoros Inteligentes (`winsound`)**:
   - 🔊 **Som Grave (500 Hz)**: Transição válida de status (🔴 ➔ 🟡 ou 🟡 ➔ 🟢).
   - 🔊 **Som Agudo (2000 Hz)**: Alerta de **Nota Duplicada** (já bipada).
   - 🔊 **Som Agudo + Grave Consecutivos (2200 Hz ➔ 450 Hz)**: Alerta de **Nota Fora do Lote**.

5. **Sincronização Multi-Computador & Banco de Dados Persistente**:
   - Banco SQLite (`pedidos.db`) contra perdas e quedas de energia com carimbo de data/hora automático no nível de segundos.
   - Servidor FastAPI + WebSockets (`server.py`) para sincronizar a estação de Separação (Computador 1) e a estação de Coleta (Computador 2) em tempo real (< 50ms).
   - Sistema de Lotes (`➕ Novo Lote`) para arquivar o lote anterior no banco e zerar a tela sem poluição visual.

6. **Trava de Cooldown de 5 Minutos (300s) para o 2º Bip**:
   - Proteção contra bipagens duplas acidentais: o 2º bip (Coleta - 🟢) só é aceito após 5 minutos do 1º bip (Separação - 🟡).
   - Exibe contagem regressiva visual de aviso (`Aguardando Xm Ys`) e som de alerta em tentativas antecipadas.

7. **Painel de Auditoria & Exportação de CSV**:
   - Botão **`📜 Auditoria & Relatórios`** abre janela modal para navegar por qualquer lote (Ativo ou Arquivado) por data/hora de criação.
   - Mostra totais por status (🔴 Não Bipado, 🟡 Em Separação, 🟢 Pronto para Coleta) e horários detalhados (Importação, 1º Bip, 2º Bip e Duração de Separação).
   - Botão **`📥 Exportar CSV de Auditoria`** gera arquivo CSV com formatação UTF-8 BOM pronto para Excel.

---

## 🧹 Estado dos Dados
- **Banco de Dados `pedidos.db`**: Limpo e zerado de testes antigos. Atualmente pronto com o lote inicial zerado `LOTE_20260902_012829`.
- **Pasta `xml_entrada/`**: Limpa, sem arquivos pendentes de teste.

---

## 🛠️ Como Retomar ou Fazer Futuras Manutenções

1. **Para Rodar o Código em Desenvolvimento**:
   ```powershell
   cd "C:\Users\enrik\Desktop\TesteShopee"
   .\venv\Scripts\python.exe app.py
   ```

2. **Para Iniciar o Servidor WebSocket Multi-PC**:
   ```powershell
   .\venv\Scripts\python.exe server.py
   ```

3. **Para Recompilar o Executável `.exe`**:
   ```powershell
   cd "C:\Users\enrik\Desktop\TesteShopee"
   .\venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --name "ValidadorExpedicao" app.py
   Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, ValidadorExpedicao.spec
   ```
