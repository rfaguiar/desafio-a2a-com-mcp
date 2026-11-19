"""Configuracao da protecao de requestState entre requests MCP."""

from __future__ import annotations

import os

from mcp.server.mcpserver import RequestStateSecurity

REQUEST_STATE_SECRET_ENV = "REQUEST_STATE_SECRET"
REQUEST_STATE_TTL_SECONDS = 15 * 60
REQUEST_STATE_SECRET_MIN_BYTES = 32


def criar_seguranca_request_state() -> RequestStateSecurity:
    """Cria a politica compartilhavel, falhando cedo se a chave for insegura."""
    valor = os.environ.get(REQUEST_STATE_SECRET_ENV)
    if valor is None:
        raise RuntimeError(
            f"{REQUEST_STATE_SECRET_ENV} deve ser definida antes de iniciar o servidor"
        )
    chave = valor.encode("utf-8")
    if len(chave) < REQUEST_STATE_SECRET_MIN_BYTES:
        raise RuntimeError(
            f"{REQUEST_STATE_SECRET_ENV} deve conter ao menos "
            f"{REQUEST_STATE_SECRET_MIN_BYTES} bytes"
        )
    return RequestStateSecurity(
        keys=[chave],
        ttl=REQUEST_STATE_TTL_SECONDS,
        bind_principal=lambda _ctx: None,
    )
