import os
import re
import sys
import math
import unicodedata
from collections import Counter
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from dao import PedidoDAO as database
from service import DocumentoParserService as parser

ENV_PATH = os.path.join(database.BASE_DIR, ".env")
load_dotenv(dotenv_path=ENV_PATH)


def _normalizar_texto(texto: str) -> str:
    """Remove acentos e converte para minúsculas para busca RAG tolerante a falhas."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sem_acento.lower()


def _tokenizar(texto: str) -> List[str]:
    norm = _normalizar_texto(texto)
    stopwords = {
        "o", "a", "os", "as", "de", "da", "do", "das", "dos", "em", "na", "no", "nas", "nos",
        "para", "por", "com", "um", "uma", "que", "qual", "quais", "foi", "foram", "me", "de",
        "nota", "notas", "nf", "nfe", "fiscal", "fiscais", "sobre", "listar", "liste", "mostre",
        "cliente", "nome", "numero", "produto", "produtos", "item", "itens", "veiculo", "veiculos",
        "vendido", "vendida", "vendidos", "hora", "horario", "adicionado", "adicionada", "adicao",
        "pasta", "importacao", "importado", "importada", "retorne", "diga", "fale", "valor"
    }
    tokens = re.findall(r"[a-z0-9]{2,}", norm)
    return [t for t in tokens if t not in stopwords]


class IndiceRAGNotas:
    """
    Motor RAG (Retrieval-Augmented Generation) que indexa automaticamente todos os arquivos
    XML e PDF da pasta de importação (xml_entrada/ e xml_entrada/processados/) e cruza
    em tempo real com o banco de dados SQLite (pedidos.db).
    """

    def __init__(self):
        self.documentos: List[Dict[str, Any]] = []
        self.ultima_atualizacao: str = "-"

    def indexar_tudo(self, lote_id_filtro: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Varre a pasta xml_entrada (e subpasta processados) em busca de arquivos .xml e .pdf,
        extrai Número da Nota, Cliente, Produto/Veículo vendido e Hora de adição na pasta,
        e enriquece com os dados de status/bipagem do banco SQLite.
        """
        base_dir = database.BASE_DIR
        pasta_entrada = os.path.join(base_dir, "xml_entrada")
        pasta_processados = os.path.join(pasta_entrada, "processados")

        os.makedirs(pasta_entrada, exist_ok=True)
        os.makedirs(pasta_processados, exist_ok=True)

        # 1. Mapear todos os registros do banco de dados SQLite por chave
        mapa_db_por_chave: Dict[str, Dict[str, Any]] = {}
        try:
            with database.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT p.*, l.codigo as lote_codigo, l.status as lote_status
                    FROM pedidos p
                    JOIN lotes l ON l.id = p.lote_id
                    ORDER BY p.id DESC;
                """)
                for row in cur.fetchall():
                    d = dict(row)
                    if lote_id_filtro and d["lote_id"] != lote_id_filtro:
                        continue
                    chave_db = d["chave"]
                    if chave_db not in mapa_db_por_chave:
                        mapa_db_por_chave[chave_db] = d
        except Exception as e:
            print(f"Aviso ao ler banco para RAG: {e}")

        # 2. Localizar todos os arquivos .xml e .pdf em xml_entrada e xml_entrada/processados
        arquivos_encontrados: List[str] = []
        for pasta in (pasta_entrada, pasta_processados):
            if os.path.exists(pasta):
                for nome in os.listdir(pasta):
                    caminho = os.path.join(pasta, nome)
                    if os.path.isfile(caminho) and nome.lower().endswith((".xml", ".pdf")):
                        arquivos_encontrados.append(caminho)

        docs_indexados: Dict[str, Dict[str, Any]] = {}

        for caminho in arquivos_encontrados:
            if caminho.lower().endswith(".xml"):
                meta = parser.extrair_metadados_xml(caminho)
            else:
                meta = parser.extrair_metadados_pdf(caminho)

            if not meta:
                continue

            chave = meta["chave"]
            info_db = mapa_db_por_chave.get(chave)

            # Se houver filtro de lote específico e esta nota não pertencer ao lote filtrado, pular
            if lote_id_filtro is not None and not info_db:
                continue

            status_raw = info_db["status"] if info_db else "NA_PASTA_PENDENTE"
            if status_raw == "NAO_BIPADO":
                status_fmt = "🔴 Não Bipado"
            elif status_raw == "EM_SEPARACAO":
                status_fmt = "🟡 Em Separação (1º Bip)"
            elif status_raw == "PRONTO_COLETA":
                status_fmt = "🟢 Pronto para Coleta (2º Bip)"
            else:
                status_fmt = "📂 Na Pasta (Aguardando Sincronização)"

            # Hora adicionada na pasta: prioriza data_importacao do banco ou mtime do arquivo
            hora_pasta = (info_db.get("data_importacao") if info_db else None) or meta["hora_adicionado_pasta"]
            lote_cod = info_db.get("lote_codigo") if info_db else "Pasta xml_entrada"

            doc = {
                **meta,
                "status_raw": status_raw,
                "status_fmt": status_fmt,
                "hora_adicionado_pasta": hora_pasta,
                "lote_codigo": lote_cod,
                "data_bip_separacao": info_db.get("data_bip_separacao") if info_db else None,
                "data_bip_coleta": info_db.get("data_bip_coleta") if info_db else None,
            }

            # Construir texto integral de busca para o motor RAG
            doc["texto_rag"] = (
                f"Nota Fiscal NF {doc['numero_nf']} | Chave: {doc['chave']} | "
                f"Cliente: {doc['cliente_nome']} (CPF/CNPJ: {doc['cliente_doc']}, Cidade: {doc['cliente_cidade_uf']}, Endereço: {doc['cliente_endereco']}) | "
                f"Produto / Veículo Vendido: {doc['produto_veiculo_vendido']} | "
                f"Valor Total: R$ {doc['valor_total_nf']} | "
                f"Hora Adicionado na Pasta de Importação: {doc['hora_adicionado_pasta']} | "
                f"Data Emissão NF: {doc['data_emissao']} | "
                f"Status Bipagem: {doc['status_fmt']} | Lote: {doc['lote_codigo']} | "
                f"1º Bip Separação: {doc['data_bip_separacao'] or '-'} | "
                f"2º Bip Coleta: {doc['data_bip_coleta'] or '-'} | "
                f"Arquivo: {doc['nome_arquivo']} ({doc['tipo_arquivo']})"
            )

            doc["valores_busca"] = (
                f"{doc['numero_nf']} {doc['chave']} {doc['cliente_nome']} {doc['cliente_doc']} "
                f"{doc['cliente_cidade_uf']} {doc['cliente_endereco']} {doc['produto_veiculo_vendido']} "
                f"{doc['valor_total_nf']} {doc['hora_adicionado_pasta']} {doc['nome_arquivo']}"
            )

            docs_indexados[chave] = doc

        # 3. Adicionar também pedidos que estejam no SQLite mas cujo XML não esteja mais na pasta
        for chave_db, d in mapa_db_por_chave.items():
            if chave_db not in docs_indexados:
                st = d["status"]
                status_fmt = (
                    "🔴 Não Bipado" if st == "NAO_BIPADO"
                    else "🟡 Em Separação (1º Bip)" if st == "EM_SEPARACAO"
                    else "🟢 Pronto para Coleta (2º Bip)"
                )
                doc = {
                    "tipo_arquivo": "SQLite",
                    "nome_arquivo": d.get("arquivo_xml") or "-",
                    "caminho_arquivo": "-",
                    "numero_nf": d["numero_nf"],
                    "serie_nf": "1",
                    "chave": chave_db,
                    "natureza_operacao": "Venda",
                    "data_emissao": "-",
                    "hora_adicionado_pasta": d.get("data_importacao") or "-",
                    "emitente_nome": "-",
                    "emitente_fantasia": "-",
                    "emitente_cnpj": "-",
                    "cliente_nome": "Registrado apenas no Banco (XML ausente)",
                    "cliente_doc": "-",
                    "cliente_cidade_uf": "-",
                    "cliente_endereco": "-",
                    "itens": [],
                    "produto_veiculo_vendido": "Consultar XML original",
                    "transporte_info": "",
                    "valor_total_nf": "-",
                    "status_raw": st,
                    "status_fmt": status_fmt,
                    "lote_codigo": d.get("lote_codigo") or "-",
                    "data_bip_separacao": d.get("data_bip_separacao"),
                    "data_bip_coleta": d.get("data_bip_coleta"),
                }
                doc["texto_rag"] = (
                    f"Nota Fiscal NF {doc['numero_nf']} | Chave: {doc['chave']} | "
                    f"Hora Adicionado na Pasta: {doc['hora_adicionado_pasta']} | "
                    f"Status Bipagem: {doc['status_fmt']} | Lote: {doc['lote_codigo']}"
                )
                docs_indexados[chave_db] = doc

        self.documentos = list(docs_indexados.values())
        return self.documentos

    def buscar_rag(self, pergunta: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """
        Realiza busca híbrida (Match Exato de NF/Chave/CPF + Ranking Semântico/Léxico BM25)
        sobre os documentos XML/PDF indexados.
        """
        if not self.documentos:
            self.indexar_tudo()

        if not self.documentos:
            return []

        q_norm = _normalizar_texto(pergunta)
        tokens_q = _tokenizar(pergunta)

        # Se for uma pergunta global (listar todas, resumo, status geral, não bipadas, já bipadas), retorna todos
        if not tokens_q or any(
            termo in q_norm for termo in (
                "todas", "todos", "status geral", "resumo", "nao bipad", "ja bipad",
                "faltam bipar", "lote", "relatorio", "importad"
            )
        ):
            return self.documentos[:top_k]

        scores = []
        for doc in self.documentos:
            score = 0.0
            doc_norm = _normalizar_texto(doc.get("valores_busca") or doc["texto_rag"])

            # Boost para match exato de número da NF
            if str(doc["numero_nf"]).lower() in q_norm.split():
                score += 50.0

            # Boost para match parcial/final da chave
            if len(doc["chave"]) >= 6 and any( len(t) >= 4 and t in doc["chave"].lower() for t in tokens_q ):
                score += 30.0

            # Contagem de termos no nome do cliente, produto/veículo e texto geral
            cli_norm = _normalizar_texto(doc["cliente_nome"])
            prod_norm = _normalizar_texto(doc["produto_veiculo_vendido"])

            for tok in tokens_q:
                if tok in cli_norm:
                    score += 15.0
                if tok in prod_norm:
                    score += 12.0
                if tok in doc_norm:
                    score += 5.0

            scores.append((score, doc))

        scores.sort(key=lambda x: x[0], reverse=True)
        melhores = [d for sc, d in scores if sc > 0]

        # Se nenhum termo específico casou, devolve todos os documentos para o Agente analisar
        return melhores[:top_k] if melhores else self.documentos[:top_k]


# Instância global do índice RAG
indice_rag = IndiceRAGNotas()


def formatar_ficha_nota(doc: Dict[str, Any], idx: Optional[int] = None) -> str:
    """Formata os dados completos de uma nota extraída via RAG (XML/PDF + SQLite)."""
    prefixo = f"{idx}. " if idx is not None else "• "
    linhas = [
        f"{prefixo}📄 NOTA FISCAL Nº {doc['numero_nf']} (Série {doc.get('serie_nf', '1')}) — [{doc['status_fmt']}]",
        f"   👤 Cliente / Destinatário : {doc['cliente_nome']} (CPF/CNPJ: {doc['cliente_doc']}) — {doc['cliente_cidade_uf']}",
        f"   📦 Produto / Item Vendido : {doc['produto_veiculo_vendido']}",
        f"   💰 Valor Total da Nota    : R$ {doc['valor_total_nf']}",
        f"   🕒 Hora Adicionado Pasta  : {doc['hora_adicionado_pasta']} (Emissão NF: {doc['data_emissao']})",
        f"   🔑 Chave de Acesso (44d)  : {doc['chave']}",
        f"   🗂️ Arquivo / Lote         : {doc['nome_arquivo']} ({doc['tipo_arquivo']}) | Lote: {doc['lote_codigo']}"
    ]
    if doc.get("transporte_info"):
        linhas.append(f"   🚚 Transporte / Veículo   : {doc['transporte_info']}")
    if doc.get("data_bip_separacao") or doc.get("data_bip_coleta"):
        linhas.append(
            f"   ⏱️ Histórico de Bipagem   : 1º Bip (Separação): {doc.get('data_bip_separacao') or '-'} | "
            f"2º Bip (Coleta): {doc.get('data_bip_coleta') or '-'}"
        )
    return "\n".join(linhas)


def _chamar_llm_gratuito_ou_configurado(prompt_sistema: str, prompt_usuario: str) -> Optional[str]:
    """
    Tenta consultar um modelo LLM na seguinte ordem:
    1. Chave configurada no .env (GROQ_API_KEY, GEMINI_API_KEY ou OPENAI_API_KEY se válida).
    2. Endpoint gratuito Pollinations OpenAI-compatible (100% grátis e sem necessidade de chave!).
    Retorna None caso esteja sem internet ou indisponível, acionando o Agente Sintetizador Local.
    """
    # 1. Tentar OpenAI / Groq se houver chave válida no .env
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip().strip('"').strip("'")
    groq_key = (os.getenv("GROQ_API_KEY") or "").strip().strip('"').strip("'")

    if groq_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1", timeout=8.0)
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": prompt_usuario}
                ],
                temperature=0.2
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            pass

    if openai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key, timeout=6.0)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": prompt_usuario}
                ],
                temperature=0.2
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            pass

    # 2. Modelo Gratuito Sem Chave (Pollinations AI OpenAI-compatible endpoint)
    try:
        import urllib.request
        import json

        payload = json.dumps({
            "model": "openai",
            "messages": [
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ],
            "temperature": 0.2
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://text.pollinations.ai/openai",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "ValidadorShopeeIA/2.0"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
            if "choices" in data and data["choices"]:
                conteudo = data["choices"][0]["message"]["content"].strip()
                if conteudo:
                    return conteudo
    except Exception:
        pass

    return None


def consultar_agente_rag(pergunta: str, lote_id_filtro: Optional[int] = None, usar_llm_externo: bool = True) -> str:
    """
    Executa o pipeline completo de RAG (Retrieval-Augmented Generation):
    1. Indexa todos os XMLs e PDFs da pasta de importação (xml_entrada/ e processados/) + SQLite.
    2. Recupera os documentos relevantes para a pergunta do usuário.
    3. Gera a resposta detalhada com Número da Nota, Nome do Cliente, Produto/Veículo vendido,
       Hora adicionada na pasta e Status de Bipagem.
    """
    todos_docs = indice_rag.indexar_tudo(lote_id_filtro=lote_id_filtro)

    if not todos_docs:
        return (
            "🤖 [Agente IA & RAG — Pasta de Importação Vazia]\n\n"
            "Nenhum arquivo XML ou PDF foi encontrado na pasta 'xml_entrada/' (ou 'xml_entrada/processados/').\n"
            "👉 Adicione arquivos .xml ou .pdf de Notas Fiscais na pasta e clique em '🔄 Reindexar Pasta XML/PDF'."
        )

    docs_recuperados = indice_rag.buscar_rag(pergunta, top_k=15)

    # Montar contexto estruturado recuperado pelo RAG
    blocos_contexto = []
    for i, d in enumerate(docs_recuperados, start=1):
        blocos_contexto.append(formatar_ficha_nota(d, idx=i))
    contexto_rag_str = "\n\n".join(blocos_contexto)

    # Estatísticas globais da base indexada
    total = len(todos_docs)
    nao_bip = [d for d in todos_docs if d["status_raw"] == "NAO_BIPADO"]
    em_sep = [d for d in todos_docs if d["status_raw"] == "EM_SEPARACAO"]
    prontos = [d for d in todos_docs if d["status_raw"] == "PRONTO_COLETA"]

    resumo_topo = (
        f"📊 RESUMO DA BASE INDEXADA (RAG XML/PDF): Total: {total} nota(s) | "
        f"🔴 Não Bipadas: {len(nao_bip)} | 🟡 Em Separação: {len(em_sep)} | 🟢 Prontas p/ Coleta: {len(prontos)}"
    )

    if usar_llm_externo:
        prompt_sistema = (
            "Você é o Agente Inteligente de Auditoria com RAG do sistema 'Validador de Expedição Shopee / Bling'. "
            "Você tem acesso direto aos dados extraídos dos arquivos XML e PDF da pasta de importação e do banco SQLite.\n"
            "Ao responder ao usuário:\n"
            "1. Sempre informe com clareza para cada nota relevante:\n"
            "   - Número da Nota Fiscal (NF)\n"
            "   - Nome do Cliente / Destinatário (e Cidade/UF)\n"
            "   - Produto / Item / Veículo que foi vendido e Valor (R$)\n"
            "   - Hora exata em que foi adicionado na pasta de importação\n"
            "   - Status atual de bipagem (🔴 Não Bipado, 🟡 Em Separação ou 🟢 Pronto para Coleta)\n"
            "2. Responda em português de forma organizada, objetiva e fiel exclusivamente aos documentos recuperados abaixo."
        )
        prompt_usuario = (
            f"{resumo_topo}\n\n"
            f"DOCUMENTOS RECUPERADOS PELO RAG (XML / PDF):\n{contexto_rag_str}\n\n"
            f"PERGUNTA DO USUÁRIO:\n{pergunta}"
        )

        resposta_llm = _chamar_llm_gratuito_ou_configurado(prompt_sistema, prompt_usuario)
        if resposta_llm:
            return f"🤖 [Resposta do Agente IA + RAG (XML/PDF)]\n{resumo_topo}\n" + ("─" * 75) + f"\n\n{resposta_llm}"

    # Resposta Estruturada Nativa do Sintetizador RAG Local (instantânea e 100% precisa)
    q_norm = _normalizar_texto(pergunta)
    if "nao bipad" in q_norm or "faltam bipar" in q_norm:
        alvo = nao_bip
        titulo = f"🔴 NOTAS QUE AINDA NÃO FORAM BIPADAS ({len(alvo)} de {total})"
    elif "ja bipad" in q_norm:
        alvo = em_sep + prontos
        titulo = f"🟢 NOTAS QUE JÁ FORAM BIPADAS ({len(alvo)} de {total})"
    else:
        alvo = docs_recuperados
        titulo = f"📋 NOTAS LOCALIZADAS PELO MOTOR RAG ({len(alvo)} de {total})"

    linhas_resp = [
        f"🤖 [Agente RAG Local — Leitura Direta XML / PDF]",
        resumo_topo,
        "─" * 75,
        titulo,
        ""
    ]

    if not alvo:
        linhas_resp.append("Nenhuma nota encontrada para este filtro específico.")
    else:
        for i, d in enumerate(alvo, start=1):
            linhas_resp.append(formatar_ficha_nota(d, idx=i))
            linhas_resp.append("")

    return "\n".join(linhas_resp)
