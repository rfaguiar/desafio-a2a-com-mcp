import json

from starlette.testclient import TestClient

from agente.main import criar_aplicacao


class ClienteMcpFalso:
    versao_politica = "2026-11-01"

    def __init__(self, *, resultado=None, resultados=None) -> None:
        self.resultado = resultado or {
            "resultType": "complete",
            "structuredContent": {
                "reserva": "res-0003",
                "reservado": True,
                "sala": "sala-porao",
                "inicio": "2026-11-03T09:00:00-03:00",
                "fim": "2026-11-03T10:00:00-03:00",
                "responsavel": "Doc",
                "politica": "2026-11-01",
                "motivo": None,
            },
        }
        self.resultados = list(resultados) if resultados is not None else None
        self.chamadas = []

    def chamar_tool(
        self,
        nome: str,
        argumentos: dict,
        *,
        input_responses=None,
        request_state=None,
        traceparent=None,
    ) -> dict:
        self.chamadas.append(
            {
                "nome": nome,
                "argumentos": argumentos,
                "traceparent": traceparent,
                "requestState": request_state,
                "inputResponses": input_responses,
            }
        )
        if self.resultados is not None:
            return self.resultados.pop(0)
        return self.resultado


def enviar(
    cliente: TestClient,
    texto: str,
    *,
    task_id: str | None = None,
    traceparent: str | None = None,
) -> dict:
    mensagem = {
        "messageId": "msg-user",
        "role": "ROLE_USER",
        "parts": [{"text": texto}],
    }
    if task_id is not None:
        mensagem["taskId"] = task_id
    headers = {"Content-Type": "application/json"}
    if traceparent is not None:
        headers["traceparent"] = traceparent
    resposta = cliente.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "SendMessage",
            "params": {"message": mensagem},
        },
        headers=headers,
    )
    return resposta.json()


