import os
import sys
from datetime import datetime
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from dao import PedidoDAO as database

# Carrega variáveis do arquivo .env na raiz do projeto
ENV_PATH = os.path.join(database.BASE_DIR, ".env")
load_dotenv(dotenv_path=ENV_PATH)


def _calcular_duracao(dt_sep: Optional[str], dt_col: Optional[str]) -> str:
    if not dt_sep or not dt_col:
        return "-"
    try:
        t1 = datetime.strptime(dt_sep, "%Y-%m-%d %H:%M:%S")
        t2 = datetime.strptime(dt_col, "%Y-%m-%d %H:%M:%S")
        diff_sec = int((t2 - t1).total_seconds())
        mins = diff_sec // 60
        secs = diff_sec % 60
        return f"{mins}m {secs}s"
    except Exception:
        return "-"


def montar_contexto_lote(lote_id: int) -> str:
    """
    Extrai todos os dados do lote selecionado no SQLite (estatísticas, lista de NFs,
    status de cada nota, horários de bipagem e histórico de alertas) em formato estruturado
    para alimentar o modelo de IA.
    """
    dados = database.obter_dados_lote_por_id(lote_id)
    if not dados:
        return "Lote não encontrado no banco de dados."

    lote = dados["lote"]
    stats = dados["estatisticas"]
    pedidos = dados["pedidos"]
    historico = database.obter_historico_bips(lote_id=lote_id, limit=50)

    nao_bipados = [p for p in pedidos if p["status"] == "NAO_BIPADO"]
    em_separacao = [p for p in pedidos if p["status"] == "EM_SEPARACAO"]
    prontos_coleta = [p for p in pedidos if p["status"] == "PRONTO_COLETA"]

    perc_concluido = (stats["pronto_coleta"] / stats["total"] * 100) if stats["total"] > 0 else 0.0
    perc_bipados = (stats["bipados_total"] / stats["total"] * 100) if stats["total"] > 0 else 0.0

    linhas = [
        f"=== DADOS DO LOTE DE EXPEDIÇÃO ===",
        f"Código do Lote: {lote['codigo']} (ID: {lote['id']})",
        f"Status do Lote: {lote['status']}",
        f"Data de Criação: {lote.get('data_criacao') or '-'}",
        f"Data de Fechamento: {lote.get('data_fechamento') or 'Em Aberto'}",
        "",
        f"=== RESUMO ESTATÍSTICO ===",
        f"- Total de Notas Fiscais Importadas: {stats['total']}",
        f"- 🔴 Não Bipadas (Pendentes de 1º Bip): {stats['nao_bipados']}",
        f"- 🟡 Em Separação (1º Bip realizado, aguardando 2º Bip): {stats['em_separacao']}",
        f"- 🟢 Prontas para Coleta (2º Bip concluído): {stats['pronto_coleta']}",
        f"- Total Já Bipadas (Separação + Coleta): {stats['bipados_total']} ({perc_bipados:.1f}%)",
        f"- Progresso Final de Coleta: {perc_concluido:.1f}%",
        "",
        f"=== 1. NOTAS AINDA NÃO BIPADAS ({len(nao_bipados)}) ==="
    ]

    if nao_bipados:
        for p in nao_bipados:
            linhas.append(
                f"  • NF {p['numero_nf']} | Chave: {p['chave']} | Importada em: {p.get('data_importacao') or '-'}"
            )
    else:
        linhas.append("  (Nenhuma nota pendente de 1º bip)")

    linhas.append("")
    linhas.append(f"=== 2. NOTAS JÁ BIPADAS - EM SEPARAÇÃO ({len(em_separacao)}) ===")
    if em_separacao:
        for p in em_separacao:
            linhas.append(
                f"  • NF {p['numero_nf']} | Status: 🟡 Em Separação | 1º Bip: {p.get('data_bip_separacao') or '-'} | Chave: {p['chave']}"
            )
    else:
        linhas.append("  (Nenhuma nota atualmente em separação)")

    linhas.append("")
    linhas.append(f"=== 3. NOTAS JÁ BIPADAS - PRONTAS PARA COLETA ({len(prontos_coleta)}) ===")
    if prontos_coleta:
        for p in prontos_coleta:
            dur = _calcular_duracao(p.get("data_bip_separacao"), p.get("data_bip_coleta"))
            linhas.append(
                f"  • NF {p['numero_nf']} | Status: 🟢 Pronto p/ Coleta | 1º Bip: {p.get('data_bip_separacao') or '-'} | 2º Bip: {p.get('data_bip_coleta') or '-'} | Duração: {dur} | Chave: {p['chave']}"
            )
    else:
        linhas.append("  (Nenhuma nota finalizada para coleta ainda)")

    alertas = [h for h in historico if h.get("resultado") in ("FORA_DO_LOTE", "COOLDOWN", "DUPLICADO", "JA_CONCLUIDO")]
    linhas.append("")
    linhas.append(f"=== 4. OCORRÊNCIAS E ALERTAS DE BIPAGEM NO LOTE ({len(alertas)}) ===")
    if alertas:
        for a in alertas[:15]:
            linhas.append(
                f"  • [{a.get('timestamp')}] Resultado: {a.get('resultado')} | Chave: {a.get('chave')}"
            )
    else:
        linhas.append("  (Nenhum alerta de erro, duplicidade ou cooldown registrado neste lote)")

    return "\n".join(linhas)


