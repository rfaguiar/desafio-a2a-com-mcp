import json

import pytest
from starlette.testclient import TestClient

from servidor_mcp.main import criar_aplicacao

PROTOCOLO = "2026-07-28"
CAPABILITIES = {"elicitation": {"form": {}}}


@pytest.fixture(autouse=True)
def request_state_secret(monkeypatch) -> None:
    monkeypatch.setenv("REQUEST_STATE_SECRET", "test-key-" + ("x" * 32))


def request(
    method: str,
    params: dict | None = None,
    *,
    nome: str | None = None,
    omitido: str | None = None,
    traceparent: str | None = None,
    capabilities: dict | None = None,
) -> tuple[dict, dict[str, str]]:
    meta = {
        "io.modelcontextprotocol/protocolVersion": PROTOCOLO,
        "io.modelcontextprotocol/clientCapabilities": (
            CAPABILITIES if capabilities is None else capabilities
        ),
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
        "reservar_sala",
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


def reservar(
    cliente: TestClient,
    sala: str,
    inicio: str,
    fim: str,
    responsavel: str = "Doc",
) -> tuple[int, dict]:
    corpo, headers = request(
        "tools/call",
        {
            "name": "reservar_sala",
            "arguments": {
                "sala": sala,
                "inicio": inicio,
                "fim": fim,
                "responsavel": responsavel,
            },
        },
        nome="reservar_sala",
    )
    resposta = cliente.post("/mcp", json=corpo, headers=headers)
    return resposta.status_code, resposta.json()["result"]


def consultar_na_aplicacao(
    cliente: TestClient, sala: str, inicio: str, fim: str
) -> dict:
    corpo, headers = request(
        "tools/call",
        {
            "name": "consultar_disponibilidade",
            "arguments": {"sala": sala, "inicio": inicio, "fim": fim},
        },
        nome="consultar_disponibilidade",
    )
    resposta = cliente.post("/mcp", json=corpo, headers=headers)
    return resposta.json()["result"]


def test_reserva_livre_gera_id_e_fica_visivel_na_mesma_instancia() -> None:
    inicio = "2026-11-03T09:00:00-03:00"
    fim = "2026-11-03T10:00:00-03:00"

    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        status, resultado = reservar(cliente, "sala-aquario", inicio, fim)
        disponibilidade = consultar_na_aplicacao(
            cliente, "sala-aquario", inicio, fim
        )

    assert status == 200
    assert resultado["resultType"] == "complete"
    assert resultado["structuredContent"] == {
        "reserva": "res-0003",
        "reservado": True,
        "sala": "sala-aquario",
        "inicio": inicio,
        "fim": fim,
        "responsavel": "Doc",
        "politica": "2026-11-01",
        "motivo": None,
    }
    assert json.loads(resultado["content"][0]["text"]) == resultado["structuredContent"]
    assert disponibilidade["structuredContent"]["livre"] is False
    assert disponibilidade["structuredContent"]["conflitos"][0]["id"] == "res-0003"


def test_reserva_sem_alternativas_devolve_erro_de_execucao() -> None:
    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        reservar(
            cliente,
            "sala-mirante",
            "2026-11-03T11:00:00-03:00",
            "2026-11-03T12:00:00-03:00",
        )
        _, resultado = reservar(
            cliente,
            "sala-mirante",
            "2026-11-03T11:00:00-03:00",
            "2026-11-03T12:00:00-03:00",
        )

    assert resultado["isError"] is True
    assert "Sem alternativas disponiveis no intervalo" in resultado["content"][0]["text"]


def reservar_raw(
    cliente: TestClient,
    sala: str = "sala-garagem",
    inicio: str = "2026-11-03T14:00:00-03:00",
    fim: str = "2026-11-03T15:00:00-03:00",
    responsavel: str = "Marty",
    **kwargs,
) -> tuple[int, dict]:
    corpo, headers = request(
        "tools/call",
        {
            "name": "reservar_sala",
            "arguments": {
                "sala": sala,
                "inicio": inicio,
                "fim": fim,
                "responsavel": responsavel,
            },
        },
        nome="reservar_sala",
        **kwargs,
    )
    resposta = cliente.post("/mcp", json=corpo, headers=headers)
    return resposta.status_code, resposta.json()


def retomar_raw(
    cliente: TestClient,
    chave: str,
    estado: str,
    resposta_input: dict,
    *,
    sala: str = "sala-garagem",
    inicio: str = "2026-11-03T14:00:00-03:00",
    fim: str = "2026-11-03T15:00:00-03:00",
    responsavel: str = "Marty",
) -> tuple[int, dict]:
    corpo, headers = request(
        "tools/call",
        {
            "name": "reservar_sala",
            "arguments": {
                "sala": sala,
                "inicio": inicio,
                "fim": fim,
                "responsavel": responsavel,
            },
            "inputResponses": {chave: resposta_input},
            "requestState": estado,
        },
        nome="reservar_sala",
    )
    resposta = cliente.post("/mcp", json=corpo, headers=headers)
    return resposta.status_code, resposta.json()


def test_conflito_devolve_input_required_com_alternativas_ordenadas() -> None:
    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        status, resposta = reservar_raw(cliente)

    resultado = resposta["result"]
    chave = next(iter(resultado["inputRequests"]))
    pedido = resultado["inputRequests"][chave]
    schema_sala = pedido["params"]["requestedSchema"]["properties"]["sala"]
    assert status == 200
    assert resultado["resultType"] == "input_required"
    assert pedido["method"] == "elicitation/create"
    assert pedido["params"]["mode"] == "form"
    assert schema_sala["enum"] == ["sala-fusca", "sala-mirante"]
    assert resultado["requestState"]


def test_conflito_sem_capability_de_form_devolve_32021() -> None:
    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        status, resposta = reservar_raw(cliente, capabilities={})

    assert status == 400
    assert resposta["error"]["code"] == -32021
    assert "requiredCapabilities" in resposta["error"]["data"]


def test_retry_aceito_conclui_na_sala_escolhida_apos_reinstancia() -> None:
    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        _, pausa = reservar_raw(cliente)
    resultado = pausa["result"]
    chave = next(iter(resultado["inputRequests"]))
    estado = resultado["requestState"]

    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        status, resposta = retomar_raw(
            cliente,
            chave,
            estado,
            {"action": "accept", "content": {"sala": "sala-fusca"}},
        )

    assert status == 200
    assert resposta["result"]["structuredContent"]["sala"] == "sala-fusca"
    assert resposta["result"]["structuredContent"]["responsavel"] == "Marty"


def test_retry_recusado_conclui_sem_reservar() -> None:
    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        _, pausa = reservar_raw(cliente)
        resultado = pausa["result"]
        chave = next(iter(resultado["inputRequests"]))
        _, resposta = retomar_raw(
            cliente, chave, resultado["requestState"], {"action": "decline"}
        )

    assert resposta["result"]["resultType"] == "complete"
    assert resposta["result"]["isError"] is False
    assert resposta["result"]["structuredContent"] == {
        "reserva": None,
        "reservado": False,
        "sala": None,
        "inicio": None,
        "fim": None,
        "responsavel": None,
        "politica": None,
        "motivo": "recusado",
    }


def test_retry_nao_permite_argumentos_adulterados() -> None:
    with TestClient(criar_aplicacao(), base_url="http://127.0.0.1:7301") as cliente:
        _, pausa = reservar_raw(cliente)
        resultado = pausa["result"]
        chave = next(iter(resultado["inputRequests"]))
        status, resposta = retomar_raw(
            cliente,
            chave,
            resultado["requestState"],
            {"action": "accept", "content": {"sala": "sala-fusca"}},
            sala="sala-mirante",
            inicio="2026-11-03T13:00:00-03:00",
            fim="2026-11-03T14:00:00-03:00",
            responsavel="Biff",
        )

    assert status == 400
    assert resposta["error"]["code"] == -32602
