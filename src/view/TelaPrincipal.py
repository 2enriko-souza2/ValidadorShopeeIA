import os
import sys
import time
import threading
import winsound
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from dao import PedidoDAO as database
from service import XmlService as watcher
from service import AuditoriaIAService


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

        self.title("Validador de Expedição + IA - Conferência Shopee / Bling")
        self.geometry("1150x720")
        self.minsize(900, 600)

        # Estado do modo Tela Cheia
        self.is_fullscreen = False

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

        # Estilizar TTK
        self.setup_styles()

        # Construir elementos gráficos
        self.criar_interface()

        # Vinculação de teclas de atalho globais
        self.bind("<F11>", self.toggle_fullscreen)
        self.bind("<Escape>", self.exit_fullscreen)

        # Atualizar dados iniciais
        self.carregar_dados_lote_ativo()

        # Iniciar polling e sincronização periódica da UI (1s)
        self.checar_atualizacoes_db()

        # Iniciar manutenção de foco automático contínuo no campo de bipagem
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

        # Scrollbar escuro
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
        # Container Principal
        main_container = ttk.Frame(self, style="Main.TFrame")
        main_container.pack(fill="both", expand=True, padx=15, pady=15)

        # ==============================================================================
        # 1. HEADER & BARRA DE AÇÕES
        # ==============================================================================
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

        # Botões de Ação na Direita
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

        self.btn_fullscreen = ttk.Button(
            btn_frame,
            text="🖥️ Tela Cheia",
            style="Primary.TButton",
            command=self.toggle_fullscreen
        )
        self.btn_fullscreen.pack(side="left", padx=4)

        # ==============================================================================
        # 2. CARDS DE ESTATÍSTICAS (PROPORCIONAIS)
        # ==============================================================================
        stats_frame = ttk.Frame(main_container, style="Main.TFrame")
        stats_frame.pack(fill="x", pady=(0, 12))

        for i in range(4):
            stats_frame.columnconfigure(i, weight=1, uniform="stat_card")

        # Card 1: Total de Notas
        card1 = tk.Frame(stats_frame, bg=self.card_bg, highlightbackground=self.card_border, highlightthickness=1)
        card1.grid(row=0, column=0, padx=4, sticky="ew")
        tk.Label(card1, text="Total de Notas", font=("Segoe UI", 10, "bold"), bg=self.card_bg, fg="#8be9fd").pack(pady=(8, 2))
        self.lbl_card_total = tk.Label(card1, text="0", font=("Segoe UI", 20, "bold"), bg=self.card_bg, fg="#ffffff")
        self.lbl_card_total.pack(pady=(0, 8))

        # Card 2: 🔴 Não Bipadas
        card2 = tk.Frame(stats_frame, bg=self.card_bg, highlightbackground=self.card_border, highlightthickness=1)
        card2.grid(row=0, column=1, padx=4, sticky="ew")
        tk.Label(card2, text="🔴 Não Bipadas", font=("Segoe UI", 10, "bold"), bg=self.card_bg, fg="#ff5555").pack(pady=(8, 2))
        self.lbl_card_nao_bipadas = tk.Label(card2, text="0", font=("Segoe UI", 20, "bold"), bg=self.card_bg, fg="#ff5555")
        self.lbl_card_nao_bipadas.pack(pady=(0, 8))

        # Card 3: 🟡 Em Separação
        card3 = tk.Frame(stats_frame, bg=self.card_bg, highlightbackground=self.card_border, highlightthickness=1)
        card3.grid(row=0, column=2, padx=4, sticky="ew")
        tk.Label(card3, text="🟡 Em Separação", font=("Segoe UI", 10, "bold"), bg=self.card_bg, fg="#f1fa8c").pack(pady=(8, 2))
        self.lbl_card_em_separacao = tk.Label(card3, text="0", font=("Segoe UI", 20, "bold"), bg=self.card_bg, fg="#f1fa8c")
        self.lbl_card_em_separacao.pack(pady=(0, 8))

        # Card 4: 🟢 Prontas para Coleta
        card4 = tk.Frame(stats_frame, bg=self.card_bg, highlightbackground=self.card_border, highlightthickness=1)
        card4.grid(row=0, column=3, padx=4, sticky="ew")
        tk.Label(card4, text="🟢 Prontas para Coleta", font=("Segoe UI", 10, "bold"), bg=self.card_bg, fg="#50fa7b").pack(pady=(8, 2))
        self.lbl_card_pronto_coleta = tk.Label(card4, text="0", font=("Segoe UI", 20, "bold"), bg=self.card_bg, fg="#50fa7b")
        self.lbl_card_pronto_coleta.pack(pady=(0, 8))

        # ==============================================================================
        # 3. CAMPO DE BIPAGEM DE ALTA VISIBILIDADE
        # ==============================================================================
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

        # Banner de Feedback Visual da Bipagem
        self.lbl_feedback = tk.Label(
            bip_box,
            text="Aguardando bipagem... (Foco automático ativo)",
            font=("Segoe UI", 11, "bold"),
            bg=self.card_bg,
            fg="#6272a4",
            pady=4
        )
        self.lbl_feedback.pack(fill="x", padx=15, pady=(0, 6))

        # ==============================================================================
        # 4. TABELA DINÂMICA DE PEDIDOS (TREEVIEW PERMANENTE)
        # ==============================================================================
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

        # Configurar tags de cores para a tabela
        self.tree.tag_configure("nao_bipado", foreground="#ff5555")
        self.tree.tag_configure("em_separacao", foreground="#f1fa8c")
        self.tree.tag_configure("pronto_coleta", foreground="#50fa7b")

        # Scrollbars
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview, style="Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set)

        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview, style="Horizontal.TScrollbar")
        self.tree.configure(xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        # ==============================================================================
        # BARRA DE STATUS INFERIOR
        # ==============================================================================
        self.statusbar = tk.Label(
            main_container,
            text="Sistema Pronto | SQLite Operacional | Pressione F11 para Tela Cheia | Esc para Sair",
            font=("Segoe UI", 9),
            bg=self.bg_color,
            fg="#6272a4",
            anchor="w"
        )
        self.statusbar.pack(fill="x", pady=(6, 0))

    # ==============================================================================
    # LÓGICA DE FOCO AUTOMÁTICO E TECLAS DE ATALHO
    # ==============================================================================
    def manter_foco_continuo(self):
        """Redireciona o foco para o campo de bipagem se o usuário não estiver em outro campo editável."""
        try:
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

        self.entry_bip.focus_set()

    def exit_fullscreen(self, event=None):
        if self.is_fullscreen:
            self.is_fullscreen = False
            self.attributes("-fullscreen", False)
            self.btn_fullscreen.configure(text="🖥️ Tela Cheia")
            self.entry_bip.focus_set()

    # ==============================================================================
    # ATUALIZAÇÃO DA INTERFACE E CARREGAMENTO DE DADOS
    # ==============================================================================
    def calcular_hash_estado(self, pedidos):
        """Gera uma assinatura hash do estado atual dos pedidos no lote."""
        return "|".join(f"{p['id']}:{p['status']}:{p.get('data_bip_separacao')}:{p.get('data_bip_coleta')}" for p in pedidos)

    def carregar_dados_lote_ativo(self):
        """Consulta o banco SQLite e atualiza os cards, o lote ativo e a Treeview."""
        try:
            dados_lote = database.listar_pedidos_lote_ativo()

            lote_info = dados_lote["lote"]
            estatisticas = dados_lote["estatisticas"]
            pedidos = dados_lote["pedidos"]

            # Atualizar hash para evitar atualizações redundantes da tabela
            hash_atual = f"{lote_info['id']}_" + self.calcular_hash_estado(pedidos)
            self.last_db_state_hash = hash_atual

            # Atualizar Header do Lote
            self.lbl_lote_code.configure(text=f"Lote Ativo: {lote_info['codigo']} (ID: {lote_info['id']})")

            # Atualizar Cards de Estatísticas
            self.lbl_card_total.configure(text=str(estatisticas["total"]))
            self.lbl_card_nao_bipadas.configure(text=str(estatisticas["nao_bipados"]))
            self.lbl_card_em_separacao.configure(text=str(estatisticas["em_separacao"]))
            self.lbl_card_pronto_coleta.configure(text=str(estatisticas["pronto_coleta"]))

            # Atualizar Treeview mantendo todas as notas visíveis permanentemente
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
        """Verifica se novos XMLs ou bips foram registrados no banco de dados."""
        try:
            dados_lote = database.listar_pedidos_lote_ativo()
            pedidos = dados_lote["pedidos"]
            lote_id = dados_lote["lote"]["id"]
            hash_novo = f"{lote_id}_" + self.calcular_hash_estado(pedidos)

            if hash_novo != self.last_db_state_hash:
                self.carregar_dados_lote_ativo()
        except Exception:
            pass
        finally:
            self.after(1000, self.checar_atualizacoes_db)

    def iniciar_websocket_listener(self):
        """Thread secundária para escutar o WebSocket do servidor se estiver ativo."""
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

        # Atualizar Alerta Sonoro e Banner de Feedback Visual
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
        """Varre manualmente a pasta de entrada (xml_entrada) para importar XMLs novos."""
        try:
            res = watcher.processar_pasta_existente()
            self.carregar_dados_lote_ativo()

            inseridos = res.get("inseridos", 0)
            duplicados = res.get("duplicados", 0)
            totais = res.get("totais", 0)

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
                messagebox.showinfo("Sincronização", f"⚠️ O(s) {duplicados} arquivo(s) XML localizado(s) já haviam sido importado(s) para o lote ativo atual.\n\nEles foram movidos para a pasta 'xml_entrada/processados'.")
            else:
                self.lbl_feedback.configure(
                    text="🔄 Sincronização: Nenhum arquivo XML pendente na pasta xml_entrada.",
                    bg="#282a36",
                    fg="#bd93f9"
                )
                messagebox.showinfo("Sincronização", "Nenhum arquivo XML pendente foi encontrado na pasta 'xml_entrada'.\n\nColoque novos arquivos .xml na pasta e clique em Sincronizar novamente.")
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

                if foi_inserido:
                    inseridos += 1
                else:
                    duplicados += 1
            except Exception as e:
                print(f"Erro ao importar {caminho_xml}: {e}")
                erros += 1

        msg_result = f"Importação Concluída!\n\n" \
                     f"✅ Novas notas inseridas: {inseridos}\n" \
                     f"⚠️ Notas duplicadas no lote: {duplicados}\n"
        if erros > 0:
            msg_result += f"❌ Arquivos inválidos/com erro: {erros}"

        messagebox.showinfo("Resultado da Importação", msg_result)

        self.carregar_dados_lote_ativo()
        self.lbl_feedback.configure(
            text=f"📂 {inseridos} notas importadas com sucesso para o Lote {lote_ativo['codigo']}!",
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
        self.title("📜 Auditoria de Lotes & Assistente IA (GPT-4o-mini)")
        self.geometry("1120x780")
        self.minsize(900, 620)
        self.configure(bg=parent.bg_color)

        self.lotes_dict = {}  # {str_display: lote_id}
        self.lote_selecionado_id = None
        self.ia_em_execucao = False

        self.criar_interface()
        self.carregar_lotes()

        # Foco na janela modal
        self.transient(parent)
        self.grab_set()

    def criar_interface(self):
        container = ttk.Frame(self, style="Main.TFrame")
        container.pack(fill="both", expand=True, padx=15, pady=15)

        # 1. Header com Dropdown de Seleção de Lotes e Botão Exportar CSV
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

        # 2. Cards de Estatísticas do Lote Selecionado
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

        # 3. Tabela de Notas com Horários Detalhados
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

        # ==============================================================================
        # 4. PAINEL DO ASSISTENTE DE AUDITORIA COM IA (GPT-4o-mini)
        # ==============================================================================
        ia_card = tk.Frame(
            container,
            bg=self.parent.card_bg,
            highlightbackground="#bd93f9",
            highlightthickness=1,
            bd=0
        )
        ia_card.pack(fill="both", expand=False, pady=(12, 0))

        # Barra superior do Assistente IA + Botões Rápidos
        ia_top = tk.Frame(ia_card, bg=self.parent.card_bg)
        ia_top.pack(fill="x", padx=12, pady=(8, 6))

        tk.Label(
            ia_top,
            text="🤖 Assistente IA de Auditoria (GPT-4o-mini):",
            font=("Segoe UI", 10, "bold"),
            bg=self.parent.card_bg,
            fg="#bd93f9"
        ).pack(side="left")

        btn_ia_status = ttk.Button(
            ia_top,
            text="📊 Status Geral do Lote",
            style="Primary.TButton",
            command=lambda: self.solicitar_auditoria_ia(
                "Faça um diagnóstico e status geral completo deste lote: total de notas importadas, "
                "quantas e quais já foram bipadas, quantas faltam bipar, progresso percentual e se houve alertas."
            )
        )
        btn_ia_status.pack(side="right", padx=3)

        btn_ia_bipadas = ttk.Button(
            ia_top,
            text="🟢 Listar Já Bipadas",
            style="Primary.TButton",
            command=lambda: self.solicitar_auditoria_ia(
                "Liste todas as notas fiscais que JÁ FORAM BIPADAS neste lote, separando entre "
                "'Em Separação (1º Bip)' e 'Prontas para Coleta (2º Bip)' com seus respectivos horários."
            )
        )
        btn_ia_bipadas.pack(side="right", padx=3)

        btn_ia_nao_bipadas = ttk.Button(
            ia_top,
            text="🔴 Listar Não Bipadas",
            style="Primary.TButton",
            command=lambda: self.solicitar_auditoria_ia(
                "Liste todas as notas fiscais que AINDA NÃO FORAM BIPADAS neste lote (pendentes de 1º bip), "
                "informando o Nº da NF, chave e data de importação."
            )
        )
        btn_ia_nao_bipadas.pack(side="right", padx=3)

        # Barra de Pergunta Livre para a IA
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

        # Área de Texto com Scroll para Resposta da IA
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
            f"⏳ Consultando o modelo de IA (GPT-4o-mini) para o lote selecionado...\nPergunta: \"{pergunta}\"",
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

        # Atualizar Cards
        self.lbl_total.configure(text=str(stats["total"]))
        self.lbl_nao_bipadas.configure(text=str(stats["nao_bipados"]))
        self.lbl_em_separacao.configure(text=str(stats["em_separacao"]))
        self.lbl_pronto_coleta.configure(text=str(stats["pronto_coleta"]))

        # Limpar e Preencher Tabela
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
