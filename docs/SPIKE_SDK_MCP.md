# Spike do SDK MCP

## Versoes verificadas

- `mcp==2.3.0`;
- Python 3.10 ou superior;
- tipos wire de `mcp-types==2.3.0`, alinhados a `2026-07-28`.

## API escolhida

O processo MCP usara `mcp.server.MCPServer` para registrar tools com
`MCPServer.tool()` e resources com `MCPServer.resource()`.

O transporte escolhido e o Streamable HTTP nativo do SDK:

```python
server.run(
    transport="streamable-http",
    host="127.0.0.1",
    port=7301,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)
```

Tambem e possivel obter a aplicacao ASGI com
`MCPServer.streamable_http_app()`, sem criar uma implementacao de protocolo
paralela.

## MRTR e estado protegido

No wire `2026-07-28`, a interrupcao e representada por
`mcp_types.InputRequiredResult`, com `result_type="input_required"`,
`input_requests` e `request_state`.

No retry, uma tool recebe as respostas e o estado pelas propriedades
`Context.input_responses` e `Context.request_state`. O SDK aplica
`RequestStateBoundary` automaticamente. A politica de protecao selecionada
sera `mcp.server.mcpserver.RequestStateSecurity`, com uma chave compartilhada
fornecida pelo ambiente; essa classe fornece AES-GCM, validacao de expiracao,
binding do request e deteccao de adulteracao.

## Smoke do pacote instalado

Os imports abaixo foram executados no ambiente criado a partir do lock:

```python
from mcp_types import InputRequiredResult
from mcp.server import MCPServer
from mcp.server.mcpserver import RequestStateSecurity
```

Uma instancia de `MCPServer` tambem expos `streamable_http_app()` conforme
esperado.
