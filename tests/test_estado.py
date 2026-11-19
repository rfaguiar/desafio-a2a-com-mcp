import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver import InvalidRequestState
from mcp.server.mcpserver import Context
from mcp_types import CallToolResult, InputRequiredResult, TextContent
from starlette.testclient import TestClient

from servidor_mcp.estado import (
    REQUEST_STATE_TTL_SECONDS,
    criar_seguranca_request_state,
)

PROTOCOLO = "2026-07-28"


def _request(request_state: str | None = None) -> tuple[dict, dict[str, str]]:
    params = {
        "name": "pausar",
        "arguments": {},
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": PROTOCOLO,
            "io.modelcontextprotocol/clientCapabilities": {
                "elicitation": {"form": {}}
            },
        },
    }
    if request_state is not None:
        params["requestState"] = request_state
    return (
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": params,
        },
        {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOLO,
            "Mcp-Method": "tools/call",
            "Mcp-Name": "pausar",
        },
    )


def _app_probe() -> object:
    servidor = MCPServer(
        "probe-request-state",
        request_state_security=criar_seguranca_request_state(),
    )

    @servidor.tool(structured_output=False)
    def pausar(ctx: Context) -> CallToolResult | InputRequiredResult:
        if ctx.request_state is not None:
            return CallToolResult(
                content=[TextContent(type="text", text=ctx.request_state)]
            )
        return InputRequiredResult(request_state="pedido-original")

    app = servidor.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
    )
    return app


def test_exige_chave_externa(monkeypatch) -> None:
    monkeypatch.delenv("REQUEST_STATE_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="REQUEST_STATE_SECRET deve ser definida"):
        criar_seguranca_request_state()


def test_exige_chave_com_no_minimo_32_bytes(monkeypatch) -> None:
    monkeypatch.setenv("REQUEST_STATE_SECRET", "curta")

    with pytest.raises(RuntimeError, match="ao menos 32 bytes"):
        criar_seguranca_request_state()


def test_politica_persiste_entre_instancias_com_a_mesma_chave(monkeypatch) -> None:
    monkeypatch.setenv("REQUEST_STATE_SECRET", "x" * 32)

    primeira = criar_seguranca_request_state()
    segunda = criar_seguranca_request_state()
    payload = b'{"pedido":"original"}'
    token = primeira.codec.seal(payload)

    assert primeira.ttl == REQUEST_STATE_TTL_SECONDS == 900
    assert segunda.codec.unseal(token) == payload


def test_codec_rejeita_adulteracao_e_formato_invalido(monkeypatch) -> None:
    monkeypatch.setenv("REQUEST_STATE_SECRET", "x" * 32)
    security = criar_seguranca_request_state()
    token = security.codec.seal(b"pedido")
    adulterado = token[:-1] + ("A" if token[-1] != "A" else "B")

    with pytest.raises(InvalidRequestState):
        security.codec.unseal(adulterado)
    with pytest.raises(InvalidRequestState):
        security.codec.unseal("formato-invalido")


def test_request_state_sobrevive_a_reinstancia_com_a_mesma_chave(
    monkeypatch,
) -> None:
    monkeypatch.setenv("REQUEST_STATE_SECRET", "x" * 32)
    corpo, headers = _request()
    with TestClient(_app_probe(), base_url="http://127.0.0.1:7301") as cliente:
        estado = cliente.post("/mcp", json=corpo, headers=headers).json()["result"][
            "requestState"
        ]

    retry, headers_retry = _request(estado)
    with TestClient(_app_probe(), base_url="http://127.0.0.1:7301") as cliente:
        resposta = cliente.post("/mcp", json=retry, headers=headers_retry)

    assert resposta.status_code == 200
    assert resposta.json()["result"]["content"][0]["text"] == "pedido-original"


def test_request_state_expirado_e_rejeitado_no_wire(monkeypatch) -> None:
    monkeypatch.setenv("REQUEST_STATE_SECRET", "x" * 32)
    agora = 10_000.0
    monkeypatch.setattr("mcp.server.request_state.time.time", lambda: agora)
    corpo, headers = _request()
    with TestClient(_app_probe(), base_url="http://127.0.0.1:7301") as cliente:
        estado = cliente.post("/mcp", json=corpo, headers=headers).json()["result"][
            "requestState"
        ]

    monkeypatch.setattr("mcp.server.request_state.time.time", lambda: agora + 901)
    retry, headers_retry = _request(estado)
    with TestClient(_app_probe(), base_url="http://127.0.0.1:7301") as cliente:
        resposta = cliente.post("/mcp", json=retry, headers=headers_retry)

    assert resposta.status_code == 400
    assert resposta.json()["error"]["code"] == -32602


def test_request_state_adulterado_e_rejeitado_no_wire(monkeypatch) -> None:
    monkeypatch.setenv("REQUEST_STATE_SECRET", "x" * 32)
    corpo, headers = _request()
    with TestClient(_app_probe(), base_url="http://127.0.0.1:7301") as cliente:
        estado = cliente.post("/mcp", json=corpo, headers=headers).json()["result"][
            "requestState"
        ]
    adulterado = estado[:-1] + ("A" if estado[-1] != "A" else "B")
    retry, headers_retry = _request(adulterado)

    with TestClient(_app_probe(), base_url="http://127.0.0.1:7301") as cliente:
        resposta = cliente.post("/mcp", json=retry, headers=headers_retry)

    assert resposta.status_code == 400
    assert resposta.json()["error"]["code"] == -32602
