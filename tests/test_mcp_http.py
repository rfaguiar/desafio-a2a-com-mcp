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
    assert {tool["name"] for tool in tools} == {
        "consultar_disponibilidade",
        "listar_salas",
    }
    assert all(tool["inputSchema"]["type"] == "object" for tool in tools)
    tools_por_nome = {tool["name"]: tool for tool in tools}
    assert (
        tools_por_nome["listar_salas"]["outputSchema"]["properties"]["salas"]["type"]
        == "array"
    )
    assert (
        tools_por_nome["consultar_disponibilidade"]["outputSchema"]["properties"][
            "livre"
        ]["type"]
        == "boolean"
    )


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


def test_resources_list_publica_a_politica() -> None:
    corpo, headers = request("resources/list")

    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        resposta = cliente.post("/mcp", json=corpo, headers=headers)

    assert resposta.status_code == 200
    resources = resposta.json()["result"]["resources"]
    assert [
        {
            "uri": resource["uri"],
            "mimeType": resource["mimeType"],
        }
        for resource in resources
    ] == [{"uri": "politica://uso", "mimeType": "text/markdown"}]


def test_leitura_da_politica_devolve_o_markdown_exato() -> None:
    corpo, headers = request(
        "resources/read", {"uri": "politica://uso"}, nome="politica://uso"
    )

    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        resposta = cliente.post("/mcp", json=corpo, headers=headers)

    assert resposta.status_code == 200
    resultado = resposta.json()["result"]
    assert resultado["resultType"] == "complete"
    assert resultado["contents"] == [
        {
            "uri": "politica://uso",
            "mimeType": "text/markdown",
            "text": (
                "versao: 2026-11-01\n\n"
                "- Reservas somente entre 08:00 e 20:00, horario de Sao Paulo (-03:00).\n"
                "- Duracao maxima de 2 horas por reserva.\n"
                "- Uma sala nao pode ter duas reservas sobrepostas.\n"
            ),
        }
    ]


def test_leitura_de_uri_desconhecida_devolve_invalid_params() -> None:
    corpo, headers = request(
        "resources/read",
        {"uri": "politica://inexistente"},
        nome="politica://inexistente",
    )

    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        resposta = cliente.post("/mcp", json=corpo, headers=headers)

    assert resposta.status_code == 400
    assert resposta.json()["error"]["code"] == -32602
    assert "contents" not in resposta.json().get("result", {})


def consultar(sala: str, inicio: str, fim: str) -> tuple[int, dict]:
    corpo, headers = request(
        "tools/call",
        {
            "name": "consultar_disponibilidade",
            "arguments": {"sala": sala, "inicio": inicio, "fim": fim},
        },
        nome="consultar_disponibilidade",
    )
    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        resposta = cliente.post("/mcp", json=corpo, headers=headers)
    return resposta.status_code, resposta.json()["result"]


def test_consultar_disponibilidade_devolve_intervalo_livre() -> None:
    status, resultado = consultar(
        "sala-aquario",
        "2026-11-03T09:00:00-03:00",
        "2026-11-03T10:00:00-03:00",
    )

    assert status == 200
    assert resultado["structuredContent"] == {
        "sala": "sala-aquario",
        "livre": True,
        "conflitos": [],
    }
    assert json.loads(resultado["content"][0]["text"]) == resultado["structuredContent"]


def test_consultar_disponibilidade_devolve_conflito_da_sala() -> None:
    _, resultado = consultar(
        "sala-garagem",
        "2026-11-03T14:30:00-03:00",
        "2026-11-03T15:30:00-03:00",
    )

    assert resultado["structuredContent"] == {
        "sala": "sala-garagem",
        "livre": False,
        "conflitos": [
            {
                "id": "res-0001",
                "inicio": "2026-11-03T14:00:00-03:00",
                "fim": "2026-11-03T15:00:00-03:00",
                "responsavel": "Marty",
            }
        ],
    }


@pytest.mark.parametrize(
    ("sala", "inicio", "fim", "mensagem"),
    [
        (
            "sala-delorean",
            "2026-11-03T09:00:00-03:00",
            "2026-11-03T10:00:00-03:00",
            "Sala inexistente: sala-delorean",
        ),
        (
            "sala-aquario",
            "2026-11-03T07:00:00-03:00",
            "2026-11-03T08:00:00-03:00",
            "Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00",
        ),
        (
            "sala-aquario",
            "2026-11-03T09:00:00-03:00",
            "2026-11-03T12:00:00-03:00",
            "Duracao acima do limite: a politica permite no maximo 2 horas",
        ),
        (
            "sala-aquario",
            "2026-11-03T10:00:00-03:00",
            "2026-11-03T09:00:00-03:00",
            "Intervalo invalido: fim deve ser posterior a inicio",
        ),
    ],
)
def test_consultar_disponibilidade_devolve_erros_como_is_error(
    sala: str, inicio: str, fim: str, mensagem: str
) -> None:
    status, resultado = consultar(sala, inicio, fim)

    assert status == 200
    assert resultado["isError"] is True
    assert mensagem in resultado["content"][0]["text"]