def _analisar_localmente_ia(lote_id: int, pergunta: str) -> str:
    """
    Motor inteligente local de linguagem natural para auditoria imediata.
    Interpreta a intenção da pergunta (não bipadas, já bipadas, status geral, erros)
    e gera a análise detalhada em linguagem natural.
    """
    dados = database.obter_dados_lote_por_id(lote_id)
    if not dados:
        return "❌ Lote não encontrado no banco de dados."

    lote = dados["lote"]
    stats = dados["estatisticas"]
    pedidos = dados["pedidos"]
    historico = database.obter_historico_bips(lote_id=lote_id, limit=50)

    nao_bipados = [p for p in pedidos if p["status"] == "NAO_BIPADO"]
    em_separacao = [p for p in pedidos if p["status"] == "EM_SEPARACAO"]
    prontos_coleta = [p for p in pedidos if p["status"] == "PRONTO_COLETA"]
    ja_bipados = em_separacao + prontos_coleta

    q = pergunta.lower()

    # Caso o lote esteja vazio
    if stats["total"] == 0:
        alertas = [h for h in historico if h.get("resultado") in ("FORA_DO_LOTE", "COOLDOWN")]
        msg = (
            f"🤖 [Análise IA — {lote['codigo']}]\n"
            f"O lote '{lote['codigo']}' ({lote['status']}) está atualmente com 0 notas fiscais importadas.\n"
            f"👉 Para auditar notas neste lote, importe arquivos XML usando o botão '📂 Carregar XMLs' ou '🔄 Sincronizar Pasta'."
        )
        if alertas:
            msg += f"\n\n⚠️ Observação de Auditoria: Embora não haja XMLs importados neste lote, foram detectadas {len(alertas)} tentativa(s) de bipagem de códigos FORA DO LOTE (última chave: {alertas[0]['chave']} em {alertas[0]['timestamp']})."
        return msg

    # Intenção 1: Pergunta especificamente sobre NÃO BIPADAS / FALTAM BIPAR
    if any(termo in q for termo in ("não foram bipadas", "nao foram bipadas", "não bipadas", "nao bipadas", "faltam bipar", "falta bipar", "pendentes")):
        if not nao_bipados:
            return (
                f"🤖 [Análise IA — Notas Não Bipadas ({lote['codigo']})]\n"
                f"✅ Excelente notícia! Todas as {stats['total']} notas fiscais deste lote já receberam pelo menos o 1º bip.\n"
                f"Nenhuma nota está pendente como '🔴 Não Bipada'."
            )
        linhas = [
            f"🤖 [Análise IA — Notas que Ainda NÃO Foram Bipadas ({lote['codigo']})]",
            f"Foram identificadas {len(nao_bipados)} de {stats['total']} nota(s) aguardando o 1º Bip:\n"
        ]
        for idx, p in enumerate(nao_bipados, start=1):
            linhas.append(
                f"  {idx}. 🔴 NF {p['numero_nf']} | Chave: {p['chave']} | Importada em: {p.get('data_importacao') or '-'}"
            )
        linhas.append("\n👉 Ação recomendada: Localizar os DANFEs acima na bancada e realizar o 1º bip de entrada na separação.")
        return "\n".join(linhas)

    # Intenção 2: Pergunta especificamente sobre JÁ BIPADAS
    if any(termo in q for termo in ("já foram bipadas", "ja foram bipadas", "já bipadas", "ja bipadas")) and "status geral" not in q:
        if not ja_bipados:
            return (
                f"🤖 [Análise IA — Notas Já Bipadas ({lote['codigo']})]\n"
                f"⚠️ Nenhuma das {stats['total']} notas fiscais deste lote foi bipada até o momento.\n"
                f"Todas as {stats['nao_bipados']} notas continuam com status '🔴 Não Bipado'."
            )
        linhas = [
            f"🤖 [Análise IA — Notas Fiscais JÁ Bipadas ({lote['codigo']})]",
            f"Total de notas já bipadas: {len(ja_bipados)} de {stats['total']} ({len(em_separacao)} em Separação | {len(prontos_coleta)} Prontas p/ Coleta):\n"
        ]
        if em_separacao:
            linhas.append(f"🟡 EM SEPARAÇÃO (1º Bip realizado — {len(em_separacao)}):")
            for p in em_separacao:
                linhas.append(
                    f"  • NF {p['numero_nf']} | 1º Bip: {p.get('data_bip_separacao') or '-'} | Chave final: ...{p['chave'][-8:]}"
                )
        if prontos_coleta:
            if em_separacao:
                linhas.append("")
            linhas.append(f"🟢 PRONTAS PARA COLETA (1º e 2º Bips concluídos — {len(prontos_coleta)}):")
            for p in prontos_coleta:
                dur = _calcular_duracao(p.get("data_bip_separacao"), p.get("data_bip_coleta"))
                linhas.append(
                    f"  • NF {p['numero_nf']} | 1º Bip: {p.get('data_bip_separacao')} | 2º Bip: {p.get('data_bip_coleta')} | Tempo Separação: {dur}"
                )
        return "\n".join(linhas)

    # Intenção 3: Diagnóstico / Status Geral Completo do Lote (ou qualquer outra pergunta)
    perc_coleta = (stats["pronto_coleta"] / stats["total"] * 100) if stats["total"] > 0 else 0.0
    perc_bip = (stats["bipados_total"] / stats["total"] * 100) if stats["total"] > 0 else 0.0
    alertas = [h for h in historico if h.get("resultado") in ("FORA_DO_LOTE", "COOLDOWN", "DUPLICADO", "JA_CONCLUIDO")]

    linhas = [
        f"🤖 [Diagnóstico Geral de Auditoria IA — {lote['codigo']} ({lote['status']})]",
        f"📊 Resumo Executivo do Lote (Criado em {lote.get('data_criacao') or '-'}):",
        f"  • Total Importado: {stats['total']} Nota(s) Fiscal(is)",
        f"  • 🔴 Não Bipadas (Pendentes): {stats['nao_bipados']} nota(s)",
        f"  • 🟡 Em Separação (1º Bip): {stats['em_separacao']} nota(s)",
        f"  • 🟢 Prontas para Coleta (2º Bip): {stats['pronto_coleta']} nota(s) ({perc_coleta:.1f}% concluído)",
        ""
    ]

    if nao_bipados:
        nfs_pend = ", ".join(f"NF {p['numero_nf']}" for p in nao_bipados)
        linhas.append(f"🔴 Pendências de Bipagem ({len(nao_bipados)}): {nfs_pend}")
    else:
        linhas.append("✅ Pendências de 1º Bip: Nenhuma (100% das notas já iniciaram separação).")

    if em_separacao:
        nfs_sep = ", ".join(f"NF {p['numero_nf']} (1º bip às {p.get('data_bip_separacao')})" for p in em_separacao)
        linhas.append(f"🟡 Aguardando 2º Bip de Coleta ({len(em_separacao)}): {nfs_sep}")

    if prontos_coleta:
        nfs_col = ", ".join(f"NF {p['numero_nf']}" for p in prontos_coleta)
        linhas.append(f"🟢 Liberadas para Coleta ({len(prontos_coleta)}): {nfs_col}")

    if alertas:
        linhas.append(f"\n⚠️ Ocorrências de Auditoria Registradas ({len(alertas)}):")
        for a in alertas[:5]:
            linhas.append(f"  • [{a.get('timestamp')}] {a.get('resultado')} — Chave: {a.get('chave')}")

    return "\n".join(linhas)


