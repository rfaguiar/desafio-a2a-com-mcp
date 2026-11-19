import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agente.mcp_client import ClienteMcp


class _McpHandler(BaseHTTPRequestHandler):
    chamados: list[dict] = []
    sequencia = 0

    def do_POST(self) -> None:
        tamanho = int(self.headers["Content-Length"])
        corpo = json.loads(self.rfile.read(tamanho))
        self.__class__.chamados.append(
            {
                "corpo": corpo,
                "headers": dict(self.headers),
            }
        )
        metodo = corpo["method"]
        if metodo == "tools/list":
            resultado = {
                "tools": [
                    {
                        "name": "reservar_sala",
                        "inputSchema": {"type": "object"},
                    }
                ]
            }
        elif metodo == "resources/read":
            resultado = {
                "contents": [
                    {
                        "uri": "politica://uso",
                        "mimeType": "text/markdown",
                        "text": "versao: 2026-11-01\n\npolitica",
                    }
                ]
            }
        elif self.__class__.sequencia == 0:
            self.__class__.sequencia += 1
            resultado = {
                "resultType": "input_required",
                "inputRequests": {},
                "requestState": "estado-opaco",
            }
        else:
            resultado = {
                "resultType": "complete",
                "structuredContent": {"reservado": True},
            }
        resposta = json.dumps(
            {"jsonrpc": "2.0", "id": corpo["id"], "result": resultado}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resposta)))
        self.end_headers()
        self.wfile.write(resposta)

    def log_message(self, *_args) -> None:
        pass


def test_cliente_descobre_le_resource_e_reenvia_request_com_id_novo() -> None:
    _McpHandler.chamados = []
    _McpHandler.sequencia = 0
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), _McpHandler)
    thread = threading.Thread(target=servidor.serve_forever)
    thread.start()
    trace = "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
    try:
        cliente = ClienteMcp(
            f"http://127.0.0.1:{servidor.server_port}/mcp"
        )
        argumentos = {
            "sala": "sala-garagem",
            "inicio": "2026-11-03T14:00:00-03:00",
            "fim": "2026-11-03T15:00:00-03:00",
            "responsavel": "Marty",
        }
        pausa = cliente.chamar_tool(
            "reservar_sala",
            argumentos,
            traceparent=trace,
        )
        completo = cliente.chamar_tool(
            "reservar_sala",
            argumentos,
            input_responses={
                "escolha": {
                    "action": "accept",
                    "content": {"sala": "sala-fusca"},
                }
            },
            request_state=pausa["requestState"],
            traceparent=trace,
        )
    finally:
        servidor.shutdown()
        thread.join()
        servidor.server_close()

    assert completo["resultType"] == "complete"
    assert cliente.versao_politica == "2026-11-01"
    assert [c["corpo"]["method"] for c in _McpHandler.chamados] == [
        "tools/list",
        "resources/read",
        "tools/call",
        "tools/call",
    ]
    chamadas = _McpHandler.chamados[2:]
    assert chamadas[1]["corpo"]["id"] != chamadas[0]["corpo"]["id"]
    assert all(
        chamada["corpo"]["params"]["_meta"][
            "io.modelcontextprotocol/clientCapabilities"
        ]
        == {"elicitation": {"form": {}}}
        for chamada in chamadas
    )
    assert all(
        chamada["corpo"]["params"]["_meta"]["traceparent"] == trace
        for chamada in chamadas
    )
    assert chamadas[0]["headers"]["Mcp-Name"] == "reservar_sala"
    assert chamadas[1]["headers"]["Mcp-Name"] == "reservar_sala"
