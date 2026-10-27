import os
import sys
import shutil
import time
import logging
import xml.etree.ElementTree as ET
from typing import Callable, Optional, List, Dict, Any
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from dao.PedidoDAO import inserir_pedido, DEFAULT_DB_PATH, get_base_dir

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Watcher")

BASE_DIR = get_base_dir()
DEFAULT_WATCH_DIR = os.path.join(BASE_DIR, "xml_entrada")
DEFAULT_PROCESSED_DIR = os.path.join(DEFAULT_WATCH_DIR, "processados")


def garantir_diretorios(watch_dir: str = DEFAULT_WATCH_DIR, processed_dir: str = DEFAULT_PROCESSED_DIR) -> None:
    """Cria os diretórios de entrada e processados se não existirem."""
    os.makedirs(watch_dir, exist_ok=True)
    os.makedirs(processed_dir, exist_ok=True)


def extrair_dados_xml(caminho_xml: str) -> Optional[Dict[str, str]]:
    """
    Lê o arquivo XML de NF-e e extrai a chave de 44 dígitos e o número da NF.
    Retorna dict com 'chave' e 'numero_nf', ou None se inválido/falhar.
    """
    try:
        # Aguardar caso o arquivo ainda esteja sendo gravado no disco
        for attempt in range(5):
            try:
                tree = ET.parse(caminho_xml)
                root = tree.getroot()
                break
            except (ET.ParseError, PermissionError):
                if attempt == 4:
                    raise
                time.sleep(0.1)

        inf_nfe = None
        for elem in root.iter():
            if elem.tag.endswith('infNFe'):
                inf_nfe = elem
                break

        if inf_nfe is None:
            logger.warning(f"Tag infNFe não encontrada no arquivo {caminho_xml}")
            return None

        raw_id = inf_nfe.attrib.get('Id', '')
        chave = raw_id.replace('NFe', '').strip()

        num_nf = "N/A"
        for elem in root.iter():
            if elem.tag.endswith('nNF'):
                num_nf = elem.text or "N/A"
                break

        if len(chave) == 44:
            return {"chave": chave, "numero_nf": num_nf}
        else:
            logger.warning(f"Chave extraída do XML ({chave}) não possui 44 dígitos no arquivo {caminho_xml}")
            return None

    except Exception as e:
        logger.error(f"Erro ao processar o arquivo XML {caminho_xml}: {e}")
        return None


def processar_arquivo_xml(
    caminho_xml: str,
    watch_dir: str = DEFAULT_WATCH_DIR,
    processed_dir: str = DEFAULT_PROCESSED_DIR,
    db_path: str = DEFAULT_DB_PATH,
    on_novo_pedido: Optional[Callable[[Dict[str, Any]], None]] = None
) -> bool:
    """
    Processa um único arquivo XML:
    1. Extrai chave e numero_nf.
    2. Salva no banco de dados pedidos.db no lote ativo.
    3. Move o XML para xml_entrada/processados/.
    4. Notifica via callback (se fornecido).
    """
    if not os.path.exists(caminho_xml) or not caminho_xml.lower().endswith(".xml"):
        return False

    nome_arquivo = os.path.basename(caminho_xml)
    dados = extrair_dados_xml(caminho_xml)

    if not dados:
        # Se for XML inválido, ainda assim move para evitarmos loop infinito
        garantir_diretorios(watch_dir, processed_dir)
        destino_invalido = os.path.join(processed_dir, f"INVALIDO_{nome_arquivo}")
        try:
            shutil.move(caminho_xml, destino_invalido)
        except Exception as e:
            logger.error(f"Erro ao mover XML inválido {nome_arquivo}: {e}")
        return False

    # Inserir no banco de dados SQLite
    pedido, foi_inserido = inserir_pedido(
        chave=dados["chave"],
        numero_nf=dados["numero_nf"],
        arquivo_xml=nome_arquivo,
        db_path=db_path
    )

    # Mover arquivo para a pasta processados
    garantir_diretorios(watch_dir, processed_dir)
    destino = os.path.join(processed_dir, nome_arquivo)
    
    # Tratar colisão de nomes na pasta processados
    if os.path.exists(destino):
        base, ext = os.path.splitext(nome_arquivo)
        destino = os.path.join(processed_dir, f"{base}_{int(time.time())}{ext}")

    try:
        shutil.move(caminho_xml, destino)
        logger.info(f"XML {nome_arquivo} processado com sucesso (NF: {dados['numero_nf']}). Movido para {destino}")
    except Exception as e:
        logger.error(f"Erro ao mover arquivo processado {nome_arquivo}: {e}")

    # Notificar WebSocket / Callback
    if on_novo_pedido and foi_inserido:
        try:
            on_novo_pedido(pedido)
        except Exception as e:
            logger.error(f"Erro ao executar callback on_novo_pedido: {e}")

    return foi_inserido