def consultar_ia_auditoria(lote_id: int, pergunta: str) -> str:
    """
    Envia os dados reais do lote selecionado e a solicitação do operador para o modelo
    GPT-4o-mini da OpenAI. Caso a chave da API esteja sem saldo/expirada ou sem internet,
    aciona automaticamente o motor inteligente local de linguagem natural.
    """
    contexto_lote = montar_contexto_lote(lote_id)
    api_key = os.getenv("OPENAI_API_KEY")

    if api_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key.strip().strip('"').strip("'"))

            system_prompt = (
                "Você é o Assistente Inteligente de Auditoria Logística do sistema 'Validador de Expedição Shopee / Bling'. "
                "Sua função é analisar os dados reais do lote de Notas Fiscais (NF-e) fornecido e responder com total exatidão, "
                "clareza e objetividade em português.\n\n"
                "Regras importantes:\n"
                "1. Use APENAS os dados reais do lote fornecidos no contexto. Nunca invente números de NF ou chaves.\n"
                "2. Quando o usuário pedir as notas NÃO BIPADAS, liste claramente cada Nº de NF (e os últimos dígitos da chave/horário de importação) com o indicador 🔴.\n"
                "3. Quando o usuário pedir as notas JÁ BIPADAS, separe claramente entre 🟡 Em Separação (1º Bip) e 🟢 Prontas para Coleta (2º Bip), informando os horários.\n"
                "4. Quando o usuário pedir um STATUS GERAL DO LOTE, apresente um resumo executivo contendo: Total de NFs, quantas e quais faltam bipar, quantas estão em separação, quantas estão prontas para coleta (% de conclusão) e se houve alertas (como tentativas em Cooldown de 300s ou notas Fora do Lote).\n"
                "5. Se o lote tiver 0 notas importadas, informe de maneira amigável que o lote está vazio e oriente a carregar/sincronizar os arquivos XML."
            )

            user_message = (
                f"DADOS ATUAIS DO LOTE NO BANCO DE DADOS:\n{contexto_lote}\n\n"
                f"SOLICITAÇÃO DO AUDITOR:\n{pergunta}"
            )

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.2
            )

            return response.choices[0].message.content.strip()

        except Exception:
            # Fallback silencioso e transparente para o Motor Inteligente Local
            return _analisar_localmente_ia(lote_id, pergunta)

    return _analisar_localmente_ia(lote_id, pergunta)
