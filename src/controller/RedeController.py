import asyncio
import os
import logging
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from dao import PedidoDAO as database
from service.XmlService import XMLWatcherManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Server")

# ==============================================================================
# WEBSOCKET MANAGER
# ==============================================================================

class ConnectionManager:
    """Gerenciador de conexões WebSocket para transmissão em tempo real (< 50ms)."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Cliente WebSocket conectado. Total de conexões ativas: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Cliente WebSocket desconectado. Restantes: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        """Transmite uma mensagem JSON para todas as conexões ativas em paralelo."""
        if not self.active_connections:
            return

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Erro ao enviar para conexão WebSocket: {e}")
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)

    def broadcast_sync(self, message: Dict[str, Any]):
        """Método síncrono thread-safe para ser chamado a partir do Watcher (thread secundária)."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(message), self.loop)


ws_manager = ConnectionManager()
watcher_manager: Optional[XMLWatcherManager] = None


def callback_novo_pedido_watcher(pedido: Dict[str, Any]):
    """Callback invocado pelo Watcher quando um novo XML é importado."""
    dados_lote = database.listar_pedidos_lote_ativo()
    msg = {
        "evento": "NOVO_PEDIDO",
        "pedido": pedido,
        "estatisticas": dados_lote["estatisticas"]
    }
    ws_manager.broadcast_sync(msg)


# ==============================================================================
# LIFESPAN & FASTAPI APP
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    loop = asyncio.get_running_loop()
    ws_manager.set_loop(loop)

    database.init_db()

    global watcher_manager
    watcher_manager = XMLWatcherManager(on_novo_pedido=callback_novo_pedido_watcher)
    watcher_manager.start()
    logger.info("Servidor e XML Watcher iniciados com sucesso.")

    yield

    # Shutdown
    if watcher_manager:
        watcher_manager.stop()
    logger.info("Servidor e XML Watcher finalizados.")


