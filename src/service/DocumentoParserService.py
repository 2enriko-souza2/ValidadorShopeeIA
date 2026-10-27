import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, Any, List, Optional


def _limpar_tag(tag: str) -> str:
    """Remove o namespace XML (ex: '{http://www.portalfiscal.inf.br/nfe}xNome' -> 'xNome')."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _obter_hora_arquivo(caminho: str) -> str:
    """Retorna a data/hora formatada em que o arquivo foi adicionado/modificado na pasta."""
    try:
        ts = os.path.getmtime(caminho)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def extrair_metadados_xml(caminho_xml: str) -> Optional[Dict[str, Any]]:
    """
    Lê um arquivo XML de NF-e (Bling / Shopee / SEFAZ) e extrai todos os dados ricos
    para indexação no RAG e exibição pelo Agente de IA:
      - Número da Nota (nNF) e Série
      - Chave de Acesso (44 dígitos)
      - Nome do Cliente / Destinatário, CPF/CNPJ e Cidade/UF
      - Produtos / Itens / Veículos vendidos (código, descrição, quantidade, valor)
      - Dados de Transporte / Veículo (se houver)
      - Valor Total da NF
      - Hora em que foi adicionado na pasta de importação
    """
    if not os.path.exists(caminho_xml):
        return None

    try:
        for attempt in range(4):
            try:
                tree = ET.parse(caminho_xml)
                root = tree.getroot()
                break
            except (ET.ParseError, PermissionError):
                if attempt == 3:
                    raise
                time.sleep(0.1)

        chave = ""
        numero_nf = "N/A"
        serie_nf = "1"
        data_emissao = "-"
        nat_op = "Venda"

        emitente_nome = "-"
        emitente_fantasia = "-"
        emitente_cnpj = "-"

        cliente_nome = "Não informado"
        cliente_doc = "-"
        cliente_cidade = ""
        cliente_uf = ""
        cliente_endereco = ""

        valor_total_nf = "0.00"
        transportadora_nome = ""
        placa_veiculo = ""
        itens: List[Dict[str, Any]] = []

        # Localizar infNFe
        inf_nfe = None
        for elem in root.iter():
            if _limpar_tag(elem.tag) == "infNFe":
                inf_nfe = elem
                raw_id = elem.attrib.get("Id", "")
                chave = raw_id.replace("NFe", "").strip()
                break

        if inf_nfe is None:
            return None

        # Percorrer blocos principais filhos de infNFe
        for bloco in inf_nfe:
            nome_bloco = _limpar_tag(bloco.tag)

            if nome_bloco == "ide":
                for sub in bloco:
                    t = _limpar_tag(sub.tag)
                    val = (sub.text or "").strip()
                    if t == "nNF":
                        numero_nf = val
                    elif t == "serie":
                        serie_nf = val
                    elif t == "dhEmi":
                        data_emissao = val[:19].replace("T", " ")
                    elif t == "natOp":
                        nat_op = val

            elif nome_bloco == "emit":
                for sub in bloco:
                    t = _limpar_tag(sub.tag)
                    val = (sub.text or "").strip()
                    if t == "xNome":
                        emitente_nome = val
                    elif t == "xFant":
                        emitente_fantasia = val
                    elif t == "CNPJ":
                        emitente_cnpj = val

            elif nome_bloco == "dest":
                rua, nro, bairro = "", "", ""
                for sub in bloco:
                    t = _limpar_tag(sub.tag)
                    val = (sub.text or "").strip()
                    if t == "xNome":
                        cliente_nome = val
                    elif t in ("CPF", "CNPJ"):
                        cliente_doc = val
                    elif t == "enderDest":
                        for end_sub in sub:
                            et = _limpar_tag(end_sub.tag)
                            eval_txt = (end_sub.text or "").strip()
                            if et == "xLgr":
                                rua = eval_txt
                            elif et == "nro":
                                nro = eval_txt
                            elif et == "xBairro":
                                bairro = eval_txt
                            elif et == "xMun":
                                cliente_cidade = eval_txt
                            elif et == "UF":
                                cliente_uf = eval_txt
                partes_end = [p for p in (f"{rua}, {nro}".strip(", "), bairro, f"{cliente_cidade}/{cliente_uf}".strip("/")) if p]
                cliente_endereco = " - ".join(partes_end)

            elif nome_bloco == "det":
                c_prod, x_prod, q_com, v_un, v_prod = "", "", "1", "0.00", "0.00"
                veic_prod_info = ""
                for sub in bloco:
                    if _limpar_tag(sub.tag) == "prod":
                        for psub in sub:
                            pt = _limpar_tag(psub.tag)
                            pval = (psub.text or "").strip()
                            if pt == "cProd":
                                c_prod = pval
                            elif pt == "xProd":
                                x_prod = pval
                            elif pt == "qCom":
                                try:
                                    q_com = f"{float(pval):g}"
                                except Exception:
                                    q_com = pval
                            elif pt == "vUnCom":
                                try:
                                    v_un = f"{float(pval):.2f}"
                                except Exception:
                                    v_un = pval
                            elif pt == "vProd":
                                try:
                                    v_prod = f"{float(pval):.2f}"
                                except Exception:
                                    v_prod = pval
                            elif pt == "veicProd":
                                # Caso a NF-e tenha tag específica de veículo novo (veicProd)
                                dados_v = []
                                for vsub in psub:
                                    vt = _limpar_tag(vsub.tag)
                                    vval = (vsub.text or "").strip()
                                    if vt in ("chassi", "nMotor", "anoMod", "anoFab", "xCor") and vval:
                                        dados_v.append(f"{vt}:{vval}")
                                if dados_v:
                                    veic_prod_info = " (" + ", ".join(dados_v) + ")"

                if x_prod or c_prod:
                    desc_completa = f"{x_prod}{veic_prod_info}".strip()
                    itens.append({
                        "codigo": c_prod,
                        "descricao": desc_completa,
                        "quantidade": q_com,
                        "valor_unitario": v_un,
                        "valor_total": v_prod
                    })

            elif nome_bloco == "total":
                for sub in bloco.iter():
                    if _limpar_tag(sub.tag) == "vNF" and sub.text:
                        try:
                            valor_total_nf = f"{float(sub.text.strip()):.2f}"
                        except Exception:
                            valor_total_nf = sub.text.strip()

            elif nome_bloco == "transp":
                for sub in bloco.iter():
                    st = _limpar_tag(sub.tag)
                    sval = (sub.text or "").strip()
                    if st == "xNome" and sval:
                        transportadora_nome = sval
                    elif st == "placa" and sval:
                        placa_veiculo = sval

        hora_pasta = _obter_hora_arquivo(caminho_xml)
        cidade_uf = f"{cliente_cidade}/{cliente_uf}".strip("/") if (cliente_cidade or cliente_uf) else "-"

        # Montar resumo legível de produtos/veículos vendidos
        if itens:
            resumo_itens = " | ".join(
                f"[{it['codigo']}] {it['descricao']} ({it['quantidade']}x R$ {it['valor_unitario']})"
                if it["codigo"] else f"{it['descricao']} ({it['quantidade']}x)"
                for it in itens
            )
        else:
            resumo_itens = "Sem itens detalhados"

        info_transp = ""
        if transportadora_nome or placa_veiculo:
            info_transp = f"Transp: {transportadora_nome} {f'(Placa: {placa_veiculo})' if placa_veiculo else ''}".strip()

        return {
            "tipo_arquivo": "XML",
            "nome_arquivo": os.path.basename(caminho_xml),
            "caminho_arquivo": caminho_xml,
            "numero_nf": numero_nf,
            "serie_nf": serie_nf,
            "chave": chave,
            "natureza_operacao": nat_op,
            "data_emissao": data_emissao,
            "hora_adicionado_pasta": hora_pasta,
            "emitente_nome": emitente_nome,
            "emitente_fantasia": emitente_fantasia,
            "emitente_cnpj": emitente_cnpj,
            "cliente_nome": cliente_nome,
            "cliente_doc": cliente_doc,
            "cliente_cidade_uf": cidade_uf,
            "cliente_endereco": cliente_endereco,
            "itens": itens,
            "produto_veiculo_vendido": resumo_itens,
            "transporte_info": info_transp,
            "valor_total_nf": valor_total_nf
        }

    except Exception as e:
        print(f"Erro ao extrair metadados do XML {caminho_xml}: {e}")
        return None


def extrair_metadados_pdf(caminho_pdf: str) -> Optional[Dict[str, Any]]:
    """
    Lê um arquivo PDF de Nota Fiscal / DANFE usando PyPDF2/pypdf e extrai:
    - Chave de acesso de 44 dígitos (se houver)
    - Número da Nota (NF)
    - Nome do Cliente / Destinatário
    - Produto / Veículo vendido
    - Valor Total e Hora em que foi adicionado na pasta
    """
    if not os.path.exists(caminho_pdf):
        return None

    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(caminho_pdf)
        texto_paginas = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                texto_paginas.append(t)
        texto_bruto = "\n".join(texto_paginas).strip()
    except Exception as e:
        print(f"Erro ao ler PDF {caminho_pdf}: {e}")
        return None

    hora_pasta = _obter_hora_arquivo(caminho_pdf)
    nome_arq = os.path.basename(caminho_pdf)

    # 1. Tentar localizar chave de 44 dígitos (com ou sem espaços)
    apenas_digitos = re.sub(r"\D", "", texto_bruto)
    match_chave = re.search(r"(\d{44})", apenas_digitos)
    chave = match_chave.group(1) if match_chave else f"PDF_{os.path.splitext(nome_arq)[0]}"

    # 2. Tentar localizar Número da NF
    match_nf = re.search(r"(?:N[º°o\.]?\s*(?:DA\s*)?NF(?:-e)?|N[úu]mero)\s*[:\-]?\s*([\d\.]+)", texto_bruto, re.IGNORECASE)
    numero_nf = match_nf.group(1).replace(".", "") if match_nf else "PDF"

    # 3. Tentar localizar Cliente / Destinatário
    match_cli = re.search(r"(?:DESTINAT[ÁA]RIO|CLIENTE|NOME\s*/\s*RAZ[ÃA]O\s*SOCIAL)\s*[:\-]?\s*([^\n\r]{3,60})", texto_bruto, re.IGNORECASE)
    cliente_nome = match_cli.group(1).strip() if match_cli else "Extraído de PDF (Ver Conteúdo)"

    # 4. Tentar localizar Valor Total
    match_val = re.search(r"(?:VALOR\s*TOTAL\s*(?:DA\s*NOTA)?|TOTAL\s*R\$)\s*[:\-]?\s*R?\$?\s*([\d\.,]+)", texto_bruto, re.IGNORECASE)
    valor_total_nf = match_val.group(1).strip() if match_val else "-"

    # Resumo das primeiras linhas úteis para item/veículo vendido
    linhas_uteis = [ln.strip() for ln in texto_bruto.splitlines() if len(ln.strip()) > 4]
    resumo_texto = " | ".join(linhas_uteis[:6]) if linhas_uteis else "Documento PDF importado"

    return {
        "tipo_arquivo": "PDF",
        "nome_arquivo": nome_arq,
        "caminho_arquivo": caminho_pdf,
        "numero_nf": numero_nf,
        "serie_nf": "1",
        "chave": chave,
        "natureza_operacao": "Documento PDF",
        "data_emissao": hora_pasta,
        "hora_adicionado_pasta": hora_pasta,
        "emitente_nome": "-",
        "emitente_fantasia": "-",
        "emitente_cnpj": "-",
        "cliente_nome": cliente_nome,
        "cliente_doc": "-",
        "cliente_cidade_uf": "-",
        "cliente_endereco": "-",
        "itens": [{"codigo": "PDF", "descricao": resumo_texto[:120], "quantidade": "1", "valor_unitario": valor_total_nf, "valor_total": valor_total_nf}],
        "produto_veiculo_vendido": resumo_texto[:180],
        "transporte_info": "",
        "valor_total_nf": valor_total_nf,
        "texto_integral_pdf": texto_bruto[:3000]
    }
