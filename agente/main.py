"""Ponto de entrada e servidor A2A do agente."""

from __future__ import annotations

import json
import os
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .mcp_client import ClienteMcp, ErroMcp
from .mensagens import parse_reserva, texto_da_mensagem
from .tarefas import Tarefas, novo_id

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7300


def _card(base_url: str) -> dict[str, Any]:
    return {
        "name": "Central de Salas",
        "description": "Reserva salas de reuniao da Hill Valley Tech.",
        "provider": {
            "organization": "Hill Valley Tech",
            "url": "https://hillvalley.example",
        },
        "version": "1.0.0",
        "supportedInterfaces": [
            {
                "url": f"{base_url}/a2a",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extendedAgentCard": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "reservar-sala",
                "name": "Reservar sala",
                "description": (
                    "Reserva uma sala em um intervalo. Se houver conflito, "
                    "pergunta qual alternativa usar."
                ),
                "tags": ["salas", "agenda"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
                "examples": [
                    "reservar sala=sala-garagem "
                    "inicio=2026-11-03T14:00:00-03:00 "
                    "fim=2026-11-03T15:00:00-03:00 responsavel=Marty"
                ],
            }
        ],
    }


def _texto_resultado(resultado: dict[str, Any]) -> str:
    return " ".join(
        item.get("text", "")
        for item in resultado.get("content", [])
        if isinstance(item, dict)
    )


def _rpc_error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        },
        status_code=200,
    )


def criar_aplicacao(cliente_mcp: Any | None = None) -> Starlette:
    tarefas = Tarefas()
    cliente = cliente_mcp or ClienteMcp(
        os.environ.get("MCP_URL", "http://127.0.0.1:7301/mcp")
    )
    base_url = os.environ.get("A2A_BASE_URL", "http://127.0.0.1:7300")

    async def agent_card(_request: Request) -> JSONResponse:
        return JSONResponse(_card(base_url))

    async def a2a(request: Request) -> JSONResponse:
        try:
            envelope = await request.json()
        except (TypeError, ValueError, json.JSONDecodeError):
            return _rpc_error(None, -32700, "Parse error")
        if not isinstance(envelope, dict):
            return _rpc_error(None, -32600, "Invalid Request")
        request_id = envelope.get("id")
        if envelope.get("jsonrpc") != "2.0":
            return _rpc_error(request_id, -32600, "Invalid Request")
        method = envelope.get("method")
        params = envelope.get("params")
        if not isinstance(params, dict):
            return _rpc_error(request_id, -32602, "Invalid params")

        if method == "GetTask":
            task_id = params.get("id")
            task = tarefas.obter(task_id) if isinstance(task_id, str) else None
            if task is None:
                return _rpc_error(request_id, -32602, "Task nao encontrada")
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"task": task.como_publica()},
                }
            )
        if method != "SendMessage":
            return _rpc_error(request_id, -32601, "Method not found")

        mensagem = params.get("message")
        if not isinstance(mensagem, dict):
            return _rpc_error(request_id, -32602, "Mensagem ausente")
        task_id = mensagem.get("taskId")
        if task_id is not None:
            task = tarefas.obter(task_id) if isinstance(task_id, str) else None
            if task is None:
                return _rpc_error(request_id, -32602, "Task nao encontrada")
            if task.terminal:
                return _rpc_error(
                    request_id, -32602, "Task terminal nao pode ser continuada"
                )
            task.history.append(mensagem)
            task.transicionar(
                "TASK_STATE_WORKING",
                "Continuacao ainda nao suportada nesta etapa",
            )
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"task": task.como_publica()},
                }
            )

        try:
            argumentos = parse_reserva(texto_da_mensagem(mensagem))
        except ValueError as erro:
            return _rpc_error(request_id, -32602, str(erro))
        task = tarefas.criar(mensagem, request.headers.get("traceparent"))
        task.private.argumentos_originais = argumentos
        task.transicionar("TASK_STATE_WORKING")
        try:
            resultado = cliente.chamar_tool(
                "reservar_sala",
                argumentos,
                traceparent=task.private.traceparent,
            )
        except ErroMcp as erro:
            task.transicionar("TASK_STATE_FAILED", str(erro))
        else:
            if resultado.get("isError"):
                task.transicionar(
                    "TASK_STATE_FAILED", _texto_resultado(resultado)
                )
            elif resultado.get("resultType") == "complete":
                estruturado = resultado.get("structuredContent") or {}
                reserva = {
                    "reserva": estruturado.get("reserva"),
                    "sala": estruturado.get("sala"),
                    "inicio": estruturado.get("inicio"),
                    "fim": estruturado.get("fim"),
                    "responsavel": estruturado.get("responsavel"),
                    "politica": cliente.versao_politica,
                }
                task.artifacts.append(
                    {
                        "artifactId": novo_id("art"),
                        "name": "reserva",
                        "parts": [{"text": json.dumps(reserva)}],
                    }
                )
                task.transicionar(
                    "TASK_STATE_COMPLETED",
                    f"Reserva {reserva['reserva']} confirmada na {reserva['sala']}.",
                )
            else:
                task.transicionar(
                    "TASK_STATE_FAILED",
                    "Resposta MCP inesperada pelo caminho sincrono",
                )
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"task": task.como_publica()},
            }
        )

    return Starlette(
        routes=[
            Route(
                "/.well-known/agent-card.json",
                agent_card,
                methods=["GET"],
            ),
            Route("/a2a", a2a, methods=["POST"]),
        ]
    )


def main() -> None:
    """Sobe o agente A2A no processo independente."""
    host = os.environ.get("A2A_HOST", DEFAULT_HOST)
    port = int(os.environ.get("A2A_PORT", str(DEFAULT_PORT)))
    uvicorn.run(criar_aplicacao(), host=host, port=port)