app = FastAPI(
    title="Validador de Expedição API",
    description="API Backend com WebSockets para conferência e validação de bipagem de expedição Shopee/Bling",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# SCHEMAS DE REQUISIÇÃO E RESPOSTA
# ==============================================================================

class BipRequest(BaseModel):
    chave: str = Field(..., description="Chave DANFE de 44 dígitos")
    etapa: Optional[str] = Field(None, description="Etapa da bipagem: 'SEPARACAO', 'COLETA' ou None para progressão automática")
    estacao_id: Optional[str] = Field(None, description="Identificador do computador/leitor")


class NovoLoteRequest(BaseModel):
    codigo: Optional[str] = Field(None, description="Nome ou código identificador do novo lote (opcional)")
    arquivar_anterior: bool = Field(True, description="Se True, altera o lote ativo atual para 'ARQUIVADO'")


# ==============================================================================
# ENDPOINTS REST
# ==============================================================================

@app.get("/")
def read_root():
    dados_lote = database.listar_pedidos_lote_ativo()
    return {
        "status": "online",
        "mensagem": "Servidor Validador de Expedição Operacional",
        "lote_ativo": dados_lote["lote"],
        "estatisticas": dados_lote["estatisticas"]
    }


@app.get("/lotes/ativo")
def obter_lote_ativo():
    """Retorna todas as informações do lote ativo, incluindo lista de pedidos e estatísticas."""
    return database.listar_pedidos_lote_ativo()


@app.post("/lotes/novo")
async def criar_lote(req: NovoLoteRequest):
    """Cria um novo lote ativo. Arquiva o lote anterior por padrão."""
    novo_lote = database.criar_novo_lote(codigo=req.codigo, arquivar_anterior=req.arquivar_anterior)
    dados_lote = database.listar_pedidos_lote_ativo()

    msg = {
        "evento": "NOVO_LOTE",
        "lote": novo_lote,
        "estatisticas": dados_lote["estatisticas"]
    }
    await ws_manager.broadcast(msg)

    return {
        "sucesso": True,
        "mensagem": f"Novo lote '{novo_lote['codigo']}' criado com sucesso!",
        "lote": novo_lote
    }


@app.post("/lotes/arquivar")
async def arquivar_lote():
    """Arquiva o lote ativo atual."""
    sucesso = database.arquivar_lote_ativo()
    if not sucesso:
        raise HTTPException(status_code=400, detail="Nenhum lote ativo encontrado para arquivar.")

    # Cria um novo lote automático limpo após arquivar o anterior
    novo_lote = database.obter_ou_criar_lote_ativo()
    dados_lote = database.listar_pedidos_lote_ativo()

    msg = {
        "evento": "LOTE_ARQUIVADO",
        "lote": novo_lote,
        "estatisticas": dados_lote["estatisticas"]
    }
    await ws_manager.broadcast(msg)

    return {"sucesso": True, "mensagem": "Lote ativo arquivado com sucesso!", "novo_lote": novo_lote}


@app.get("/pedidos")
def listar_pedidos(status: Optional[str] = Query(None, description="Filtrar por status: NAO_BIPADO, EM_SEPARACAO, PRONTO_COLETA")):
    """Retorna os pedidos do lote ativo com filtro opcional de status."""
    dados = database.listar_pedidos_lote_ativo()
    pedidos = dados["pedidos"]
    if status:
        status_upper = status.upper()
        pedidos = [p for p in pedidos if p["status"] == status_upper]
    return {
        "lote_id": dados["lote"]["id"],
        "total_filtrado": len(pedidos),
        "pedidos": pedidos
    }


@app.post("/bipar")
async def bipar(req: BipRequest):
    """
    Endpoint principal de bipagem de DANFE.
    Transita o pedido entre etapas, registra o histórico e notifica todos os computadores via WebSockets.
    """
    res = database.bipar_pedido(chave=req.chave, etapa=req.etapa, estacao_id=req.estacao_id)
    dados_lote = database.listar_pedidos_lote_ativo()

    msg = {
        "evento": "NOVA_BIPAGEM",
        "resultado": res["resultado"],
        "mensagem": res["mensagem"],
        "chave": res["chave"],
        "pedido": res["pedido"],
        "estatisticas": dados_lote["estatisticas"],
        "estacao_id": req.estacao_id
    }
    await ws_manager.broadcast(msg)

    return res


@app.get("/historico")
def obter_historico(limit: int = Query(50, ge=1, le=500)):
    """Retorna os registros de bips mais recentes."""
    return database.obter_historico_bips(limit=limit)


# ==============================================================================
# WEBSOCKET ENDPOINT
# ==============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Canal WebSocket para múltiplos computadores na rede local.
    Permite receber atualizações em tempo real (< 50ms) e também enviar bips diretamente pela conexão.
    """
    await ws_manager.connect(websocket)

    # Enviar estado inicial do lote ativo ao conectar
    dados_lote = database.listar_pedidos_lote_ativo()
    await websocket.send_json({
        "evento": "ESTADO_INICIAL",
        "lote": dados_lote["lote"],
        "estatisticas": dados_lote["estatisticas"],
        "pedidos": dados_lote["pedidos"]
    })

    try:
        while True:
            data = await websocket.receive_json()

            # Suporte a bip enviado diretamente via WebSocket
            action = data.get("action") or data.get("evento")
            if action == "bipar":
                chave = data.get("chave", "")
                etapa = data.get("etapa")
                estacao_id = data.get("estacao_id")

                res = database.bipar_pedido(chave=chave, etapa=etapa, estacao_id=estacao_id)
                novos_dados = database.listar_pedidos_lote_ativo()

                msg_broadcast = {
                    "evento": "NOVA_BIPAGEM",
                    "resultado": res["resultado"],
                    "mensagem": res["mensagem"],
                    "chave": res["chave"],
                    "pedido": res["pedido"],
                    "estatisticas": novos_dados["estatisticas"],
                    "estacao_id": estacao_id
                }
                await ws_manager.broadcast(msg_broadcast)

            elif action == "ping":
                await websocket.send_json({"evento": "pong"})

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Exceção na conexão WebSocket: {e}")
        ws_manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("controller.RedeController:app", host="0.0.0.0", port=8000, reload=True)