def processar_pasta_existente(
    watch_dir: str = DEFAULT_WATCH_DIR,
    processed_dir: str = DEFAULT_PROCESSED_DIR,
    db_path: str = DEFAULT_DB_PATH,
    on_novo_pedido: Optional[Callable[[Dict[str, Any]], None]] = None
) -> Dict[str, int]:
    """Varre a pasta de entrada xml_entrada e processa todos os arquivos .xml pendentes."""
    garantir_diretorios(watch_dir, processed_dir)
    if not os.path.exists(watch_dir):
        return {"inseridos": 0, "duplicados": 0, "totais": 0}

    arquivos = [
        os.path.join(watch_dir, f) for f in os.listdir(watch_dir)
        if f.lower().endswith('.xml') and os.path.isfile(os.path.join(watch_dir, f))
    ]

    inseridos = 0
    duplicados = 0

    for arq in arquivos:
        foi_ins = processar_arquivo_xml(arq, watch_dir, processed_dir, db_path, on_novo_pedido)
        if foi_ins:
            inseridos += 1
        else:
            duplicados += 1

    return {"inseridos": inseridos, "duplicados": duplicados, "totais": len(arquivos)}


class XMLFolderHandler(FileSystemEventHandler):
    """Event Handler para o Watchdog monitorar novos arquivos XML."""

    def __init__(self, watch_dir: str, processed_dir: str, db_path: str, on_novo_pedido: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.watch_dir = watch_dir
        self.processed_dir = processed_dir
        self.db_path = db_path
        self.on_novo_pedido = on_novo_pedido

    def _tratar_evento(self, event):
        if event.is_directory:
            return
        if event.src_path.lower().endswith(".xml"):
            # Pequena pausa para garantir finalização da escrita no disco
            time.sleep(0.15)
            processar_arquivo_xml(
                event.src_path,
                self.watch_dir,
                self.processed_dir,
                self.db_path,
                self.on_novo_pedido
            )

    def on_created(self, event: FileCreatedEvent):
        self._tratar_evento(event)

    def on_modified(self, event: FileModifiedEvent):
        self._tratar_evento(event)


class XMLWatcherManager:
    """Gerenciador do Folder Watcher com suporte a Watchdog e Polling de backup."""

    def __init__(
        self,
        watch_dir: str = DEFAULT_WATCH_DIR,
        processed_dir: str = DEFAULT_PROCESSED_DIR,
        db_path: str = DEFAULT_DB_PATH,
        on_novo_pedido: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        self.watch_dir = watch_dir
        self.processed_dir = processed_dir
        self.db_path = db_path
        self.on_novo_pedido = on_novo_pedido
        self.observer: Optional[Observer] = None
        self.running = False

    def start(self) -> None:
        """Inicia o monitoramento de arquivos."""
        garantir_diretorios(self.watch_dir, self.processed_dir)

        # 1. Processar arquivos já existentes
        processar_pasta_existente(self.watch_dir, self.processed_dir, self.db_path, self.on_novo_pedido)

        # 2. Iniciar Watchdog Observer
        event_handler = XMLFolderHandler(self.watch_dir, self.processed_dir, self.db_path, self.on_novo_pedido)
        self.observer = Observer()
        self.observer.schedule(event_handler, path=self.watch_dir, recursive=False)
        self.observer.start()
        self.running = True
        logger.info(f"XML Watcher iniciado na pasta: {self.watch_dir}")

    def stop(self) -> None:
        """Para o monitoramento de arquivos."""
        if self.observer and self.running:
            self.observer.stop()
            self.observer.join()
            self.running = False
            logger.info("XML Watcher finalizado.")


if __name__ == "__main__":
    print(f"Iniciando Watcher em: {DEFAULT_WATCH_DIR}")
    watcher = XMLWatcherManager()
    watcher.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        watcher.stop()

