import os
import sys
import time
import shutil
import threading
import winsound
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from dao import PedidoDAO as database
from service import XmlService as watcher
from service import AuditoriaIAService
from service import AgenteRAGService


def tocar_som(tipo: str):
    """
    Emite alertas sonoros assíncronos via winsound sem travar a interface gráfica.
    - SUCESSO: Som Grave (500Hz, 300ms) -> Transição válida (🔴->🟡 ou 🟡->🟢)
    - DUPLICADO: Som Agudo (2000Hz, 300ms) -> Nota duplicada ou já concluída
    - FORA_DO_LOTE: Som Agudo+Grave (2200Hz 200ms -> 450Hz 400ms) -> Nota fora do lote
    """
    def _emitir():
        try:
            if tipo == "SUCESSO":
                winsound.Beep(500, 300)
            elif tipo == "DUPLICADO":
                winsound.Beep(2000, 300)
            elif tipo == "FORA_DO_LOTE":
                winsound.Beep(2200, 200)
                winsound.Beep(450, 400)
        except Exception as e:
            print(f"Erro ao reproduzir alerta sonoro ({tipo}): {e}")

    threading.Thread(target=_emitir, daemon=True).start()


class ValidadorExpedicaoApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Validador de Expedição + Agente RAG IA (XML / PDF) - Shopee / Bling")
        self.geometry("1220x780")
        self.minsize(960, 640)

        # Estado do modo Tela Cheia
        self.is_fullscreen = False
        self.rag_em_execucao = False

        # Palette de Cores do Tema Escuro
        self.bg_color = "#1e1e2e"       # Fundo principal escuro
        self.card_bg = "#282a36"        # Fundo dos cards e contêineres
        self.card_border = "#44475a"    # Borda dos cards
        self.fg_color = "#f8f8f2"       # Cor de texto primária
        self.accent_color = "#bd93f9"   # Purple/Lavender accent
        self.green_color = "#50fa7b"    # Verde para Sucesso / Pronto
        self.yellow_color = "#f1fa8c"   # Amarelo para Separação
        self.red_color = "#ff5555"      # Vermelho para Alerta / Não Bipado

        self.configure(bg=self.bg_color)

        # Garantir inicialização da base de dados SQLite
        database.init_db()

        # Variável para rastrear hash do estado do banco
        self.last_db_state_hash = None

        # Estilizar TTK (incluindo Abas / Notebook)
        self.setup_styles()

        # Construir elementos gráficos (Abas 1 e 2)
        self.criar_interface()

        # Vinculação de teclas de atalho globais
        self.bind("<F11>", self.toggle_fullscreen)
        self.bind("<Escape>", self.exit_fullscreen)

        # Atualizar dados iniciais (Lote Ativo e Índice RAG XML/PDF)
        self.carregar_dados_lote_ativo()
        self.atualizar_aba_rag_documentos()

        # Iniciar polling e sincronização periódica da UI (1s)
        self.checar_atualizacoes_db()

        # Iniciar manutenção de foco automático contínuo no campo de bipagem (apenas na Aba 1)
        self.manter_foco_continuo()

        # Tentar conectar WebSocket em background se servidor estiver ativo
        self.iniciar_websocket_listener()

    def setup_styles(self):
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        # Configuração de temas e fontes globais
        self.style.configure(".", background=self.bg_color, foreground=self.fg_color, font=("Segoe UI", 10))
        self.style.configure("Main.TFrame", background=self.bg_color)
        self.style.configure("Card.TFrame", background=self.card_bg, relief="flat")

        # Estilo das Abas (Notebook)
        self.style.configure(
            "TNotebook",
            background=self.bg_color,
            borderwidth=0,
            tabmargins=[2, 5, 2, 0]
        )
        self.style.configure(
            "TNotebook.Tab",
            background="#282a36",
            foreground="#f8f8f2",
            padding=[18, 8],
            font=("Segoe UI", 11, "bold"),
            borderwidth=0
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", "#6272a4"), ("active", "#44475a")],
            foreground=[("selected", "#ffffff"), ("active", "#ffffff")]
        )

        # Botões Customizados
        self.style.configure(
            "Primary.TButton",
            font=("Segoe UI", 10, "bold"),
            background="#44475a",
            foreground="#ffffff",
            padding=(12, 7),
            borderwidth=0
        )
        self.style.map("Primary.TButton", background=[("active", "#6272a4")])

        self.style.configure(
            "Accent.TButton",
            font=("Segoe UI", 10, "bold"),
            background="#6272a4",
            foreground="#ffffff",
            padding=(12, 7),
            borderwidth=0
        )
        self.style.map("Accent.TButton", background=[("active", "#bd93f9")])

        self.style.configure(
            "Danger.TButton",
            font=("Segoe UI", 10, "bold"),
            background="#ff5555",
            foreground="#ffffff",
            padding=(12, 7),
            borderwidth=0
        )
        self.style.map("Danger.TButton", background=[("active", "#ff6e6e")])

        # Estilo da Treeview (Tabela Dinâmica de Pedidos)
        self.style.configure(
            "Treeview",
            background="#21222c",
            foreground="#f8f8f2",
            fieldbackground="#21222c",
            rowheight=32,
            font=("Segoe UI", 10)
        )
        self.style.configure(
            "Treeview.Heading",
            background="#282a36",
            foreground="#bd93f9",
            font=("Segoe UI", 10, "bold"),
            padding=6,
            relief="flat"
        )
        self.style.map("Treeview.Heading", background=[("active", "#44475a")])
        self.style.map("Treeview", background=[("selected", "#44475a")], foreground=[("selected", "#ffffff")])

        # Scrollbars escuras
        self.style.configure(
            "Vertical.TScrollbar",
            gripcount=0,
            background="#282a36",
            darkcolor="#1e1e2e",
            lightcolor="#44475a",
            troughcolor="#1e1e2e",
            bordercolor="#1e1e2e",
            arrowcolor="#f8f8f2"
        )
        self.style.configure(
            "Horizontal.TScrollbar",
            gripcount=0,
            background="#282a36",
            darkcolor="#1e1e2e",
            lightcolor="#44475a",
            troughcolor="#1e1e2e",
            bordercolor="#1e1e2e",
            arrowcolor="#f8f8f2"
        )

    def criar_interface(self):
        # Container Principal com Abas (Notebook)
        root_container = ttk.Frame(self, style="Main.TFrame")
        root_container.pack(fill="both", expand=True, padx=12, pady=10)

        self.notebook = ttk.Notebook(root_container)
        self.notebook.pack(fill="both", expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        # Criar Aba 1 (Validador Operacional) e Aba 2 (Agente IA & Pesquisa RAG XML/PDF)
        self.tab_operacao = ttk.Frame(self.notebook, style="Main.TFrame")
        self.tab_agente_rag = ttk.Frame(self.notebook, style="Main.TFrame")

        self.notebook.add(self.tab_operacao, text="📦 Conferência & Bipagem de Expedição")
        self.notebook.add(self.tab_agente_rag, text="🤖 Agente IA & Pesquisa RAG (XML / PDF)")

        self._construir_aba_operacao(self.tab_operacao)
        self._construir_aba_agente_rag(self.tab_agente_rag)

        # Barra de Status Inferior Global
        self.statusbar = tk.Label(
            root_container,
            text="Sistema Pronto | SQLite + Motor RAG (XML/PDF) Operacionais | Pressione F11 para Tela Cheia | Esc para Sair",
            font=("Segoe UI", 9),
            bg=self.bg_color,
            fg="#6272a4",
            anchor="w"
        )
        self.statusbar.pack(fill="x", pady=(6, 0))

    # ==============================================================================
    # CONSTRUÇÃO DA ABA 1: CONFERÊNCIA & BIPAGEM
    # ==============================================================================
    def _construir_aba_operacao(self, parent_frame):
        main_container = ttk.Frame(parent_frame, style="Main.TFrame")
        main_container.pack(fill="both", expand=True, padx=8, pady=10)

        # 1. HEADER & BARRA DE AÇÕES
        header_frame = ttk.Frame(main_container, style="Main.TFrame")
        header_frame.pack(fill="x", pady=(0, 12))

        title_label = tk.Label(
            header_frame,
            text="📦 Validador de Expedição",
            font=("Segoe UI", 16, "bold"),
            bg=self.bg_color,
            fg="#bd93f9"
        )
        title_label.pack(side="left")

        self.lbl_lote_code = tk.Label(
            header_frame,
            text="Lote: Carregando...",
            font=("Segoe UI", 10, "italic"),
            bg=self.bg_color,
            fg="#6272a4"
        )
        self.lbl_lote_code.pack(side="left", padx=15)

        btn_frame = ttk.Frame(header_frame, style="Main.TFrame")
        btn_frame.pack(side="right")

        self.btn_sincronizar = ttk.Button(
            btn_frame,
            text="🔄 Sincronizar Pasta",
            style="Primary.TButton",
            command=self.sincronizar_pasta_entrada
        )
        self.btn_sincronizar.pack(side="left", padx=4)

        self.btn_carregar = ttk.Button(
            btn_frame,
            text="📂 Carregar XMLs",
            style="Primary.TButton",
            command=self.carregar_xmls
        )
        self.btn_carregar.pack(side="left", padx=4)

        self.btn_novo_lote = ttk.Button(
            btn_frame,
            text="➕ Novo Lote",
            style="Danger.TButton",
            command=self.confirmar_novo_lote
        )
        self.btn_novo_lote.pack(side="left", padx=4)

        self.btn_auditoria = ttk.Button(
            btn_frame,
            text="📜 Auditoria",
            style="Primary.TButton",
            command=self.abrir_janela_auditoria
        )
        self.btn_auditoria.pack(side="left", padx=4)

        self.btn_ir_ia = ttk.Button(
            btn_frame,
            text="🤖 Abrir Agente RAG",
            style="Accent.TButton",
            command=lambda: self.notebook.select(self.tab_agente_rag)
        )
        self.btn_ir_ia.pack(side="left", padx=4)

        self.btn_fullscreen = ttk.Button(
            btn_frame,
            text="🖥️ Tela Cheia",
            style="Primary.TButton",
            command=self.toggle_fullscreen
        )
        self.btn_fullscreen.pack(side="left", padx=4)

        # 2. CARDS DE ESTATÍSTICAS
        stats_frame = ttk.Frame(main_container, style="Main.TFrame")
        stats_frame.pack(fill="x", pady=(0, 12))

        for i in range(4):
            stats_frame.columnconfigure(i, weight=1, uniform="stat_card")

        card1 = tk.Frame(stats_frame, bg=self.card_bg, highlightbackground=self.card_border, highlightthickness=1)
        card1.grid(row=0, column=0, padx=4, sticky="ew")
        tk.Label(card1, text="Total de Notas", font=("Segoe UI", 10, "bold"), bg=self.card_bg, fg="#8be9fd").pack(pady=(8, 2))
        self.lbl_card_total = tk.Label(card1, text="0", font=("Segoe UI", 20, "bold"), bg=self.card_bg, fg="#ffffff")
        self.lbl_card_total.pack(pady=(0, 8))

        card2 = tk.Frame(stats_frame, bg=self.card_bg, highlightbackground=self.card_border, highlightthickness=1)
        card2.grid(row=0, column=1, padx=4, sticky="ew")
        tk.Label(card2, text="🔴 Não Bipadas", font=("Segoe UI", 10, "bold"), bg=self.card_bg, fg="#ff5555").pack(pady=(8, 2))
        self.lbl_card_nao_bipadas = tk.Label(card2, text="0", font=("Segoe UI", 20, "bold"), bg=self.card_bg, fg="#ff5555")
        self.lbl_card_nao_bipadas.pack(pady=(0, 8))

        card3 = tk.Frame(stats_frame, bg=self.card_bg, highlightbackground=self.card_border, highlightthickness=1)
        card3.grid(row=0, column=2, padx=4, sticky="ew")
        tk.Label(card3, text="🟡 Em Separação", font=("Segoe UI", 10, "bold"), bg=self.card_bg, fg="#f1fa8c").pack(pady=(8, 2))
        self.lbl_card_em_separacao = tk.Label(card3, text="0", font=("Segoe UI", 20, "bold"), bg=self.card_bg, fg="#f1fa8c")
        self.lbl_card_em_separacao.pack(pady=(0, 8))

        card4 = tk.Frame(stats_frame, bg=self.card_bg, highlightbackground=self.card_border, highlightthickness=1)
        card4.grid(row=0, column=3, padx=4, sticky="ew")
        tk.Label(card4, text="🟢 Prontas para Coleta", font=("Segoe UI", 10, "bold"), bg=self.card_bg, fg="#50fa7b").pack(pady=(8, 2))
        self.lbl_card_pronto_coleta = tk.Label(card4, text="0", font=("Segoe UI", 20, "bold"), bg=self.card_bg, fg="#50fa7b")
        self.lbl_card_pronto_coleta.pack(pady=(0, 8))

        # 3. CAMPO DE BIPAGEM DE ALTA VISIBILIDADE
        bip_box = tk.Frame(main_container, bg=self.card_bg, highlightbackground="#6272a4", highlightthickness=2, bd=0)
        bip_box.pack(fill="x", pady=(0, 12), ipady=4)

        lbl_bip_title = tk.Label(
            bip_box,
            text="⚡ BIPAR DANFE (Chave de 44 Dígitos / Leitor de Código de Barras):",
            font=("Segoe UI", 11, "bold"),
            bg=self.card_bg,
            fg="#f8f8f2"
        )
        lbl_bip_title.pack(anchor="w", padx=15, pady=(8, 4))

        self.entry_bip = tk.Entry(
            bip_box,
            font=("Consolas", 16, "bold"),
            bg="#191622",
            fg="#50fa7b",
            insertbackground="#ffffff",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#44475a",
            bd=5
        )
        self.entry_bip.pack(fill="x", padx=15, pady=(0, 8))
        self.entry_bip.bind("<Return>", self.processar_bip)

        self.lbl_feedback = tk.Label(
            bip_box,
            text="Aguardando bipagem... (Foco automático ativo)",
            font=("Segoe UI", 11, "bold"),
            bg=self.card_bg,
            fg="#6272a4",
            pady=4
        )
        self.lbl_feedback.pack(fill="x", padx=15, pady=(0, 6))

        # 4. TABELA DINÂMICA DE PEDIDOS
        table_container = ttk.Frame(main_container, style="Main.TFrame")
        table_container.pack(fill="both", expand=True)

        table_header = tk.Label(
            table_container,
            text="📋 Lista de Pedidos do Lote Ativo (Exibição Permanente)",
            font=("Segoe UI", 11, "bold"),
            bg=self.bg_color,
            fg="#f8f8f2"
        )
        table_header.pack(anchor="w", pady=(0, 5))

        table_frame = ttk.Frame(table_container, style="Main.TFrame")
        table_frame.pack(fill="both", expand=True)

        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        columns = ("index", "numero_nf", "status", "chave", "data_importacao", "ultimo_bip")
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            style="Treeview",
            selectmode="browse"
        )

        self.tree.heading("index", text="#")
        self.tree.heading("numero_nf", text="Nº NF")
        self.tree.heading("status", text="Status")
        self.tree.heading("chave", text="Chave de Acesso (44 dígitos)")
        self.tree.heading("data_importacao", text="Data Importação")
        self.tree.heading("ultimo_bip", text="Último Bip")

        self.tree.column("index", width=50, minwidth=40, anchor="center")
        self.tree.column("numero_nf", width=110, minwidth=80, anchor="center")
        self.tree.column("status", width=180, minwidth=140, anchor="w")
        self.tree.column("chave", width=380, minwidth=280, anchor="w")
        self.tree.column("data_importacao", width=160, minwidth=120, anchor="center")
        self.tree.column("ultimo_bip", width=160, minwidth=120, anchor="center")

        self.tree.tag_configure("nao_bipado", foreground="#ff5555")
        self.tree.tag_configure("em_separacao", foreground="#f1fa8c")
        self.tree.tag_configure("pronto_coleta", foreground="#50fa7b")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview, style="Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set)

        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview, style="Horizontal.TScrollbar")
        self.tree.configure(xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

    # ==============================================================================
    # CONSTRUÇÃO DA ABA 2: AGENTE IA & PESQUISA RAG (XML / PDF)
    # ==============================================================================
    def _construir_aba_agente_rag(self, parent_frame):
        rag_container = ttk.Frame(parent_frame, style="Main.TFrame")
        rag_container.pack(fill="both", expand=True, padx=8, pady=10)

        # 1. Header da Aba RAG
        rag_header = ttk.Frame(rag_container, style="Main.TFrame")
        rag_header.pack(fill="x", pady=(0, 10))

        tk.Label(
            rag_header,
            text="🤖 Agente IA & Leitor RAG de Notas Fiscais (XML / PDF)",
            font=("Segoe UI", 15, "bold"),
            bg=self.bg_color,
            fg="#bd93f9"
        ).pack(side="left")

        self.lbl_rag_status = tk.Label(
            rag_header,
            text="📚 Base RAG: Carregando...",
            font=("Segoe UI", 10, "italic"),
            bg=self.bg_color,
            fg="#8be9fd"
        )
        self.lbl_rag_status.pack(side="left", padx=15)

        rag_btns = ttk.Frame(rag_header, style="Main.TFrame")
        rag_btns.pack(side="right")

        ttk.Button(
            rag_btns,
            text="📄 Importar XML / PDF p/ Pasta",
            style="Primary.TButton",
            command=self.importar_arquivos_rag
        ).pack(side="left", padx=4)

        ttk.Button(
            rag_btns,
            text="🔄 Reindexar Pasta XML / PDF",
            style="Accent.TButton",
            command=self.atualizar_aba_rag_documentos
        ).pack(side="left", padx=4)

        # 2. Tabela de Notas Extraídas da Pasta de Importação (XML / PDF)
        lbl_tbl_rag = tk.Label(
            rag_container,
            text="📂 Notas Fiscais Extraídas da Pasta de Importação (Clique em uma nota para ver a ficha completa):",
            font=("Segoe UI", 10, "bold"),
            bg=self.bg_color,
            fg="#f8f8f2"
        )
        lbl_tbl_rag.pack(anchor="w", pady=(0, 4))

        rag_table_frame = ttk.Frame(rag_container, style="Main.TFrame")
        rag_table_frame.pack(fill="both", expand=True, pady=(0, 10))
        rag_table_frame.rowconfigure(0, weight=1)
        rag_table_frame.columnconfigure(0, weight=1)

        cols_rag = ("numero_nf", "cliente", "produto_veiculo", "valor", "hora_pasta", "status", "arquivo")
        self.tree_rag = ttk.Treeview(
            rag_table_frame,
            columns=cols_rag,
            show="headings",
            style="Treeview",
            height=6,
            selectmode="browse"
        )

        self.tree_rag.heading("numero_nf", text="Nº Nota (NF)")
        self.tree_rag.heading("cliente", text="Nome do Cliente / Destinatário")
        self.tree_rag.heading("produto_veiculo", text="Produto / Item / Veículo Vendido")
        self.tree_rag.heading("valor", text="Valor Total")
        self.tree_rag.heading("hora_pasta", text="Hora Adicionado na Pasta")
        self.tree_rag.heading("status", text="Status Bipagem")
        self.tree_rag.heading("arquivo", text="Arquivo (XML/PDF)")

        self.tree_rag.column("numero_nf", width=95, anchor="center")
        self.tree_rag.column("cliente", width=220, anchor="w")
        self.tree_rag.column("produto_veiculo", width=360, anchor="w")
        self.tree_rag.column("valor", width=95, anchor="center")
        self.tree_rag.column("hora_pasta", width=155, anchor="center")
        self.tree_rag.column("status", width=170, anchor="w")
        self.tree_rag.column("arquivo", width=180, anchor="w")

        self.tree_rag.tag_configure("nao_bipado", foreground="#ff5555")
        self.tree_rag.tag_configure("em_separacao", foreground="#f1fa8c")
        self.tree_rag.tag_configure("pronto_coleta", foreground="#50fa7b")

        vsb_r = ttk.Scrollbar(rag_table_frame, orient="vertical", command=self.tree_rag.yview, style="Vertical.TScrollbar")
        hsb_r = ttk.Scrollbar(rag_table_frame, orient="horizontal", command=self.tree_rag.xview, style="Horizontal.TScrollbar")
        self.tree_rag.configure(yscrollcommand=vsb_r.set, xscrollcommand=hsb_r.set)

        self.tree_rag.grid(row=0, column=0, sticky="nsew")
        vsb_r.grid(row=0, column=1, sticky="ns")
        hsb_r.grid(row=1, column=0, sticky="ew")

        self.tree_rag.bind("<<TreeviewSelect>>", self.on_selecionar_nota_rag)

        # 3. Painel de Chat e Consultas Rápidas do Agente IA + RAG
        chat_card = tk.Frame(
            rag_container,
            bg=self.card_bg,
            highlightbackground="#bd93f9",
            highlightthickness=2,
            bd=0
        )
        chat_card.pack(fill="both", expand=True)

        # Barra de Botões de 1 Clique para o Agente
        quick_bar = tk.Frame(chat_card, bg=self.card_bg)
        quick_bar.pack(fill="x", padx=12, pady=(8, 6))

        tk.Label(
            quick_bar,
            text="⚡ Consultas Rápidas IA:",
            font=("Segoe UI", 10, "bold"),
            bg=self.card_bg,
            fg="#8be9fd"
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            quick_bar,
            text="🧾 Listar Todas (Nº NF, Cliente, Produto/Veículo e Hora)",
            style="Accent.TButton",
            command=lambda: self.executar_pergunta_rag(
                "Liste todas as notas fiscais da pasta informando: Número da Nota, Nome do Cliente, "
                "Produto/Veículo que foi vendido, Valor e a Hora em que foi adicionado na pasta de importação.",
                usar_llm=False
            )
        ).pack(side="left", padx=3)

        ttk.Button(
            quick_bar,
            text="🔴 Não Bipadas",
            style="Primary.TButton",
            command=lambda: self.executar_pergunta_rag(
                "Quais notas fiscais ainda não foram bipadas? Mostre número da nota, cliente, item/veículo vendido e hora de importação.",
                usar_llm=False
            )
        ).pack(side="left", padx=3)

        ttk.Button(
            quick_bar,
            text="🟢 Já Bipadas",
            style="Primary.TButton",
            command=lambda: self.executar_pergunta_rag(
                "Quais notas fiscais já foram bipadas? Mostre número da nota, cliente, item/veículo vendido e horários de bipagem.",
                usar_llm=False
            )
        ).pack(side="left", padx=3)

        ttk.Button(
            quick_bar,
            text="📊 Diagnóstico IA Completo",
            style="Primary.TButton",
            command=lambda: self.executar_pergunta_rag(
                "Faça um diagnóstico completo de todas as notas importadas: resumo do lote, clientes, "
                "produtos/veículos vendidos, horários de entrada na pasta e status de bipagem.",
                usar_llm=True
            )
        ).pack(side="left", padx=3)

        # Campo de Pergunta Livre ao Agente RAG
        ask_bar = tk.Frame(chat_card, bg=self.card_bg)
        ask_bar.pack(fill="x", padx=12, pady=(2, 8))

        self.entry_rag_query = tk.Entry(
            ask_bar,
            font=("Segoe UI", 11),
            bg="#191622",
            fg="#50fa7b",
            insertbackground="#ffffff",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#6272a4",
            bd=5
        )
        self.entry_rag_query.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_rag_query.insert(
            0,
            "Pesquise por Nº da Nota, Nome do Cliente, Produto/Veículo vendido ou pergunte ao Agente IA..."
        )
        self.entry_rag_query.bind("<FocusIn>", self._limpar_placeholder_aba_rag)
        self.entry_rag_query.bind("<Return>", lambda e: self.enviar_pergunta_aba_rag())

        ttk.Button(
            ask_bar,
            text="🤖 Perguntar ao Agente RAG",
            style="Accent.TButton",
            command=self.enviar_pergunta_aba_rag
        ).pack(side="right")

        # Área de Resposta do Agente RAG
        resp_frame = tk.Frame(chat_card, bg=self.card_bg)
        resp_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self.txt_rag_output = tk.Text(
            resp_frame,
            height=11,
            font=("Consolas", 10),
            bg="#191622",
            fg="#f8f8f2",
            insertbackground="#ffffff",
            relief="flat",
            wrap="word",
            padx=10,
            pady=8,
            state="disabled"
        )
        vsb_out = ttk.Scrollbar(resp_frame, orient="vertical", command=self.txt_rag_output.yview, style="Vertical.TScrollbar")
        self.txt_rag_output.configure(yscrollcommand=vsb_out.set)

        self.txt_rag_output.pack(side="left", fill="both", expand=True)
        vsb_out.pack(side="right", fill="y")

    # ==============================================================================
    # LÓGICA DA ABA 2 (AGENTE IA & RAG XML / PDF)
    # ==============================================================================
    def _limpar_placeholder_aba_rag(self, event=None):
        txt = self.entry_rag_query.get()
        if txt.startswith("Pesquise por Nº da Nota"):
            self.entry_rag_query.delete(0, tk.END)

    def _escrever_saida_rag(self, texto: str, cor: str = "#50fa7b"):
        self.txt_rag_output.configure(state="normal", fg=cor)
        self.txt_rag_output.delete("1.0", tk.END)
        self.txt_rag_output.insert(tk.END, texto)
        self.txt_rag_output.configure(state="disabled")

    def atualizar_aba_rag_documentos(self):
        """Reindexa a pasta xml_entrada (e processados) e preenche a tabela RAG."""
        try:
            docs = AgenteRAGService.indice_rag.indexar_tudo()
            self.lbl_rag_status.configure(
                text=f"📚 Base RAG Indexada: {len(docs)} documento(s) (XML/PDF)"
            )

            children = self.tree_rag.get_children()
            self.tree_rag.delete(*children)

            self._mapa_docs_rag = {}

            for idx, d in enumerate(docs, start=1):
                iid = str(d["chave"])
                self._mapa_docs_rag[iid] = d
                st = d["status_raw"]
                tag = (
                    "nao_bipado" if st == "NAO_BIPADO"
                    else "em_separacao" if st == "EM_SEPARACAO"
                    else "pronto_coleta" if st == "PRONTO_COLETA"
                    else ""
                )
                self.tree_rag.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        d["numero_nf"],
                        d["cliente_nome"],
                        d["produto_veiculo_vendido"],
                        f"R$ {d['valor_total_nf']}",
                        d["hora_adicionado_pasta"],
                        d["status_fmt"],
                        f"{d['nome_arquivo']} ({d['tipo_arquivo']})"
                    ),
                    tags=(tag,)
                )

            # Exibir automaticamente o resumo das notas indexadas na abertura
            if docs and not self.rag_em_execucao:
                resumo = AgenteRAGService.consultar_agente_rag(
                    "Liste todas as notas fiscais da pasta informando número da nota, cliente, item/veículo vendido e hora",
                    usar_llm_externo=False
                )
                self._escrever_saida_rag(resumo, cor="#50fa7b")
            elif not docs:
                self._escrever_saida_rag(
                    "📂 Nenhum arquivo XML ou PDF encontrado na pasta 'xml_entrada'.\n"
                    "Clique em '📄 Importar XML / PDF p/ Pasta' para adicionar notas fiscais.",
                    cor="#f1fa8c"
                )
        except Exception as e:
            self._escrever_saida_rag(f"Erro ao indexar pasta RAG: {e}", cor="#ff5555")

    def on_selecionar_nota_rag(self, event=None):
        sel = self.tree_rag.selection()
        if not sel:
            return
        iid = sel[0]
        doc = getattr(self, "_mapa_docs_rag", {}).get(iid)
        if not doc:
            return

        ficha = (
            "🔎 [FICHA DETALHADA DA NOTA FISCAL — EXTRAÇÃO RAG (XML / PDF)]\n"
            + ("═" * 75) + "\n\n"
            + AgenteRAGService.formatar_ficha_nota(doc)
        )
        if doc.get("cliente_endereco") and doc.get("cliente_endereco") != "-":
            ficha += f"\n   📍 Endereço Completo      : {doc['cliente_endereco']}"
        if doc.get("emitente_nome") and doc.get("emitente_nome") != "-":
            ficha += f"\n   🏢 Emitente da Nota       : {doc['emitente_nome']} ({doc['emitente_fantasia']}) — CNPJ: {doc['emitente_cnpj']}"

        self._escrever_saida_rag(ficha, cor="#8be9fd")

    def enviar_pergunta_aba_rag(self):
        pergunta = self.entry_rag_query.get().strip()
        if not pergunta or pergunta.startswith("Pesquise por Nº da Nota"):
            pergunta = "Liste todas as notas com número da nota, nome do cliente, produto/veículo vendido e hora de adição na pasta."
        self.executar_pergunta_rag(pergunta, usar_llm=True)

    def executar_pergunta_rag(self, pergunta: str, usar_llm: bool = True):
        if self.rag_em_execucao:
            return
        self.rag_em_execucao = True
        self._escrever_saida_rag(
            f"⏳ Agente RAG pesquisando nos arquivos XML/PDF e analisando sua solicitação...\n"
            f"Pergunta: \"{pergunta}\"",
            cor="#f1fa8c"
        )

        def _worker():
            try:
                resp = AgenteRAGService.consultar_agente_rag(pergunta=pergunta, usar_llm_externo=usar_llm)
                self.after(0, lambda: self._finalizar_execucao_rag(resp, "#50fa7b"))
            except Exception as e:
                self.after(0, lambda: self._finalizar_execucao_rag(f"❌ Erro no Agente RAG: {e}", "#ff5555"))

        threading.Thread(target=_worker, daemon=True).start()

    def _finalizar_execucao_rag(self, texto: str, cor: str):
        self.rag_em_execucao = False
        self._escrever_saida_rag(texto, cor=cor)

    def importar_arquivos_rag(self):
        """Permite selecionar arquivos XML ou PDF e copiá-los para a pasta de importação do RAG."""
        arquivos = filedialog.askopenfilenames(
            title="Selecione arquivos XML ou PDF de Notas Fiscais",
            filetypes=[("Notas Fiscais (XML / PDF)", "*.xml *.pdf"), ("Arquivos XML", "*.xml"), ("Arquivos PDF", "*.pdf")]
        )
        if not arquivos:
            return

        pasta_entrada = os.path.join(database.BASE_DIR, "xml_entrada")
        os.makedirs(pasta_entrada, exist_ok=True)

        copiados = 0
        for arq in arquivos:
            try:
                nome = os.path.basename(arq)
                destino = os.path.join(pasta_entrada, nome)
                if os.path.abspath(arq) != os.path.abspath(destino):
                    shutil.copy2(arq, destino)
                copiados += 1
            except Exception as e:
                print(f"Erro ao copiar {arq}: {e}")

        # Processar XMLs novos para o lote ativo também
        watcher.processar_pasta_existente()
        self.carregar_dados_lote_ativo()
        self.atualizar_aba_rag_documentos()
        messagebox.showinfo(
            "Importação RAG Concluída",
            f"✅ {copiados} arquivo(s) (XML/PDF) importado(s) e indexado(s) no motor RAG com sucesso!"
        )

    # ==============================================================================
    # LÓGICA DE FOCO AUTOMÁTICO E TECLAS DE ATALHO
    # ==============================================================================
    def on_tab_changed(self, event=None):
        """Quando o usuário troca de aba, atualiza o RAG ou devolve o foco ao leitor de código de barras."""
        try:
            aba_atual = self.notebook.select()
            if str(aba_atual) == str(self.tab_operacao):
                self.entry_bip.focus_set()
            else:
                self.atualizar_aba_rag_documentos()
        except Exception:
            pass

    def manter_foco_continuo(self):
        """
        Redireciona o foco para o campo de bipagem APENAS quando a Aba 1 (Operação) estiver ativa
        e o usuário não estiver em outro campo editável.
        """
        try:
            aba_atual = self.notebook.select()
            if str(aba_atual) == str(self.tab_operacao):
                focused = self.focus_get()
                if focused != self.entry_bip and focused is not None:
                    if not isinstance(focused, (tk.Entry, ttk.Entry, tk.Text)):
                        self.entry_bip.focus_set()
                elif focused is None:
                    self.entry_bip.focus_set()
        except Exception:
            pass

        self.after(500, self.manter_foco_continuo)

    def toggle_fullscreen(self, event=None):
        self.is_fullscreen = not self.is_fullscreen
        self.attributes("-fullscreen", self.is_fullscreen)

        if self.is_fullscreen:
            self.btn_fullscreen.configure(text="🗗 Sair Tela Cheia")
        else:
            self.btn_fullscreen.configure(text="🖥️ Tela Cheia")

    def exit_fullscreen(self, event=None):
        if self.is_fullscreen:
            self.is_fullscreen = False
            self.attributes("-fullscreen", False)
            self.btn_fullscreen.configure(text="🖥️ Tela Cheia")

    # ==============================================================================
    # ATUALIZAÇÃO DA INTERFACE E CARREGAMENTO DE DADOS (ABA 1)
    # ==============================================================================
    def calcular_hash_estado(self, pedidos):
        return "|".join(f"{p['id']}:{p['status']}:{p.get('data_bip_separacao')}:{p.get('data_bip_coleta')}" for p in pedidos)

    def carregar_dados_lote_ativo(self):
        try:
            dados_lote = database.listar_pedidos_lote_ativo()

            lote_info = dados_lote["lote"]
            estatisticas = dados_lote["estatisticas"]
            pedidos = dados_lote["pedidos"]

            hash_atual = f"{lote_info['id']}_" + self.calcular_hash_estado(pedidos)
            self.last_db_state_hash = hash_atual

            self.lbl_lote_code.configure(text=f"Lote Ativo: {lote_info['codigo']} (ID: {lote_info['id']})")

            self.lbl_card_total.configure(text=str(estatisticas["total"]))
            self.lbl_card_nao_bipadas.configure(text=str(estatisticas["nao_bipados"]))
            self.lbl_card_em_separacao.configure(text=str(estatisticas["em_separacao"]))
            self.lbl_card_pronto_coleta.configure(text=str(estatisticas["pronto_coleta"]))

            children = self.tree.get_children()
            self.tree.delete(*children)

            for idx, p in enumerate(pedidos, start=1):
                st = p["status"]
                if st == "NAO_BIPADO":
                    status_fmt = "🔴 Não Bipado"
                    tag = "nao_bipado"
                    ultimo_bip = "-"
                elif st == "EM_SEPARACAO":
                    status_fmt = "🟡 Em Separação"
                    tag = "em_separacao"
                    ultimo_bip = p.get("data_bip_separacao") or "-"
                elif st == "PRONTO_COLETA":
                    status_fmt = "🟢 Pronto para Coleta"
                    tag = "pronto_coleta"
                    ultimo_bip = p.get("data_bip_coleta") or p.get("data_bip_separacao") or "-"
                else:
                    status_fmt = st
                    tag = ""
                    ultimo_bip = "-"

                dt_imp = p.get("data_importacao") or "-"

                self.tree.insert(
                    "",
                    "end",
                    iid=str(p["id"]),
                    values=(
                        idx,
                        p["numero_nf"],
                        status_fmt,
                        p["chave"],
                        dt_imp,
                        ultimo_bip
                    ),
                    tags=(tag,)
                )

        except Exception as e:
            print(f"Erro ao carregar dados do lote ativo: {e}")

    def checar_atualizacoes_db(self):
        try:
            dados_lote = database.listar_pedidos_lote_ativo()
            pedidos = dados_lote["pedidos"]
            lote_id = dados_lote["lote"]["id"]
            hash_novo = f"{lote_id}_" + self.calcular_hash_estado(pedidos)

            if hash_novo != self.last_db_state_hash:
                self.carregar_dados_lote_ativo()
                self.atualizar_aba_rag_documentos()
        except Exception:
            pass
        finally:
            self.after(1000, self.checar_atualizacoes_db)

    def iniciar_websocket_listener(self):
        def _ws_worker():
            try:
                import websockets
                import json
                import asyncio

                async def client():
                    uri = "ws://localhost:8000/ws"
                    async with websockets.connect(uri) as websocket:
                        while True:
                            data = await websocket.recv()
                            msg = json.loads(data)
                            if msg.get("evento") in ("NOVA_BIPAGEM", "NOVO_PEDIDO", "NOVO_LOTE", "LOTE_ARQUIVADO"):
                                self.after(0, self.carregar_dados_lote_ativo)

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(client())
            except Exception:
                pass

        threading.Thread(target=_ws_worker, daemon=True).start()

    # ==============================================================================
    # PROCESSAMENTO DE BIP E AÇÕES DE BOTÕES
    # ==============================================================================
    def processar_bip(self, event=None):
        raw_input = self.entry_bip.get().strip()
        self.entry_bip.delete(0, tk.END)

        if not raw_input:
            return

        chave = database.sanitizar_chave(raw_input)
        res = database.bipar_pedido(chave=chave, estacao_id="GUI_LOCAL")

        resultado = res["resultado"]
        mensagem = res["mensagem"]

        if resultado in ("SUCESSO_SEPARACAO", "SUCESSO_COLETA"):
            tocar_som("SUCESSO")
            self.lbl_feedback.configure(
                text=f"✅ {mensagem}",
                bg="#1b4b27",
                fg="#50fa7b"
            )
            self.statusbar.configure(text=f"Última Ação: Bip registrado com sucesso ({chave[-8:] if len(chave)>=8 else chave})")

        elif resultado in ("DUPLICADO", "JA_CONCLUIDO", "COOLDOWN"):
            tocar_som("DUPLICADO")
            self.lbl_feedback.configure(
                text=f"⚠️ {mensagem}",
                bg="#4a4215",
                fg="#f1fa8c"
            )
            self.statusbar.configure(text=f"Última Ação: Alerta de Cooldown / Duplicado ({chave[-8:] if len(chave)>=8 else chave})")

        elif resultado == "FORA_DO_LOTE":
            tocar_som("FORA_DO_LOTE")
            self.lbl_feedback.configure(
                text=f"❌ {mensagem}",
                bg="#4a1c1d",
                fg="#ff5555"
            )
            self.statusbar.configure(text=f"Última Ação: ERRO - Chave fora do lote ({chave[-8:] if len(chave)>=8 else chave})")

        self.carregar_dados_lote_ativo()
        self.entry_bip.focus_set()

    def sincronizar_pasta_entrada(self):
        try:
            res = watcher.processar_pasta_existente()
            self.carregar_dados_lote_ativo()
            self.atualizar_aba_rag_documentos()

            inseridos = res.get("inseridos", 0)
            duplicados = res.get("duplicados", 0)

            if inseridos > 0:
                tocar_som("SUCESSO")
                msg_txt = f"✅ {inseridos} novo(s) arquivo(s) XML importado(s) com sucesso!"
                if duplicados > 0:
                    msg_txt += f"\n⚠️ {duplicados} arquivo(s) já existia(m) no lote atual."

                self.lbl_feedback.configure(
                    text=f"🔄 Sincronização: {inseridos} nova(s) nota(s) adicionada(s)!",
                    bg="#1b4b27",
                    fg="#50fa7b"
                )
                messagebox.showinfo("Sincronização Concluída", msg_txt)
            elif duplicados > 0:
                tocar_som("DUPLICADO")
                self.lbl_feedback.configure(
                    text=f"⚠️ {duplicados} XML(s) processado(s) (já existiam no lote ativo).",
                    bg="#4a4215",
                    fg="#f1fa8c"
                )
                messagebox.showinfo("Sincronização", f"⚠️ O(s) {duplicados} arquivo(s) XML localizado(s) já haviam sido importado(s) para o lote ativo atual.")
            else:
                self.lbl_feedback.configure(
                    text="🔄 Sincronização: Nenhum arquivo XML pendente na pasta xml_entrada.",
                    bg="#282a36",
                    fg="#bd93f9"
                )
                messagebox.showinfo("Sincronização", "Nenhum arquivo XML pendente foi encontrado na pasta 'xml_entrada'.")
        except Exception as e:
            messagebox.showerror("Erro de Sincronização", f"Erro ao varrer pasta de entrada: {e}")
        finally:
            self.entry_bip.focus_set()

    def carregar_xmls(self):
        resposta = messagebox.askyesnocancel(
            "📂 Carregar XMLs",
            "Deseja selecionar uma PASTA inteira contendo XMLs?\n\n(Escolha 'Não' para selecionar arquivos XML individuais)"
        )

        if resposta is None:
            self.entry_bip.focus_set()
            return

        arquivos_xml = []

        if resposta is True:
            pasta = filedialog.askdirectory(title="Selecione a pasta com arquivos XML")
            if not pasta:
                self.entry_bip.focus_set()
                return
            try:
                for root_dir, _, files in os.walk(pasta):
                    for f in files:
                        if f.lower().endswith(".xml"):
                            arquivos_xml.append(os.path.join(root_dir, f))
            except Exception as e:
                messagebox.showerror("Erro", f"Erro ao ler pasta: {e}")
                self.entry_bip.focus_set()
                return
        else:
            arquivos = filedialog.askopenfilenames(
                title="Selecione os arquivos XML",
                filetypes=[("Arquivos XML", "*.xml"), ("Todos os Arquivos", "*.*")]
            )
            if not arquivos:
                self.entry_bip.focus_set()
                return
            arquivos_xml = list(arquivos)

        if not arquivos_xml:
            messagebox.showinfo("Aviso", "Nenhum arquivo XML foi localizado.")
            self.entry_bip.focus_set()
            return

        lote_ativo = database.obter_ou_criar_lote_ativo()
        lote_id = lote_ativo["id"]

        pasta_proc = os.path.join(database.BASE_DIR, "xml_entrada", "processados")
        os.makedirs(pasta_proc, exist_ok=True)

        inseridos = 0
        duplicados = 0
        erros = 0

        for caminho_xml in arquivos_xml:
            try:
                dados = watcher.extrair_dados_xml(caminho_xml)
                if not dados:
                    erros += 1
                    continue

                nome_arquivo = os.path.basename(caminho_xml)
                _, foi_inserido = database.inserir_pedido(
                    chave=dados["chave"],
                    numero_nf=dados["numero_nf"],
                    lote_id=lote_id,
                    arquivo_xml=nome_arquivo
                )

                # Copiar para xml_entrada/processados para indexação pelo motor RAG
                dest_rag = os.path.join(pasta_proc, nome_arquivo)
                if os.path.abspath(caminho_xml) != os.path.abspath(dest_rag) and not os.path.exists(dest_rag):
                    try:
                        shutil.copy2(caminho_xml, dest_rag)
                    except Exception:
                        pass

                if foi_inserido:
                    inseridos += 1
                else:
                    duplicados += 1
            except Exception as e:
                print(f"Erro ao importar {caminho_xml}: {e}")
                erros += 1

        msg_result = f"Importação Concluída!\n\n✅ Novas notas inseridas: {inseridos}\n⚠️ Notas duplicadas no lote: {duplicados}\n"
        if erros > 0:
            msg_result += f"❌ Arquivos inválidos/com erro: {erros}"

        messagebox.showinfo("Resultado da Importação", msg_result)

        self.carregar_dados_lote_ativo()
        self.atualizar_aba_rag_documentos()
        self.lbl_feedback.configure(
            text=f"📂 {inseridos} notas importadas e indexadas no RAG para o Lote {lote_ativo['codigo']}!",
            bg="#1b4b27",
            fg="#50fa7b"
        )
        self.entry_bip.focus_set()

    def confirmar_novo_lote(self):
        confirmar = messagebox.askyesno(
            "➕ Criar Novo Lote",
            "Deseja arquivar o lote ativo atual e iniciar um NOVO lote zerado?\n\n"
            "Todas as notas atuais permanecerão salvas no histórico do banco de dados."
        )

        if not confirmar:
            self.entry_bip.focus_set()
            return

        novo_lote = database.criar_novo_lote(arquivar_anterior=True)
        self.carregar_dados_lote_ativo()
        self.atualizar_aba_rag_documentos()

        self.lbl_feedback.configure(
            text=f"✨ Novo lote '{novo_lote['codigo']}' ativado com sucesso!",
            bg="#282a36",
            fg="#bd93f9"
        )
        self.statusbar.configure(text=f"Lote arquivado. Novo lote criado: {novo_lote['codigo']}")
        self.entry_bip.focus_set()

    def abrir_janela_auditoria(self):
        JanelaAuditoria(self)