def test_agent_card_publica_interface_jsonrpc_e_skill() -> None:
    with TestClient(criar_aplicacao(ClienteMcpFalso())) as cliente:
        resposta = cliente.get("/.well-known/agent-card.json")

    assert resposta.status_code == 200
    card = resposta.json()
    assert card["supportedInterfaces"] == [
        {
            "url": "http://127.0.0.1:7300/a2a",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ]
    assert card["skills"][0]["id"] == "reservar-sala"
    assert card["capabilities"]["streaming"] is False


def test_send_message_conclui_com_artifact_e_propagacao_de_trace() -> None:
    mcp = ClienteMcpFalso()
    trace = "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
    with TestClient(criar_aplicacao(mcp), base_url="http://127.0.0.1:7300") as cliente:
        resposta = enviar(
            cliente,
            (
                "reservar sala=sala-porao inicio=2026-11-03T09:00:00-03:00 "
                "fim=2026-11-03T10:00:00-03:00 responsavel=Doc"
            ),
            traceparent=trace,
        )

    tarefa = resposta["result"]["task"]
    assert tarefa["status"]["state"] == "TASK_STATE_COMPLETED"
    assert tarefa["artifacts"][0]["name"] == "reserva"
    assert json.loads(tarefa["artifacts"][0]["parts"][0]["text"]) == {
        "reserva": "res-0003",
        "sala": "sala-porao",
        "inicio": "2026-11-03T09:00:00-03:00",
        "fim": "2026-11-03T10:00:00-03:00",
        "responsavel": "Doc",
        "politica": "2026-11-01",
    }
    assert mcp.chamadas[0]["traceparent"] == trace
    assert "requestState" not in json.dumps(resposta)


def test_get_task_devolve_estado_atual_e_terminal_rejeita_continuacao() -> None:
    with TestClient(criar_aplicacao(ClienteMcpFalso())) as cliente:
        primeira = enviar(
            cliente,
            (
                "reservar sala=sala-porao inicio=2026-11-03T09:00:00-03:00 "
                "fim=2026-11-03T10:00:00-03:00 responsavel=Doc"
            ),
        )
        task_id = primeira["result"]["task"]["id"]
        obtida = cliente.post(
            "/a2a",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "GetTask",
                "params": {"id": task_id},
            },
        ).json()
        terminal = enviar(cliente, "escolha=sala-porao", task_id=task_id)

    assert obtida["result"]["task"]["id"] == task_id
    assert obtida["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
    assert terminal["error"]["code"] == -32602


def test_resultado_is_error_da_tool_falha_a_task() -> None:
    mcp = ClienteMcpFalso(
        resultado={
            "resultType": "complete",
            "isError": True,
            "content": [{"type": "text", "text": "Sala inexistente: sala-delorean"}],
        }
    )
    with TestClient(criar_aplicacao(mcp)) as cliente:
        resposta = enviar(
            cliente,
            (
                "reservar sala=sala-delorean inicio=2026-11-03T09:00:00-03:00 "
                "fim=2026-11-03T10:00:00-03:00 responsavel=Doc"
            ),
        )

    tarefa = resposta["result"]["task"]
    assert tarefa["status"]["state"] == "TASK_STATE_FAILED"
    assert "Sala inexistente: sala-delorean" in tarefa["status"]["message"][
        "parts"
    ][0]["text"]


def pausa(estado: str, alternativas: list[str]) -> dict:
    return {
        "resultType": "input_required",
        "inputRequests": {
            "escolha_de_sala": {
                "method": "elicitation/create",
                "params": {
                    "mode": "form",
                    "requestedSchema": {
                        "type": "object",
                        "properties": {
                            "sala": {
                                "type": "string",
                                "enum": alternativas,
                            }
                        },
                        "required": ["sala"],
                    },
                },
            }
        },
        "requestState": estado,
    }


def completo(sala: str, reserva: str = "res-0004") -> dict:
    return {
        "resultType": "complete",
        "structuredContent": {
            "reserva": reserva,
            "reservado": True,
            "sala": sala,
            "inicio": "2026-11-03T14:00:00-03:00",
            "fim": "2026-11-03T15:00:00-03:00",
            "responsavel": "Marty",
            "politica": "2026-11-01",
            "motivo": None,
        },
    }


def test_pausa_escolha_invalida_e_retry_preservam_estado_da_task() -> None:
    mcp = ClienteMcpFalso(
        resultados=[
            pausa("estado-opaco-a", ["sala-fusca", "sala-mirante"]),
            completo("sala-fusca"),
        ]
    )
    trace = "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
    pedido = (
        "reservar sala=sala-garagem inicio=2026-11-03T14:00:00-03:00 "
        "fim=2026-11-03T15:00:00-03:00 responsavel=Marty"
    )
    with TestClient(criar_aplicacao(mcp)) as cliente:
        inicial = enviar(cliente, pedido, traceparent=trace)
        task_id = inicial["result"]["task"]["id"]
        invalida = enviar(cliente, "escolha=sala-aquario", task_id=task_id)
        aceita = enviar(
            cliente,
            "escolha=sala-fusca",
            task_id=task_id,
            traceparent="00-outro-outro-01",
        )

    assert inicial["result"]["task"]["status"]["message"]["parts"][0]["text"] == (
        "alternativas: sala-fusca, sala-mirante"
    )
    assert invalida["result"]["task"]["status"]["state"] == (
        "TASK_STATE_INPUT_REQUIRED"
    )
    assert aceita["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
    assert mcp.chamadas[1]["argumentos"] == mcp.chamadas[0]["argumentos"]
    assert mcp.chamadas[1]["traceparent"] == trace
    assert mcp.chamadas[1]["requestState"] == "estado-opaco-a"
    assert mcp.chamadas[1]["inputResponses"] == {
        "escolha_de_sala": {
            "action": "accept",
            "content": {"sala": "sala-fusca"},
        }
    }
    assert "estado-opaco-a" not in json.dumps(aceita)


def test_recusa_termina_a_task_como_cancelada() -> None:
    mcp = ClienteMcpFalso(
        resultados=[
            pausa("estado-opaco-recusa", ["sala-mirante"]),
            {
                "resultType": "complete",
                "structuredContent": {
                    "reserva": None,
                    "reservado": False,
                    "sala": None,
                    "inicio": None,
                    "fim": None,
                    "responsavel": None,
                    "politica": None,
                    "motivo": "recusado",
                },
            },
        ]
    )
    with TestClient(criar_aplicacao(mcp)) as cliente:
        inicial = enviar(
            cliente,
            (
                "reservar sala=sala-garagem inicio=2026-11-03T14:00:00-03:00 "
                "fim=2026-11-03T15:00:00-03:00 responsavel=Marty"
            ),
        )
        task_id = inicial["result"]["task"]["id"]
        recusada = enviar(cliente, "escolha=recusar", task_id=task_id)

    assert (
        recusada["result"]["task"]["status"]["state"] == "TASK_STATE_CANCELED"
    )
    assert mcp.chamadas[1]["inputResponses"] == {
        "escolha_de_sala": {"action": "decline"}
    }


def test_duas_tasks_pausadas_nao_trocam_estado() -> None:
    mcp = ClienteMcpFalso(
        resultados=[
            pausa("estado-a", ["sala-fusca", "sala-mirante"]),
            pausa("estado-b", ["sala-mirante"]),
            completo("sala-fusca", "res-0003"),
            completo("sala-mirante", "res-0004"),
        ]
    )
    with TestClient(criar_aplicacao(mcp)) as cliente:
        a = enviar(
            cliente,
            (
                "reservar sala=sala-garagem inicio=2026-11-03T14:00:00-03:00 "
                "fim=2026-11-03T15:00:00-03:00 responsavel=A"
            ),
        )
        b = enviar(
            cliente,
            (
                "reservar sala=sala-fusca inicio=2026-11-03T16:00:00-03:00 "
                "fim=2026-11-03T17:00:00-03:00 responsavel=B"
            ),
        )
        task_a = a["result"]["task"]["id"]
        task_b = b["result"]["task"]["id"]
        enviar(cliente, "escolha=sala-fusca", task_id=task_a)
        enviar(cliente, "escolha=sala-mirante", task_id=task_b)

    assert mcp.chamadas[2]["requestState"] == "estado-a"
    assert mcp.chamadas[3]["requestState"] == "estado-b"
    assert mcp.chamadas[2]["argumentos"]["responsavel"] == "A"
    assert mcp.chamadas[3]["argumentos"]["responsavel"] == "B"
