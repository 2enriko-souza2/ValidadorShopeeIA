import os
import sys
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any


def get_base_dir() -> str:
    """
    Retorna o diretório base real do projeto.
    Se o script estiver rodando compilado pelo PyInstaller (.exe),
    retorna a pasta raiz do projeto (ex: TesteShopee).
    """
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        if os.path.basename(exe_dir).lower() == "dist":
            return os.path.dirname(exe_dir)
        return exe_dir
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))


BASE_DIR = get_base_dir()
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "pedidos.db")


def get_db_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Retorna conexão com o banco SQLite configurada com Row factory e Foreign Keys habilitadas."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Cria a estrutura das tabelas lotes, pedidos e historico_bips se não existirem."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()

        # Tabela Lotes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'ATIVO',
                data_criacao DATETIME DEFAULT (datetime('now', 'localtime')),
                data_fechamento DATETIME NULL
            );
        """)

        # Tabela Pedidos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pedidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lote_id INTEGER NOT NULL,
                chave TEXT NOT NULL,
                numero_nf TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'NAO_BIPADO',
                data_importacao DATETIME DEFAULT (datetime('now', 'localtime')),
                data_bip_separacao DATETIME NULL,
                data_bip_coleta DATETIME NULL,
                arquivo_xml TEXT NULL,
                FOREIGN KEY (lote_id) REFERENCES lotes(id) ON DELETE CASCADE,
                UNIQUE (lote_id, chave)
            );
        """)

        # Tabela Historico de Bips
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS historico_bips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pedido_id INTEGER NULL,
                lote_id INTEGER NULL,
                chave TEXT NOT NULL,
                tipo_bip TEXT NOT NULL,
                resultado TEXT NOT NULL,
                timestamp DATETIME DEFAULT (datetime('now', 'localtime')),
                estacao_id TEXT NULL,
                FOREIGN KEY (pedido_id) REFERENCES pedidos(id) ON DELETE SET NULL,
                FOREIGN KEY (lote_id) REFERENCES lotes(id) ON DELETE CASCADE
            );
        """)

        # Índices para performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pedidos_chave ON pedidos(chave);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pedidos_lote_id ON pedidos(lote_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pedidos_status ON pedidos(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_lotes_status ON lotes(status);")

        conn.commit()


# ==============================================================================
# GESTÃO DE LOTES
# ==============================================================================

def obter_ou_criar_lote_ativo(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """
    Retorna o lote com status 'ATIVO'.
    Caso não exista nenhum lote ativo, cria um lote automático com data/hora.
    """
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM lotes WHERE status = 'ATIVO' ORDER BY id DESC LIMIT 1;")
        row = cursor.fetchone()
        if row:
            return dict(row)

        # Criar novo lote automático
        codigo_lote = f"LOTE_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute(
            "INSERT INTO lotes (codigo, status, data_criacao) VALUES (?, 'ATIVO', ?);",
            (codigo_lote, now_str)
        )
        conn.commit()

        cursor.execute("SELECT * FROM lotes WHERE id = ?;", (cursor.lastrowid,))
        return dict(cursor.fetchone())


def criar_novo_lote(codigo: Optional[str] = None, arquivar_anterior: bool = True, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """
    Cria um novo lote ativo.
    Se arquivar_anterior=True, altera o lote ativo atual para 'ARQUIVADO'.
    """
    init_db(db_path)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()

        if arquivar_anterior:
            cursor.execute(
                "UPDATE lotes SET status = 'ARQUIVADO', data_fechamento = ? WHERE status = 'ATIVO';",
                (now_str,)
            )

        if not codigo:
            codigo = f"LOTE_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        cursor.execute(
            "INSERT INTO lotes (codigo, status, data_criacao) VALUES (?, 'ATIVO', ?);",
            (codigo, now_str)
        )
        conn.commit()

        cursor.execute("SELECT * FROM lotes WHERE id = ?;", (cursor.lastrowid,))
        return dict(cursor.fetchone())


def arquivar_lote_ativo(db_path: str = DEFAULT_DB_PATH) -> bool:
    """Arquiva o lote ativo atual se existir."""
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE lotes SET status = 'ARQUIVADO', data_fechamento = ? WHERE status = 'ATIVO';",
            (now_str,)
        )
        conn.commit()
        return cursor.rowcount > 0


# ==============================================================================
# GESTÃO DE PEDIDOS / IMPORTAÇÃO
# ==============================================================================

def sanitizar_chave(chave: str) -> str:
    """Remove prefixos como 'NFe' e espaços em branco."""
    if not chave:
        return ""
    chave_limpa = chave.strip()
    if chave_limpa.upper().startswith("NFE"):
        chave_limpa = chave_limpa[3:]
    return chave_limpa.strip()


def inserir_pedido(chave: str, numero_nf: str, lote_id: Optional[int] = None, arquivo_xml: Optional[str] = None, db_path: str = DEFAULT_DB_PATH) -> Tuple[Dict[str, Any], bool]:
    """
    Insere um novo pedido no lote informado (ou no lote ativo).
    Retorna uma tupla: (dados_do_pedido, inserido_com_sucesso).
    Se a chave já existir no mesmo lote, retorna (pedido_existente, False).
    """
    chave_limpa = sanitizar_chave(chave)
    if not lote_id:
        lote_ativo = obter_ou_criar_lote_ativo(db_path)
        lote_id = lote_ativo["id"]

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()

        # Verificar se já existe no mesmo lote
        cursor.execute("SELECT * FROM pedidos WHERE lote_id = ? AND chave = ?;", (lote_id, chave_limpa))
        existente = cursor.fetchone()
        if existente:
            return dict(existente), False

        # Inserir novo pedido
        cursor.execute("""
            INSERT INTO pedidos (lote_id, chave, numero_nf, status, data_importacao, arquivo_xml)
            VALUES (?, ?, ?, 'NAO_BIPADO', ?, ?);
        """, (lote_id, chave_limpa, str(numero_nf), now_str, arquivo_xml))
        conn.commit()

        cursor.execute("SELECT * FROM pedidos WHERE id = ?;", (cursor.lastrowid,))
        return dict(cursor.fetchone()), True


# ==============================================================================
# LÓGICA DE BIPAGEM
# ==============================================================================

def bipar_pedido(chave: str, etapa: Optional[str] = None, estacao_id: Optional[str] = None, cooldown_segundos: int = 300, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """
    Realiza a bipagem de uma DANFE pela chave de 44 dígitos.

    Transições de Status:
        'NAO_BIPADO' -> 'EM_SEPARACAO' (1º Bip / Separação)
        'EM_SEPARACAO' -> 'PRONTO_COLETA' (2º Bip / Coleta com Cooldown de 5 min)

    Códigos de Resultado Retornados:
        - SUCESSO_SEPARACAO: Pedido transitou para EM_SEPARACAO.
        - SUCESSO_COLETA: Pedido transitou para PRONTO_COLETA.
        - COOLDOWN: 2º bip realizado antes do intervalo mínimo de cooldown (300s).
        - DUPLICADO: Tentativa de bipar no mesmo estágio já realizado.
        - FORA_DO_LOTE: Chave não cadastrada no lote ativo.
        - JA_CONCLUIDO: Pedido já finalizou todas as etapas ('PRONTO_COLETA').

    Parâmetros:
        chave: Chave da DANFE (44 dígitos).
        etapa: Etapa esperada ('SEPARACAO', 'COLETA' ou None/AUTO para progressão automática).
        estacao_id: Identificador da máquina/leitor que executou o bip.
        cooldown_segundos: Tempo de espera mínimo em segundos para aceitar o 2º bip (Padrão: 300s / 5min).
    """
    chave_limpa = sanitizar_chave(chave)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    lote_ativo = obter_ou_criar_lote_ativo(db_path)
    lote_id = lote_ativo["id"]

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()

        # Buscar pedido no lote ativo
        cursor.execute("SELECT * FROM pedidos WHERE lote_id = ? AND chave = ?;", (lote_id, chave_limpa))
        pedido = cursor.fetchone()

        # CASO 1: Chave NÃO cadastrada no lote ativo
        if not pedido:
            resultado = "FORA_DO_LOTE"
            mensagem = f"ERRO: Chave {chave_limpa[-8:] if len(chave_limpa)>=8 else chave_limpa} NÃO pertence ao lote ativo!"
            cursor.execute("""
                INSERT INTO historico_bips (lote_id, chave, tipo_bip, resultado, timestamp, estacao_id)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (lote_id, chave_limpa, etapa or "AUTO", resultado, now_str, estacao_id))
            conn.commit()

            return {
                "resultado": resultado,
                "mensagem": mensagem,
                "chave": chave_limpa,
                "pedido": None
            }

        pedido_dict = dict(pedido)
        pedido_id = pedido_dict["id"]
        status_atual = pedido_dict["status"]
        numero_nf = pedido_dict["numero_nf"]

        # Helper para checar cooldown do 2º bip
        def checar_cooldown_coleta(data_bip_sep_str: Optional[str]) -> Tuple[bool, str]:
            if not data_bip_sep_str:
                return False, ""
            try:
                dt_sep = datetime.strptime(data_bip_sep_str, '%Y-%m-%d %H:%M:%S')
                dt_now = datetime.now()
                tempo_decorrido = (dt_now - dt_sep).total_seconds()
                if tempo_decorrido < cooldown_segundos:
                    restante = int(cooldown_segundos - tempo_decorrido)
                    mins = restante // 60
                    segs = restante % 60
                    tempo_fmt = f"{mins}m {segs}s" if mins > 0 else f"{segs}s"
                    return True, tempo_fmt
            except Exception:
                pass
            return False, ""

        # Determinar transição com base em etapa especificada ou AUTO
        etapa_normalizada = (etapa or "").upper()

        if etapa_normalizada == "SEPARACAO":
            if status_atual == "NAO_BIPADO":
                novo_status = "EM_SEPARACAO"
                resultado = "SUCESSO_SEPARACAO"
                mensagem = f"SUCESSO: NF {numero_nf} validada para Separação!"
            elif status_atual == "EM_SEPARACAO":
                resultado = "DUPLICADO"
                mensagem = f"AVISO: NF {numero_nf} JÁ está em Separação!"
            elif status_atual == "PRONTO_COLETA":
                resultado = "JA_CONCLUIDO"
                mensagem = f"AVISO: NF {numero_nf} JÁ foi concluída para Coleta!"
            else:
                resultado = "DUPLICADO"
                mensagem = f"AVISO: NF {numero_nf} já processada nesta etapa!"

        elif etapa_normalizada == "COLETA":
            if status_atual == "EM_SEPARACAO":
                em_cooldown, tempo_restante = checar_cooldown_coleta(pedido_dict.get("data_bip_separacao"))
                if em_cooldown:
                    resultado = "COOLDOWN"
                    mensagem = f"AVISO: NF {numero_nf} bipada recentemente! Aguarde {tempo_restante} para liberar o 2º bip."
                else:
                    novo_status = "PRONTO_COLETA"
                    resultado = "SUCESSO_COLETA"
                    mensagem = f"SUCESSO: NF {numero_nf} validada para Coleta!"
            elif status_atual == "NAO_BIPADO":
                resultado = "DUPLICADO"
                mensagem = f"AVISO: NF {numero_nf} ainda NÃO passou pela Separação!"
            elif status_atual == "PRONTO_COLETA":
                resultado = "DUPLICADO"
                mensagem = f"AVISO: NF {numero_nf} JÁ foi bipada para Coleta!"
            else:
                resultado = "DUPLICADO"
                mensagem = f"AVISO: Status incompatível ({status_atual})."

        else:
            # Modo AUTO (ou etapa não informada): 'NAO_BIPADO' -> 'EM_SEPARACAO' -> 'PRONTO_COLETA'
            if status_atual == "NAO_BIPADO":
                novo_status = "EM_SEPARACAO"
                resultado = "SUCESSO_SEPARACAO"
                mensagem = f"SUCESSO: NF {numero_nf} validada para Separação!"
            elif status_atual == "EM_SEPARACAO":
                em_cooldown, tempo_restante = checar_cooldown_coleta(pedido_dict.get("data_bip_separacao"))
                if em_cooldown:
                    resultado = "COOLDOWN"
                    mensagem = f"AVISO: NF {numero_nf} bipada recentemente! Aguarde {tempo_restante} para liberar o 2º bip."
                else:
                    novo_status = "PRONTO_COLETA"
                    resultado = "SUCESSO_COLETA"
                    mensagem = f"SUCESSO: NF {numero_nf} pronta para Coleta!"
            elif status_atual == "PRONTO_COLETA":
                resultado = "JA_CONCLUIDO"
                mensagem = f"AVISO: NF {numero_nf} JÁ teve sua coleta concluída!"

        # Atualizar banco de dados se houve transição de status
        if resultado in ("SUCESSO_SEPARACAO", "SUCESSO_COLETA"):
            if resultado == "SUCESSO_SEPARACAO":
                cursor.execute("""
                    UPDATE pedidos
                    SET status = ?, data_bip_separacao = ?
                    WHERE id = ?;
                """, (novo_status, now_str, pedido_id))
            elif resultado == "SUCESSO_COLETA":
                cursor.execute("""
                    UPDATE pedidos
                    SET status = ?, data_bip_coleta = ?
                    WHERE id = ?;
                """, (novo_status, now_str, pedido_id))

            # Atualizar dict retornado
            cursor.execute("SELECT * FROM pedidos WHERE id = ?;", (pedido_id,))
            pedido_dict = dict(cursor.fetchone())

        # Registrar no histórico de bips
        tipo_bip_log = etapa or ("SEPARACAO" if resultado == "SUCESSO_SEPARACAO" else "COLETA" if resultado == "SUCESSO_COLETA" else "AUTO")
        cursor.execute("""
            INSERT INTO historico_bips (pedido_id, lote_id, chave, tipo_bip, resultado, timestamp, estacao_id)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (pedido_id, lote_id, chave_limpa, tipo_bip_log, resultado, now_str, estacao_id))

        conn.commit()

        return {
            "resultado": resultado,
            "mensagem": mensagem,
            "chave": chave_limpa,
            "pedido": pedido_dict
        }


# ==============================================================================
# CONSULTAS E RELATÓRIOS
# ==============================================================================

def listar_pedidos_lote_ativo(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Retorna a lista de pedidos e estatísticas resumidas do lote ativo."""
    lote_ativo = obter_ou_criar_lote_ativo(db_path)
    lote_id = lote_ativo["id"]

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pedidos WHERE lote_id = ? ORDER BY id ASC;", (lote_id,))
        pedidos = [dict(r) for r in cursor.fetchall()]

        total = len(pedidos)
        nao_bipados = sum(1 for p in pedidos if p["status"] == "NAO_BIPADO")
        em_separacao = sum(1 for p in pedidos if p["status"] == "EM_SEPARACAO")
        pronto_coleta = sum(1 for p in pedidos if p["status"] == "PRONTO_COLETA")

        return {
            "lote": lote_ativo,
            "estatisticas": {
                "total": total,
                "nao_bipados": nao_bipados,
                "em_separacao": em_separacao,
                "pronto_coleta": pronto_coleta,
                "bipados_total": em_separacao + pronto_coleta
            },
            "pedidos": pedidos
        }


def obter_historico_bips(lote_id: Optional[int] = None, limit: int = 50, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Retorna os registros de bips mais recentes."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        if lote_id:
            cursor.execute(
                "SELECT * FROM historico_bips WHERE lote_id = ? ORDER BY id DESC LIMIT ?;",
                (lote_id, limit)
            )
        else:
            cursor.execute(
                "SELECT * FROM historico_bips ORDER BY id DESC LIMIT ?;",
                (limit,)
            )
        return [dict(r) for r in cursor.fetchall()]


import csv


def listar_todos_lotes(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Retorna a lista de todos os lotes ordenados do mais recente para o mais antigo, com total de pedidos."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.*, 
                   COUNT(p.id) as total_pedidos,
                   SUM(CASE WHEN p.status = 'PRONTO_COLETA' THEN 1 ELSE 0 END) as concluidos
            FROM lotes l
            LEFT JOIN pedidos p ON p.lote_id = l.id
            GROUP BY l.id
            ORDER BY l.id DESC;
        """)
        return [dict(r) for r in cursor.fetchall()]


def obter_dados_lote_por_id(lote_id: int, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """Retorna dados detalhados de um lote específico por ID."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM lotes WHERE id = ?;", (lote_id,))
        lote_row = cursor.fetchone()
        if not lote_row:
            return None
        lote = dict(lote_row)

        cursor.execute("SELECT * FROM pedidos WHERE lote_id = ? ORDER BY id ASC;", (lote_id,))
        pedidos = [dict(r) for r in cursor.fetchall()]

        total = len(pedidos)
        nao_bipados = sum(1 for p in pedidos if p["status"] == "NAO_BIPADO")
        em_separacao = sum(1 for p in pedidos if p["status"] == "EM_SEPARACAO")
        pronto_coleta = sum(1 for p in pedidos if p["status"] == "PRONTO_COLETA")

        return {
            "lote": lote,
            "estatisticas": {
                "total": total,
                "nao_bipados": nao_bipados,
                "em_separacao": em_separacao,
                "pronto_coleta": pronto_coleta,
                "bipados_total": em_separacao + pronto_coleta
            },
            "pedidos": pedidos
        }


def exportar_lote_csv(lote_id: int, caminho_destino: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Gera um arquivo CSV formatado com BOM UTF-8 para auditoria completa do lote."""
    dados = obter_dados_lote_por_id(lote_id, db_path)
    if not dados:
        return False

    lote_info = dados["lote"]
    pedidos = dados["pedidos"]

    with open(caminho_destino, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        
        # Cabeçalho do Relatório
        writer.writerow(["RELATORIO DE AUDITORIA DE EXPEDICAO"])
        writer.writerow(["Codigo do Lote", lote_info["codigo"]])
        writer.writerow(["Status do Lote", lote_info["status"]])
        writer.writerow(["Data de Criacao", lote_info["data_criacao"]])
        writer.writerow(["Data de Fechamento", lote_info["data_fechamento"] or "Em Aberto"])
        writer.writerow([])
        
        # Cabeçalho da Tabela
        writer.writerow([
            "Item",
            "Nº Nota Fiscal",
            "Status",
            "Chave de Acesso (44 digitos)",
            "Data/Hora Importacao",
            "Hora 1º Bip (Separacao)",
            "Hora 2º Bip (Coleta)",
            "Duracao Separacao (m:s)",
            "Arquivo XML Origem"
        ])

        for idx, p in enumerate(pedidos, start=1):
            st = p["status"]
            if st == "NAO_BIPADO":
                status_fmt = "Nao Bipado"
            elif st == "EM_SEPARACAO":
                status_fmt = "Em Separacao"
            elif st == "PRONTO_COLETA":
                status_fmt = "Pronto para Coleta"
            else:
                status_fmt = st

            dt_imp = p.get("data_importacao") or "-"
            dt_sep = p.get("data_bip_separacao") or "-"
            dt_col = p.get("data_bip_coleta") or "-"

            # Calcular tempo de separação se ambos existirem
            duracao_fmt = "-"
            if p.get("data_bip_separacao") and p.get("data_bip_coleta"):
                try:
                    t1 = datetime.strptime(p["data_bip_separacao"], "%Y-%m-%d %H:%M:%S")
                    t2 = datetime.strptime(p["data_bip_coleta"], "%Y-%m-%d %H:%M:%S")
                    diff_sec = int((t2 - t1).total_seconds())
                    mins = diff_sec // 60
                    secs = diff_sec % 60
                    duracao_fmt = f"{mins}m {secs}s"
                except Exception:
                    duracao_fmt = "-"

            writer.writerow([
                idx,
                p["numero_nf"],
                status_fmt,
                p["chave"],
                dt_imp,
                dt_sep,
                dt_col,
                duracao_fmt,
                p.get("arquivo_xml") or "-"
            ])

    return True

