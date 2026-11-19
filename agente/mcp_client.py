"""Cliente HTTP stateless para o servidor MCP."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any

PROTOCOLO = "2026-07-28"
CAPABILITIES = {"elicitation": {"form": {}}}


class ErroMcp(Exception):
    """Erro JSON-RPC ou de transporte recebido do servidor MCP."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class ClienteMcp:
    """Descobre capacidades em runtime e emite requests MCP independentes."""

    def __init__(self, base_url: str = "http://127.0.0.1:7301/mcp") -> None:
        self.base_url = base_url.rstrip("/")
        self._proximo_id = 1
        self._inicializado = False
        self._tools: dict[str, dict[str, Any]] = {}
        self.versao_politica: str | None = None

    def chamar_tool(
        self,
        nome: str,
        argumentos: dict[str, Any],
        *,
        input_responses: dict[str, Any] | None = None,
        request_state: str | None = None,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        self._inicializar(traceparent)
        if nome not in self._tools:
            raise ErroMcp(f"Tool MCP nao descoberta: {nome}", code=-32602)
        params: dict[str, Any] = {
            "name": nome,
            "arguments": argumentos,
        }
        if input_responses is not None:
            params["inputResponses"] = input_responses
        if request_state is not None:
            params["requestState"] = request_state
        return self._rpc("tools/call", params, nome=nome, traceparent=traceparent)

    def _inicializar(self, traceparent: str | None) -> None:
        if self._inicializado:
            return
        descoberta = self._rpc("tools/list", {}, traceparent=traceparent)
        self._tools = {
            tool["name"]: tool
            for tool in descoberta.get("tools", [])
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        }
        recurso = self._rpc(
            "resources/read",
            {"uri": "politica://uso"},
            nome="politica://uso",
            traceparent=traceparent,
        )
        contents = recurso.get("contents") or []
        if not contents or not isinstance(contents[0].get("text"), str):
            raise ErroMcp("Resource politica://uso nao devolveu texto")
        primeira_linha = contents[0]["text"].splitlines()[0]
        if not primeira_linha.startswith("versao:"):
            raise ErroMcp("Resource politica://uso nao declara versao")
        self.versao_politica = primeira_linha.removeprefix("versao:").strip()
        self._inicializado = True

    def _rpc(
        self,
        metodo: str,
        params: dict[str, Any],
        *,
        nome: str | None = None,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        request_id = self._proximo_id
        self._proximo_id += 1
        meta: dict[str, Any] = {
            "io.modelcontextprotocol/protocolVersion": PROTOCOLO,
            "io.modelcontextprotocol/clientCapabilities": CAPABILITIES,
        }
        if traceparent is not None:
            meta["traceparent"] = traceparent
        envelope = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": metodo,
            "params": {**params, "_meta": meta},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOLO,
            "Mcp-Method": metodo,
        }
        if nome is not None:
            headers["Mcp-Name"] = nome
        print(
            f"mcp_client method={metodo} id={request_id}",
            file=sys.stderr,
            flush=True,
        )
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(envelope).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as resposta:
                corpo = json.loads(resposta.read())
        except urllib.error.HTTPError as erro:
            try:
                corpo = json.loads(erro.read())
            except (TypeError, ValueError, json.JSONDecodeError) as parse:
                raise ErroMcp(f"Falha HTTP {erro.code} ao chamar MCP") from parse
        except (urllib.error.URLError, TimeoutError) as erro:
            raise ErroMcp(f"Falha de transporte MCP: {erro}") from erro
        except json.JSONDecodeError as erro:
            raise ErroMcp("Servidor MCP devolveu JSON invalido") from erro

        if "error" in corpo:
            erro = corpo["error"]
            raise ErroMcp(
                str(erro.get("message", "Erro JSON-RPC no MCP")),
                code=erro.get("code"),
                data=erro.get("data"),
            )
        resultado = corpo.get("result")
        if not isinstance(resultado, dict):
            raise ErroMcp("Resposta MCP sem objeto result")
        return resultado
