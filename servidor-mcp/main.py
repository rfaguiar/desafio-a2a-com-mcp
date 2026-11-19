"""Ponto de entrada e composicao HTTP do servidor MCP."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import uvicorn
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .dominio import (
    ErroDominio,
    Reserva,
    alternativas_disponiveis,
    carregar_dominio,
    reservas_em_conflito,
    validar_pedido,
)
from .estado import criar_seguranca_request_state

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7301
MCP_PATH = "/mcp"


class SalaOut(BaseModel):
    id: str
    nome: str
    capacidade: int
    recursos: list[str]


class ListaDeSalas(BaseModel):
    salas: list[SalaOut]


class ConflitoOut(BaseModel):
    id: str
    inicio: str
    fim: str
    responsavel: str


class Disponibilidade(BaseModel):
    sala: str
    livre: bool
    conflitos: list[ConflitoOut]


class ResultadoReserva(BaseModel):
    reserva: str | None
    reservado: bool
    sala: str | None
    inicio: str
    fim: str
    responsavel: str
    politica: str
    motivo: str | None


class RegistroRequests:
    """Registra o envelope bruto antes de o transporte aplicar o protocolo."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        mensagens: list[Message] = []
        corpo = bytearray()
        while True:
            mensagem = await receive()
            mensagens.append(mensagem)
            if mensagem["type"] != "http.request":
                break
            corpo.extend(mensagem.get("body", b""))
            if not mensagem.get("more_body", False):
                break

        self._registrar(corpo)

        async def replay() -> Message:
            if mensagens:
                return mensagens.pop(0)
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    def _registrar(corpo: bytes | bytearray) -> None:
        metodo: Any = "<ausente>"
        request_id: Any = "<ausente>"
        traceparent: Any = "<ausente>"
        try:
            envelope = json.loads(corpo)
        except (UnicodeDecodeError, json.JSONDecodeError):
            envelope = {}
        if isinstance(envelope, dict):
            metodo = envelope.get("method", metodo)
            request_id = envelope.get("id", request_id)
            params = envelope.get("params")
            if isinstance(params, dict):
                meta = params.get("_meta")
                if isinstance(meta, dict):
                    traceparent = meta.get("traceparent", traceparent)
        print(
            f"mcp_request method={metodo} id={request_id} "
            f"traceparent={traceparent}",
            file=sys.stderr,
            flush=True,
        )


def criar_servidor() -> MCPServer:
    dominio = carregar_dominio()
    reservas = list(dominio.reservas)
    proximo_numero_reserva = (
        max(int(reserva.id.removeprefix("res-")) for reserva in reservas) + 1
    )
    servidor = MCPServer(
        "A Ponte",
        version="0.1.0",
        request_state_security=criar_seguranca_request_state(),
    )

    @servidor.tool(
        name="listar_salas",
        description="Lista todas as salas com capacidade e recursos.",
    )
    def listar_salas() -> ListaDeSalas:
        return ListaDeSalas(
            salas=[
                SalaOut(
                    id=sala.id,
                    nome=sala.nome,
                    capacidade=sala.capacidade,
                    recursos=list(sala.recursos),
                )
                for sala in dominio.salas
            ]
        )

    @servidor.tool(
        name="consultar_disponibilidade",
        description="Diz se uma sala esta livre no intervalo, e quais reservas conflitam.",
    )
    def consultar_disponibilidade(
        sala: str, inicio: str, fim: str
    ) -> Disponibilidade:
        try:
            sala_validada = validar_pedido(sala, inicio, fim, dominio.salas)
        except ErroDominio as erro:
            raise ToolError(str(erro)) from erro
        conflitos = reservas_em_conflito(
            sala_validada.id, inicio, fim, reservas
        )
        return Disponibilidade(
            sala=sala_validada.id,
            livre=not conflitos,
            conflitos=[
                ConflitoOut(
                    id=reserva.id,
                    inicio=reserva.inicio,
                    fim=reserva.fim,
                    responsavel=reserva.responsavel,
                )
                for reserva in conflitos
            ],
        )

    @servidor.tool(
        name="reservar_sala",
        description="Cria uma reserva quando a sala esta livre.",
    )
    def reservar_sala(
        sala: str, inicio: str, fim: str, responsavel: str
    ) -> ResultadoReserva:
        nonlocal proximo_numero_reserva
        try:
            sala_validada = validar_pedido(sala, inicio, fim, dominio.salas)
        except ErroDominio as erro:
            raise ToolError(str(erro)) from erro

        conflitos = reservas_em_conflito(sala_validada.id, inicio, fim, reservas)
        if conflitos:
            alternativas = alternativas_disponiveis(
                sala_validada, inicio, fim, dominio.salas, reservas
            )
            if not alternativas:
                raise ToolError("Sem alternativas disponiveis no intervalo")
            raise ToolError("A sala pedida esta ocupada nesse intervalo")

        reserva = Reserva(
            id=f"res-{proximo_numero_reserva:04d}",
            sala=sala_validada.id,
            inicio=inicio,
            fim=fim,
            responsavel=responsavel,
        )
        proximo_numero_reserva += 1
        reservas.append(reserva)
        return ResultadoReserva(
            reserva=reserva.id,
            reservado=True,
            sala=reserva.sala,
            inicio=reserva.inicio,
            fim=reserva.fim,
            responsavel=reserva.responsavel,
            politica=dominio.politica.versao,
            motivo=None,
        )

    @servidor.resource(
        "politica://uso",
        name="politica-de-uso",
        description="Politica de uso das salas de reuniao.",
        mime_type="text/markdown",
    )
    def politica_de_uso() -> str:
        return dominio.politica.texto

    return servidor


def criar_aplicacao() -> ASGIApp:
    app = criar_servidor().streamable_http_app(
        streamable_http_path=MCP_PATH,
        json_response=True,
        stateless_http=True,
    )
    return RegistroRequests(app)


def main() -> None:
    """Sobe o processo MCP usando o transporte Streamable HTTP nativo."""
    host = os.environ.get("MCP_HOST", DEFAULT_HOST)
    port = int(os.environ.get("MCP_PORT", str(DEFAULT_PORT)))
    uvicorn.run(criar_aplicacao(), host=host, port=port)