class JanelaAuditoria(tk.Toplevel):
    """Janela Modal de Auditoria, Relatórios em CSV e Assistente de IA Integrado."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("📜 Auditoria de Lotes & Assistente IA")
        self.geometry("1120x780")
        self.minsize(900, 620)
        self.configure(bg=parent.bg_color)

        self.lotes_dict = {}
        self.lote_selecionado_id = None
        self.ia_em_execucao = False

        self.criar_interface()
        self.carregar_lotes()

        self.transient(parent)
        self.grab_set()

    def criar_interface(self):
        container = ttk.Frame(self, style="Main.TFrame")
        container.pack(fill="both", expand=True, padx=15, pady=15)

        header_frame = ttk.Frame(container, style="Main.TFrame")
        header_frame.pack(fill="x", pady=(0, 12))

        lbl_select = tk.Label(
            header_frame,
            text="📅 Selecionar Lote por Data/Hora:",
            font=("Segoe UI", 11, "bold"),
            bg=self.parent.bg_color,
            fg="#bd93f9"
        )
        lbl_select.pack(side="left", padx=(0, 10))

        self.combo_lotes = ttk.Combobox(
            header_frame,
            font=("Segoe UI", 10),
            state="readonly",
            width=45
        )
        self.combo_lotes.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.combo_lotes.bind("<<ComboboxSelected>>", self.on_lote_selecionado)

        btn_csv = ttk.Button(
            header_frame,
            text="📥 Exportar CSV de Auditoria",
            style="Primary.TButton",
            command=self.exportar_csv
        )
        btn_csv.pack(side="right")

        stats_frame = ttk.Frame(container, style="Main.TFrame")
        stats_frame.pack(fill="x", pady=(0, 12))

        for i in range(4):
            stats_frame.columnconfigure(i, weight=1, uniform="aud_card")

        card1 = tk.Frame(stats_frame, bg=self.parent.card_bg, highlightbackground=self.parent.card_border, highlightthickness=1)
        card1.grid(row=0, column=0, padx=4, sticky="ew")
        tk.Label(card1, text="Total no Lote", font=("Segoe UI", 9, "bold"), bg=self.parent.card_bg, fg="#8be9fd").pack(pady=(6, 2))
        self.lbl_total = tk.Label(card1, text="0", font=("Segoe UI", 16, "bold"), bg=self.parent.card_bg, fg="#ffffff")
        self.lbl_total.pack(pady=(0, 6))

        card2 = tk.Frame(stats_frame, bg=self.parent.card_bg, highlightbackground=self.parent.card_border, highlightthickness=1)
        card2.grid(row=0, column=1, padx=4, sticky="ew")
        tk.Label(card2, text="🔴 Não Bipadas", font=("Segoe UI", 9, "bold"), bg=self.parent.card_bg, fg="#ff5555").pack(pady=(6, 2))
        self.lbl_nao_bipadas = tk.Label(card2, text="0", font=("Segoe UI", 16, "bold"), bg=self.parent.card_bg, fg="#ff5555")
        self.lbl_nao_bipadas.pack(pady=(0, 6))

        card3 = tk.Frame(stats_frame, bg=self.parent.card_bg, highlightbackground=self.parent.card_border, highlightthickness=1)
        card3.grid(row=0, column=2, padx=4, sticky="ew")
        tk.Label(card3, text="🟡 Em Separação", font=("Segoe UI", 9, "bold"), bg=self.parent.card_bg, fg="#f1fa8c").pack(pady=(6, 2))
        self.lbl_em_separacao = tk.Label(card3, text="0", font=("Segoe UI", 16, "bold"), bg=self.parent.card_bg, fg="#f1fa8c")
        self.lbl_em_separacao.pack(pady=(0, 6))

        card4 = tk.Frame(stats_frame, bg=self.parent.card_bg, highlightbackground=self.parent.card_border, highlightthickness=1)
        card4.grid(row=0, column=3, padx=4, sticky="ew")
        tk.Label(card4, text="🟢 Prontas para Coleta", font=("Segoe UI", 9, "bold"), bg=self.parent.card_bg, fg="#50fa7b").pack(pady=(6, 2))
        self.lbl_pronto_coleta = tk.Label(card4, text="0", font=("Segoe UI", 16, "bold"), bg=self.parent.card_bg, fg="#50fa7b")
        self.lbl_pronto_coleta.pack(pady=(0, 6))

        table_frame = ttk.Frame(container, style="Main.TFrame")
        table_frame.pack(fill="both", expand=True)

        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        columns = ("idx", "numero_nf", "status", "chave", "dt_importacao", "dt_separacao", "dt_coleta", "duracao")
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            style="Treeview",
            selectmode="browse"
        )

        self.tree.heading("idx", text="#")
        self.tree.heading("numero_nf", text="Nº NF")
        self.tree.heading("status", text="Status Final")
        self.tree.heading("chave", text="Chave de Acesso")
        self.tree.heading("dt_importacao", text="Data Importação")
        self.tree.heading("dt_separacao", text="1º Bip (Separação)")
        self.tree.heading("dt_coleta", text="2º Bip (Coleta)")
        self.tree.heading("duracao", text="Duração Separação")

        self.tree.column("idx", width=40, anchor="center")
        self.tree.column("numero_nf", width=100, anchor="center")
        self.tree.column("status", width=160, anchor="w")
        self.tree.column("chave", width=340, anchor="w")
        self.tree.column("dt_importacao", width=150, anchor="center")
        self.tree.column("dt_separacao", width=150, anchor="center")
        self.tree.column("dt_coleta", width=150, anchor="center")
        self.tree.column("duracao", width=120, anchor="center")

        self.tree.tag_configure("nao_bipado", foreground="#ff5555")
        self.tree.tag_configure("em_separacao", foreground="#f1fa8c")
        self.tree.tag_configure("pronto_coleta", foreground="#50fa7b")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview, style="Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview, style="Horizontal.TScrollbar")
        self.tree.configure(xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        # Painel de IA na Janela de Auditoria
        ia_card = tk.Frame(
            container,
            bg=self.parent.card_bg,
            highlightbackground="#bd93f9",
            highlightthickness=1,
            bd=0
        )
        ia_card.pack(fill="both", expand=False, pady=(12, 0))

        ia_top = tk.Frame(ia_card, bg=self.parent.card_bg)
        ia_top.pack(fill="x", padx=12, pady=(8, 6))

        tk.Label(
            ia_top,
            text="🤖 Assistente IA de Auditoria do Lote:",
            font=("Segoe UI", 10, "bold"),
            bg=self.parent.card_bg,
            fg="#bd93f9"
        ).pack(side="left")

        ttk.Button(
            ia_top,
            text="📊 Status Geral do Lote",
            style="Primary.TButton",
            command=lambda: self.solicitar_auditoria_ia(
                "Faça um diagnóstico e status geral completo deste lote: total de notas importadas, "
                "quantas e quais já foram bipadas, quantas faltam bipar, progresso percentual e se houve alertas."
            )
        ).pack(side="right", padx=3)

        ttk.Button(
            ia_top,
            text="🟢 Listar Já Bipadas",
            style="Primary.TButton",
            command=lambda: self.solicitar_auditoria_ia(
                "Liste todas as notas fiscais que JÁ FORAM BIPADAS neste lote, separando entre "
                "'Em Separação (1º Bip)' e 'Prontas para Coleta (2º Bip)' com seus respectivos horários."
            )
        ).pack(side="right", padx=3)

        ttk.Button(
            ia_top,
            text="🔴 Listar Não Bipadas",
            style="Primary.TButton",
            command=lambda: self.solicitar_auditoria_ia(
                "Liste todas as notas fiscais que AINDA NÃO FORAM BIPADAS neste lote (pendentes de 1º bip), "
                "informando o Nº da NF, chave e data de importação."
            )
        ).pack(side="right", padx=3)

        ia_input_frame = tk.Frame(ia_card, bg=self.parent.card_bg)
        ia_input_frame.pack(fill="x", padx=12, pady=(0, 6))

        self.entry_pergunta_ia = tk.Entry(
            ia_input_frame,
            font=("Segoe UI", 10),
            bg="#191622",
            fg="#f8f8f2",
            insertbackground="#ffffff",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#44475a",
            bd=4
        )
        self.entry_pergunta_ia.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_pergunta_ia.insert(0, "Pergunte à IA sobre este lote (ex: Quais notas faltam bipar? Alguma nota deu erro?)...")
        self.entry_pergunta_ia.bind("<FocusIn>", self._limpar_placeholder_ia)
        self.entry_pergunta_ia.bind("<Return>", lambda e: self.enviar_pergunta_livre_ia())

        self.btn_enviar_ia = ttk.Button(
            ia_input_frame,
            text="🤖 Perguntar à IA",
            style="Primary.TButton",
            command=self.enviar_pergunta_livre_ia
        )
        self.btn_enviar_ia.pack(side="right")

        ia_text_frame = tk.Frame(ia_card, bg=self.parent.card_bg)
        ia_text_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self.txt_ia_resposta = tk.Text(
            ia_text_frame,
            height=8,
            font=("Consolas", 10),
            bg="#191622",
            fg="#50fa7b",
            insertbackground="#ffffff",
            relief="flat",
            wrap="word",
            padx=8,
            pady=6,
            state="disabled"
        )
        vsb_ia = ttk.Scrollbar(ia_text_frame, orient="vertical", command=self.txt_ia_resposta.yview, style="Vertical.TScrollbar")
        self.txt_ia_resposta.configure(yscrollcommand=vsb_ia.set)

        self.txt_ia_resposta.pack(side="left", fill="both", expand=True)
        vsb_ia.pack(side="right", fill="y")

        self._escrever_resposta_ia(
            "💡 Clique em um dos botões rápidos acima ('🔴 Listar Não Bipadas', '🟢 Listar Já Bipadas' ou '📊 Status Geral do Lote') "
            "ou digite sua pergunta para a IA auditar o lote selecionado em tempo real."
        )

    def _limpar_placeholder_ia(self, event=None):
        atual = self.entry_pergunta_ia.get()
        if atual.startswith("Pergunte à IA sobre este lote"):
            self.entry_pergunta_ia.delete(0, tk.END)

    def _escrever_resposta_ia(self, texto: str, cor: str = "#50fa7b"):
        self.txt_ia_resposta.configure(state="normal", fg=cor)
        self.txt_ia_resposta.delete("1.0", tk.END)
        self.txt_ia_resposta.insert(tk.END, texto)
        self.txt_ia_resposta.configure(state="disabled")

    def enviar_pergunta_livre_ia(self):
        pergunta = self.entry_pergunta_ia.get().strip()
        if not pergunta or pergunta.startswith("Pergunte à IA sobre este lote"):
            pergunta = "Me dê o status geral deste lote de notas fiscais."
        self.solicitar_auditoria_ia(pergunta)

    def solicitar_auditoria_ia(self, pergunta: str):
        if not self.lote_selecionado_id:
            messagebox.showwarning("Aviso", "Selecione um lote primeiro para consultar a IA.")
            return
        if self.ia_em_execucao:
            return

        self.ia_em_execucao = True
        self._escrever_resposta_ia(
            f"⏳ Consultando o Agente IA para o lote selecionado...\nPergunta: \"{pergunta}\"",
            cor="#f1fa8c"
        )

        lote_id = self.lote_selecionado_id

        def _worker():
            try:
                resposta = AuditoriaIAService.consultar_ia_auditoria(lote_id=lote_id, pergunta=pergunta)
                self.after(0, lambda: self._finalizar_resposta_ia(resposta, "#50fa7b"))
            except Exception as e:
                self.after(0, lambda: self._finalizar_resposta_ia(f"❌ Erro ao consultar IA: {e}", "#ff5555"))

        threading.Thread(target=_worker, daemon=True).start()

    def _finalizar_resposta_ia(self, texto: str, cor: str):
        self.ia_em_execucao = False
        if self.winfo_exists():
            self._escrever_resposta_ia(texto, cor=cor)

    def carregar_lotes(self):
        todos_lotes = database.listar_todos_lotes()
        if not todos_lotes:
            return

        opcoes = []
        self.lotes_dict = {}

        for l in todos_lotes:
            st_label = " (ATIVO)" if l["status"] == "ATIVO" else " (ARQUIVADO)"
            dt_fmt = l.get("data_criacao") or "Desconhecido"
            total = l.get("total_pedidos", 0)
            text_combo = f"{l['codigo']}{st_label} - Criado em {dt_fmt} ({total} NFs)"

            opcoes.append(text_combo)
            self.lotes_dict[text_combo] = l["id"]

        self.combo_lotes["values"] = opcoes
        if opcoes:
            self.combo_lotes.current(0)
            self.on_lote_selecionado()

    def on_lote_selecionado(self, event=None):
        selecionado = self.combo_lotes.get()
        if not selecionado or selecionado not in self.lotes_dict:
            return

        lote_id = self.lotes_dict[selecionado]
        self.lote_selecionado_id = lote_id
        dados = database.obter_dados_lote_por_id(lote_id)
        if not dados:
            return

        stats = dados["estatisticas"]
        pedidos = dados["pedidos"]

        self.lbl_total.configure(text=str(stats["total"]))
        self.lbl_nao_bipadas.configure(text=str(stats["nao_bipados"]))
        self.lbl_em_separacao.configure(text=str(stats["em_separacao"]))
        self.lbl_pronto_coleta.configure(text=str(stats["pronto_coleta"]))

        children = self.tree.get_children()
        self.tree.delete(*children)

        for idx, p in enumerate(pedidos, start=1):
            st = p["status"]
            if st == "NAO_BIPADO":
                status_fmt = "🔴 Não Bipado"
                tag = "nao_bipado"
            elif st == "EM_SEPARACAO":
                status_fmt = "🟡 Em Separação"
                tag = "em_separacao"
            elif st == "PRONTO_COLETA":
                status_fmt = "🟢 Pronto para Coleta"
                tag = "pronto_coleta"
            else:
                status_fmt = st
                tag = ""

            dt_imp = p.get("data_importacao") or "-"
            dt_sep = p.get("data_bip_separacao") or "-"
            dt_col = p.get("data_bip_coleta") or "-"

            duracao_fmt = "-"
            if p.get("data_bip_separacao") and p.get("data_bip_coleta"):
                try:
                    from datetime import datetime
                    t1 = datetime.strptime(p["data_bip_separacao"], "%Y-%m-%d %H:%M:%S")
                    t2 = datetime.strptime(p["data_bip_coleta"], "%Y-%m-%d %H:%M:%S")
                    diff_sec = int((t2 - t1).total_seconds())
                    mins = diff_sec // 60
                    secs = diff_sec % 60
                    duracao_fmt = f"{mins}m {secs}s"
                except Exception:
                    duracao_fmt = "-"

            self.tree.insert(
                "",
                "end",
                iid=str(p["id"]),
                values=(
                    idx,
                    p["numero_nf"],
                    status_fmt,
                    p["chave"],
                    dt_imp,
                    dt_sep,
                    dt_col,
                    duracao_fmt
                ),
                tags=(tag,)
            )

    def exportar_csv(self):
        if not self.lote_selecionado_id:
            messagebox.showwarning("Aviso", "Nenhum lote selecionado para exportação.")
            return

        audit_dir = os.path.join(database.BASE_DIR, "BoasPraticas", "Auditoria")
        os.makedirs(audit_dir, exist_ok=True)

        selecionado_txt = self.combo_lotes.get()
        lote_codigo = selecionado_txt.split(" ")[0] if selecionado_txt else f"LOTE_{self.lote_selecionado_id}"
        nome_padrao = f"Auditoria_{lote_codigo}.csv"

        caminho = filedialog.asksaveasfilename(
            title="Salvar Relatório de Auditoria em CSV",
            initialdir=audit_dir,
            initialfile=nome_padrao,
            defaultextension=".csv",
            filetypes=[("Arquivo CSV (*.csv)", "*.csv"), ("Todos os Arquivos", "*.*")]
        )

        if not caminho:
            return

        sucesso = database.exportar_lote_csv(self.lote_selecionado_id, caminho)
        if sucesso:
            messagebox.showinfo("Sucesso", f"✅ Relatório CSV de Auditoria gerado com sucesso!\n\nSalvo em:\n{caminho}")
        else:
            messagebox.showerror("Erro", "Falha ao gerar relatório CSV do lote selecionado.")


if __name__ == "__main__":
    app = ValidadorExpedicaoApp()
    app.mainloop()
