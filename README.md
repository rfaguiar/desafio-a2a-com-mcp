# A Ponte

Servidor MCP stateless para o dominio de salas e agente que o consome como
host MCP, expondo a capacidade ao mundo por A2A v1.0 sobre JSON-RPC 2.0.

## Como rodar

### Pre-requisitos

- Python 3.10 ou superior;
- `uv 0.13.9` ou superior.

Para instalar a versao fixada do gerenciador em um ambiente Python:

```bash
python -m pip install uv==0.13.9
```

A partir da raiz de um clone limpo, instale exatamente o lock:

```bash
python -m uv sync --frozen --extra dev
```

Gere uma chave e exporte-a somente no ambiente. Nao salve o resultado em um
arquivo versionado:

```bash
export REQUEST_STATE_SECRET="$(python3 -c "import secrets; print(secrets.token_hex(32))")"
```

PowerShell:

```powershell
$env:REQUEST_STATE_SECRET = python -c "import secrets; print(secrets.token_hex(32))"
```

Em um terminal, suba o servidor MCP na porta `7301`:

```bash
python -m uv run --frozen ponte-mcp
```

Em outro terminal, suba o agente A2A na porta `7300`:

```bash
python -m uv run --frozen ponte-agente
```

O card fica em
`http://127.0.0.1:7300/.well-known/agent-card.json`, o endpoint A2A em
`/a2a` e o endpoint MCP em
`http://127.0.0.1:7301/mcp`.

Com os dois processos recem-iniciados, execute:

```bash
python -m uv run --frozen --extra dev pytest
python validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301
```

Smoke do card:

```bash
curl http://127.0.0.1:7300/.well-known/agent-card.json
```

## Onde a ponte acontece

A traducao do `input_required` para uma Task
`TASK_STATE_INPUT_REQUIRED` acontece em
`_aplicar_resultado_mcp` em
[`agente/main.py`](agente/main.py). Nela, o agente extrai a ordem das
alternativas, guarda o token opaco e a chamada MCP no `EstadoPrivadoTask`.
Na continuacao, o mesmo arquivo chama `ClienteMcp.chamar_tool` com
`inputResponses`, o `requestState` inalterado e a trace original. O token nunca
e aberto nem incluido na representacao publica da Task.

## Decisoes tecnicas

- O SDK oficial `mcp==2.3.0` fornece o Streamable HTTP stateless, a
  classificacao de erros, os tipos MRTR e `RequestStateBoundary`.
- [`servidor-mcp/estado.py`](servidor-mcp/estado.py) cria
  `RequestStateSecurity` com AES-256-GCM, TTL de 15 minutos e chave fornecida
  exclusivamente por `REQUEST_STATE_SECRET`. Uma chave menor que 32 bytes
  impede a inicializacao.
- O estado do pedido viaja no `requestState` protegido. O servidor MCP nao
  usa cache ou mapa entre a pausa e o retry; as reservas criadas ficam apenas
  em memoria no processo.
- As Tasks e seu estado privado ficam no processo do agente, em
  [`agente/tarefas.py`](agente/tarefas.py), indexadas pelo `taskId`. O cliente
  ve somente `Task.como_publica`; ao terminalizar, o estado privado MRTR e
  descartado.
- O agente descobre tools e le `politica://uso` em runtime por
  [`agente/mcp_client.py`](agente/mcp_client.py). Ele nao importa o codigo do
  dominio MCP e nao implementa regra de negocio de salas.
- Cada retry recebe um id JSON-RPC monotonicamente novo. O `traceparent`
  inicial e preservado por Task nas continuacoes.
- Nao ha LLM, banco, autenticacao, streaming, persistencia de reservas ou
  dependencia de provedor de modelo.

## Saida do validador

```text
trace-id desta execucao: 7a67671bc1d2740889349328e150d218
procure esse valor no stderr do servidor MCP para conferir a propagacao do traceparent.

PASS 01 tools/list traz as tres tools
PASS 02 toda tool tem inputSchema de objeto
PASS 03 listar_salas devolve structuredContent e o mesmo JSON em texto
PASS 04 _meta sem protocolVersion devolve -32602 e HTTP 400
PASS 05 _meta sem clientCapabilities devolve -32602 e HTTP 400
PASS 06 tool inexistente e recusada, por -32602 ou por isError
PASS 07 resources/read de politica://uso devolve a politica
PASS 08 resources/read de URI inexistente devolve -32602
PASS 09 sala inexistente devolve isError com a mensagem exata
PASS 10 fora da janela devolve isError com a mensagem exata
PASS 11 duracao acima de 2h devolve isError com a mensagem exata
PASS 12 intervalo invertido devolve isError com a mensagem exata
PASS 13 conflito devolve input_required com inputRequests e requestState
PASS 14 a elicitation e form mode e oferece as alternativas na ordem certa
PASS 15 conflito sem a capability elicitation devolve -32021 e HTTP 400
PASS 16 retry com inputResponses e requestState conclui a reserva
PASS 17 requestState adulterado e rejeitado com -32602
PASS 18 argumentos adulterados no retry nao tomam efeito
PASS 19 recusa conclui sem reservar e sem isError
PASS 20 conflito sem alternativa possivel devolve isError com a mensagem exata

PASS 21 agent card responde 200 no well-known com JSON
PASS 22 o card declara a interface JSON-RPC com url e versao 1.0
PASS 23 o card declara a skill reservar-sala
PASS 24 SendMessage com sala livre conclui a Task
PASS 25 o artifact chama reserva e traz a versao da politica
PASS 26 GetTask devolve id, contextId e estado corrente
PASS 27 SendMessage com sala ocupada pausa a Task
PASS 28 a Task pausada lista as alternativas na ordem certa
PASS 29 escolha fora do enum mantem a Task pausada
PASS 30 a continuacao conclui a Task na sala escolhida
PASS 31 SendMessage em Task terminal e recusado
PASS 32 a recusa termina a Task em CANCELED
PASS 33 duas Tasks pausadas ao mesmo tempo concluem cada uma com a sua reserva
PASS 34 nenhuma resposta A2A carrega o requestState
PASS 35 sala inexistente termina a Task em FAILED com a mensagem da tool
PASS 36 o agente e deterministico: o mesmo pedido produz a mesma pausa

resumo: 36 passaram, 0 falharam, de 36 verificacoes
```
