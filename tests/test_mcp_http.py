import json

import pytest
from starlette.testclient import TestClient

from servidor_mcp.main import criar_aplicacao

PROTOCOLO = "2026-07-28"
CAPABILITIES = {"elicitation": {"form": {}}}


def request(
    method: str,
    params: dict | None = None,
    *,
    nome: str | None = None,
    omitido: str | None = None,
    traceparent: str | None = None,
) -> tuple[dict, dict[str, str]]:
    meta = {
        "io.modelcontextprotocol/protocolVersion": PROTOCOLO,
        "io.modelcontextprotocol/clientCapabilities": CAPABILITIES,
    }
    if omitido == "protocolVersion":
        meta.pop("io.modelcontextprotocol/protocolVersion")
    if omitido == "clientCapabilities":
        meta.pop("io.modelcontextprotocol/clientCapabilities")
    if traceparent is not None:
        meta["traceparent"] = traceparent

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOLO,
        "Mcp-Method": method,
    }
    if nome is not None:
        headers["Mcp-Name"] = nome
    return (
        {
            "jsonrpc": "2.0",
            "id": 17,
            "method": method,
            "params": {**(params or {}), "_meta": meta},
        },
        headers,
    )


def test_tools_list_publica_apenas_listar_salas_com_schemas() -> None:
    corpo, headers = request("tools/list")

    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        resposta = cliente.post("/mcp", json=corpo, headers=headers)

    assert resposta.status_code == 200
    tools = resposta.json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["listar_salas"]
    assert tools[0]["inputSchema"]["type"] == "object"
    assert tools[0]["outputSchema"]["properties"]["salas"]["type"] == "array"


def test_listar_salas_devolve_as_cinco_salas_em_texto_e_estruturado() -> None:
    corpo, headers = request(
        "tools/call", {"name": "listar_salas", "arguments": {}}, nome="listar_salas"
    )

    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        resposta = cliente.post("/mcp", json=corpo, headers=headers)

    assert resposta.status_code == 200
    resultado = resposta.json()["result"]
    assert resultado["resultType"] == "complete"
    assert len(resultado["structuredContent"]["salas"]) == 5
    assert json.loads(resultado["content"][0]["text"]) == resultado["structuredContent"]


@pytest.mark.parametrize("campo_omitido", ["protocolVersion", "clientCapabilities"])
def test_rejeita_meta_incompleto_sem_inferir_request_anterior(
    campo_omitido: str,
) -> None:
    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        valido, headers_validos = request("tools/list")
        assert cliente.post("/mcp", json=valido, headers=headers_validos).status_code == 200

        incompleto, headers_incompletos = request(
            "tools/list", omitido=campo_omitido
        )
        resposta = cliente.post("/mcp", json=incompleto, headers=headers_incompletos)

    assert resposta.status_code == 400
    assert resposta.json()["error"]["code"] == -32602


def test_rejeita_header_que_nao_espelha_o_body() -> None:
    corpo, headers = request("tools/list")
    headers["Mcp-Method"] = "resources/list"

    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        resposta = cliente.post("/mcp", json=corpo, headers=headers)

    assert resposta.status_code == 400
    assert resposta.json()["error"]["code"] == -32020


def test_rejeita_mcp_name_diferente_do_nome_da_tool() -> None:
    corpo, headers = request(
        "tools/call", {"name": "listar_salas", "arguments": {}}, nome="outra_tool"
    )

    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        resposta = cliente.post("/mcp", json=corpo, headers=headers)

    assert resposta.status_code == 400
    assert resposta.json()["error"]["code"] == -32020


def test_registra_metodo_id_e_traceparent_no_stderr(capsys) -> None:
    traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    corpo, headers = request("tools/list", traceparent=traceparent)

    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        cliente.post("/mcp", json=corpo, headers=headers)

    log = capsys.readouterr().err
    assert "method=tools/list" in log
    assert "id=17" in log
    assert f"traceparent={traceparent}" in log
