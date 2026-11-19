# Plano de implementacao do projeto A Ponte

## 1. Objetivo e regra de execucao

Entregar dois processos independentes e verificaveis:

1. um servidor MCP em Streamable HTTP na porta `7301`;
2. um agente que atua como host MCP e servidor A2A na porta `7300`.

O estado interrompido sera costurado sem sessao de protocolo: o servidor MCP
devolvera `requestState` protegido por integridade e o agente o associara a uma
Task A2A pausada. O cliente A2A retomara essa Task e o agente emitira um novo
`tools/call`, com novo id JSON-RPC, ecoando o estado opaco.

Cada etapa abaixo termina em um commit pequeno, testado e executavel. Nao se deve
acumular uma implementacao intermediaria quebrada para corrigir em um commit
posterior. O validador completo sera um gate de entrega; smoke tests e testes
automatizados especificos serao os gates intermediarios.

As skills de desenvolvimento instaladas orientarao a execucao sem alterar os
requisitos do desafio:

- `tdd`: cada fatia comecara por um teste comportamental em um seam publico;
- `implement`: a implementacao sera a menor que satisfaz esse comportamento;
- `systematic-debugging`: falhas serao reproduzidas e rastreadas por fronteira
  antes de alterar codigo;
- `code-review`: cada etapa sera revisada nos eixos `padroes` e `especificacao`;
- `git-workflow-and-versioning`: cada incremento testado vira um commit
  atomico, reversivel e com historico legivel.

`improve-codebase-architecture` sera consultada apenas quando uma mudanca
introduzir ou mover fronteira entre modulos. Ela nao justifica abstracoes,
servicos, repositorios ou camadas nao exigidos pelo README.

## 2. Decisoes tecnicas

### 2.1 Stack

- Python 3.10 ou superior, que e o requisito minimo declarado pelo desafio.
- SDK oficial `mcp`, na v2 e alinhado a `2026-07-28`.
- Servidor HTTP ASGI ja utilizado ou recomendado pelo SDK MCP; nao introduzir
  outro framework HTTP sem necessidade.
- Binding A2A JSON-RPC 2.0 implementado diretamente, seguindo os contratos em
  `exemplos/wire/`, porque o foco e a forma wire A2A v1.0.
- `pyproject.toml` com todas as dependencias e ferramentas de runtime
  exatamente versionadas; o lock de dependencias sera versionado.
- Nenhum LLM, banco, ORM, container ou dependencia de provedor de modelo.
- Transporte sem sessao: nenhum estado de protocolo sera deduzido da conexao
  HTTP, do SDK ou de um request anterior.

Antes de adotar uma API do SDK, a implementacao fara um spike minimo para
confirmar os nomes vigentes para `input_required`, `resources/read`, estado
protegido e transporte Streamable HTTP. A versao exata descoberta no spike sera
travada no mesmo commit. O plano nao contorna limitacoes do SDK reescrevendo o
protocolo; uma limitacao real sera documentada com evidencias no README final.

### 2.2 Organizacao proposta

```text
.
├── pyproject.toml
├── uv.lock                   # ou lock equivalente escolhido na etapa 1
├── servidor-mcp/
│   ├── __init__.py
│   ├── main.py               # composicao do processo e transporte HTTP
│   ├── dominio.py            # salas, politica, conflitos e reserva
│   ├── estado.py             # selo/verificacao de requestState
│   └── testes/
├── agente/
│   ├── __init__.py
│   ├── main.py               # card, /a2a e composicao do processo
│   ├── mcp_client.py         # descoberta e requests MCP crus
│   ├── tarefas.py            # maquina de estados e estado por Task
│   ├── mensagens.py          # parsing deterministico dos dois formatos
│   └── testes/
└── docs/
    └── PLANO_IMPLEMENTACAO.md
```

Os nomes podem ser ajustados ao estilo exigido pelo SDK. Modulos somente serao
criados quando concentrarem uma responsabilidade real e forem usados diretamente
pelos processos. Arquivos de protocolo auxiliares, scripts de diagnostico e
abstracoes genericas nao serao criados antecipadamente.

### 2.3 Invariantes arquiteturais

- `dados/`, `validador/` e `exemplos/` sao somente leitura.
- O agente so acessa o dominio por HTTP, nunca importa `servidor-mcp`.
- O servidor MCP e a unica autoridade para validar politica, conflitos e
  alternativas.
- O agente nao abre, decodifica, interpreta nem reconstitui `requestState`.
- Todo request MCP valida seu proprio `_meta`; nada e inferido de request ou
  conexao anterior.
- A reserva e mutavel somente em memoria no processo MCP.
- O `requestState` contem o pedido suficiente para retomar e nao depende de
  estado de memoria do servidor MCP.
- As Tasks vivem no processo do agente, indexadas pelo `taskId`.
- O estado terminal de uma Task e imutavel.
- Nao implementar autenticacao, streaming, SSE, push notification, OpenTelemetry
  completo, persistencia de reservas, interface grafica ou qualquer outro item
  fora do escopo.

### 2.4 Seams publicos aceitos para TDD

O README, o validador e `exemplos/wire/` ja pre-acordam as fronteiras publicas.
Portanto, os testes nao dependem de pergunta adicional ao usuario em cada ciclo:

1. **Wire MCP**: resposta HTTP/JSON-RPC para um request real, incluindo status,
   `content`, `structuredContent`, `resultType` e erro.
2. **Wire A2A**: card HTTP e respostas JSON-RPC de `SendMessage` e `GetTask`,
   incluindo historico, estado e artifact.
3. **Estado protegido**: comportamento observavel por retry MCP, incluindo
   validade apos restart, adulteracao e uso dos dados selados.
4. **Comportamento de dominio**: funcoes publicas pequenas, somente quando forem
   a interface adotada pelo servidor; nunca metodos privados ou chamadas
   internas entre helpers.
5. **Diagnostico de processo**: stderr capturado para validar metodo, id,
   `traceparent` e ordem dos requests.

Cada teste usa um literal do README, do wire ou de uma expectativa independente;
nao reproduz o mesmo algoritmo da implementacao para calcular o esperado.

## 3. Contratos que norteiam a implementacao

### 3.1 MCP

- Versao: `2026-07-28`.
- Endpoint: `POST /mcp`, porta padrao `7301`.
- `_meta` obrigatorio por request:
  - `io.modelcontextprotocol/protocolVersion`;
  - `io.modelcontextprotocol/clientCapabilities`;
  - opcionalmente `traceparent`.
- Capabilities do cliente do agente:
  `{"elicitation":{"form":{}}}`.
- Headers espelhando o corpo:
  - `MCP-Protocol-Version`;
  - `Mcp-Method`;
  - `Mcp-Name` apenas em `tools/call` e `resources/read`.
- Methods iniciais: `tools/list`, `tools/call` e `resources/read`.
- Resultados normais possuem `resultType: "complete"`.
- Toda tool devolve `content` textual e `structuredContent`.
- URI do resource: `politica://uso`, com MIME `text/markdown`.

### 3.2 A2A

- Card em `GET /.well-known/agent-card.json`, usando `supportedInterfaces`,
  `protocolBinding: "JSONRPC"` e `protocolVersion: "1.0"`.
- Endpoint `POST /a2a` na porta padrao `7300`.
- Methods: `SendMessage` e `GetTask`.
- Pedido inicial exatamente no formato:
  `reservar sala=<id> inicio=<iso8601> fim=<iso8601> responsavel=<nome>`.
- Continuacao:
  `escolha=<id>` ou `escolha=recusar`.
- Pausa com texto exato:
  `alternativas: <id>, <id>`.
- Estados wire possiveis na ordem praticada:
  `TASK_STATE_SUBMITTED` -> `TASK_STATE_WORKING` ->
  `TASK_STATE_COMPLETED`, `TASK_STATE_CANCELED`, `TASK_STATE_FAILED` ou
  `TASK_STATE_INPUT_REQUIRED`.
- `TASK_STATE_INPUT_REQUIRED` nao e terminal; seu estado privado preserva:
  - o envelope original da chamada MCP;
  - a chave de `inputRequests`;
  - as alternativas em ordem;
  - o `requestState` opaco;
  - o trace context da Task.

### 3.3 Dominio

- Carregar somente `dados/salas.json`, `dados/reservas.json` e
  `dados/politica-de-uso.md`.
- Considerar sobreposicao como
  `inicio_existente < fim_novo && fim_existente > inicio_novo`.
- Aplicar a regra de janela a cada lado do intervalo e a duracao maxima de duas
  horas.
- Alternativas: salas livres, com capacidade maior ou igual a sala pedida,
  ordenadas por capacidade crescente e id alfabetico no empate, limitadas a
  tres.
- ID novo de reserva: sequencial e deterministico dentro do processo
  (`res-0003`, `res-0004`, ...).
- Comparar instantes ISO 8601 preservando os valores textuais selados no
  resultado. Nao depender da data atual.

As mensagens de execucao abaixo sao literais de contrato e devem ser
centralizadas no ponto que produz erros da tool, sem traducao ou variacao:

- `Sala inexistente: <id informado>`;
- `Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00`;
- `Duracao acima do limite: a politica permite no maximo 2 horas`;
- `Intervalo invalido: fim deve ser posterior a inicio`;
- `Sem alternativas disponiveis no intervalo`.

## 4. Plano incremental por commits

Cada commit deve conter uma unica fatia de comportamento, usar Conventional
Commits e seguir:

1. escolher um seam e escrever um teste que falhe pelo comportamento esperado;
2. executar e registrar a falha relevante;
3. implementar somente o necessario para a fatia;
4. executar o teste focal, os testes afetados e a verificacao de tipos/lint
   configurada;
5. revisar o diff nos dois eixos — padroes e especificacao — e remover scope
   creep;
6. inspecionar o staged diff, procurar segredos e verificar que arquivos
   protegidos nao entraram;
7. executar o gate da etapa;
8. criar o commit; se a etapa revelar um bug, investigar a causa raiz antes da
   proxima tentativa.

Um commit intermediario pode ainda nao satisfazer o desafio completo, mas deve
estar reproduzivel, testado e sem deixar endpoint, arquivo ou teste quebrado pelo
seu proprio escopo. `main` so recebe comportamento demonstrado; correcoes de uma
etapa nao sao empurradas para um commit posterior.

### Commit 1 — `chore: preparar ambiente Python e testes`

**Implementar**

- Criar `pyproject.toml` com metadata minima, Python 3.10+, scripts de entrada,
  SDK MCP oficial e ferramentas de teste com versoes exatas.
- Gerar e versionar o lock.
- Configurar `pytest` e variaveis padrao dos processos.
- Adicionar testes vazios/smoke de importacao sem alterar arquivos protegidos.
- Confirmar por spike que o SDK selecionado oferece Streamable HTTP, MRTR
  `input_required` e resource.

**Gate**

- Instalar a partir do lock sem resolver versoes de modo livre.
- `pytest` passa.
- Os dois pontos de entrada carregam o mesmo ambiente sem conflito.
- O spike registra versao, endpoints e API escolhida no proprio diff, sem
  implementar protocolo paralelo.

**Estado da branch**

Base limpa e reproduzivel, ainda sem alterar comportamento externo.

### Commit 2 — `feat: adicionar carregamento e validacao do dominio`

**Implementar**

- Modelos pequenos para sala, reserva e politica.
- Leitura de dados a partir da raiz do repositorio, independente do diretorio
  corrente.
- Funcoes puras para validar sala, intervalo, janela e duracao.
- Funcao de conflito e ordenacao de alternativas.
- Testes unitarios para limites de 08:00/20:00, duas horas, intervalo invertido
  ou vazio, sobreposicao por borda, empate de capacidade e limite de tres.

**Gate**

- Testes cobrem as quatro mensagens exatas de erro.
- Nenhum teste altera os JSON ou a politica originais.

**Estado da branch**

Dominio deterministico e validado, sem processo HTTP ainda exposto.

### Commit 3 — `feat: subir MCP com descoberta e listar salas`

**Implementar**

- Processo `servidor-mcp` na porta `7301`, endpoint `/mcp`.
- Registro de `tools` e `resources` nas capabilities.
- Tool `listar_salas` com `inputSchema` objeto, `outputSchema`,
  `structuredContent` e JSON identico no bloco `text`.
- Registro de apenas `listar_salas` nessa primeira fatia; tools posteriores serao
  adicionadas quando seus comportamentos estiverem implementados.
- Middleware de `_meta` com rejeicao `-32602`/HTTP 400 para campos ausentes,
  validado em cada request sem memorizar metadata anterior.
- Validacao de headers `MCP-Protocol-Version`, `Mcp-Method` e `Mcp-Name`,
  respondendo `-32020` quando nao espelham o corpo.
- Log de cada request no stderr com metodo, id e `traceparent` ou marcador
  explicito de ausencia.

**Gate**

- Smoke `tools/list` traz `listar_salas`; a ferramenta retorna as cinco salas.
- Smoke sem `protocolVersion` e sem `clientCapabilities` retorna -32602/400.
- Logs demonstram metodo, id e trace.

**Estado da branch**

Primeiro processo real e util, permitindo MCP Inspector ou requests wire.

### Commit 4 — `feat: expor resource da politica de uso`

**Implementar**

- `resources/read` de `politica://uso`.
- Conteudo exato do Markdown e `mimeType: text/markdown`.
- URI desconhecida como erro JSON-RPC `-32602`, nunca `contents: []`.
- Registro do resource nas capabilities do servidor.

**Gate**

- O resultado bate com o arquivo `dados/politica-de-uso.md`.
- A URI desconhecida produz -32602.

**Estado da branch**

O servidor ja publica dominio e contexto de aplicacao separadamente.

### Commit 5 — `feat: adicionar consulta de disponibilidade`

**Implementar**

- Tool `consultar_disponibilidade`.
- Mesmas validacoes da reserva, retornando `sala`, `livre` e `conflitos`.
- Erros como tool result completo com `isError: true` e mensagens exatas.
- Acrescentar a tool ao resultado de `tools/list` com seu schema completo.

**Gate**

- Testes de intervalo livre, conflito, sala inexistente, janela, duracao e
  intervalo invertido.
- O texto e o `structuredContent` concordam.

**Estado da branch**

Consulta completa sem escrita e cobrindo os erros de dominio.

### Commit 6 — `feat: implementar reserva no caminho livre`

**Implementar**

- Tool `reservar_sala`.
- Acrescentar a tool ao resultado de `tools/list`; neste ponto ele declara as
  tres tools obrigatorias.
- Reserva imediata quando o intervalo e livre.
- Armazenamento em memoria, IDs sequenciais e visibilidade nas consultas
  subsequentes.
- Resultado completo com `reserva`, `reservado`, `sala`, `inicio`, `fim`,
  `responsavel` e `politica`.
- Erro `Sem alternativas disponiveis no intervalo` apenas quando houver
  conflito e o conjunto calculado de alternativas estiver vazio.

**Gate**

- Fluxo livre gera `res-0003`.
- Consulta posterior enxerga a reserva.
- Um harness focal reproduz as verificacoes 1 a 12; o validador completo ainda
  deve falhar nos checks de MRTR e A2A, que ainda nao existem.

**Estado da branch**

Reserva sincrona funcional; MRTR ainda nao sera exercitado.

### Commit 7 — `feat: proteger o request state`

**Implementar**

- Codec `v1.<payload>.<assinatura>` ou formato compativel com o utilitario oficial
  do SDK, com base64url canonico.
- Payload contendo pedido selado, alternativas, chave esperada da elicitation,
  emissao e expiracao.
- HMAC-SHA-256 usando somente `REQUEST_STATE_SECRET`.
- Validacao do tamanho minimo de 32 bytes da chave.
- Expiracao entre 5 e 30 minutos, fixada em 15 minutos.
- Verificacao em tempo constante, rejeitando adulteracao, expiracao, versao
  desconhecida e formato invalido como `-32602`.
- Nenhum segredo, payload derivado sensivel ou valor real em testes salvos.
- A API de selo/verificacao e o contrato publico e estreito desse modulo; os
  testes desse commit nao inspecionam detalhes de serializacao ou assinatura
  internos.

**Gate**

- Selo funciona antes e depois de reinstanciar o codec/processo.
- Alterar um caractere invalida.
- Chave ausente ou menor que 32 bytes impede a inicializacao com erro explicito.
- Expiracao e formato invalido sao testados.
- O comando recomendado no README usara exatamente a ideia
  `python3 -c "import secrets; print(secrets.token_hex(32))"`; o resultado
  nunca sera versionado nem fixado em exemplo.

**Estado da branch**

Infraestrutura de estado pronta e independente de memoria, ainda nao conectada
a `reservar_sala`.

### Commit 8 — `feat: adicionar pausa e retomada MRTR`

**Implementar**

- Em conflito com alternativas, `reservar_sala` retorna
  `resultType: "input_required"`.
- Um unico `inputRequests` de `elicitation/create`, modo `form`, schema plano,
  campo `sala` com `enum` ou `const`.
- Checagem previa da capability `elicitation.form`; ausencia gera -32021,
  `data.requiredCapabilities` e HTTP 400.
- Retry le `requestState` e `inputResponses` de `params`.
- Entre o `input_required` e o retry, o servidor nao mantem o pedido em mapa,
  cache, sessao ou objeto de conexao; todo dado necessario vem do estado
  verificado.
- Valores de `arguments` do retry nunca substituem os selados.
- Chave da resposta deve coincidir com a do input request; escolha deve estar
  nas alternativas seladas.
- `accept` cria a reserva na sala escolhida.
- Antes de criar a reserva, verificar novamente que a alternativa selada continua
  livre; isso nao implementa decisao concorrente nova, apenas evita persistir um
  conflito visivel no estado atual do processo.
- `decline` e `cancel` retornam `complete`, `isError: false` e
  `reservado: false`.

**Gate**

- Conflito, alternativa, recusa, capability ausente, adulteracao e argumentos
  adulterados passam testes.
- Reiniciar o processo MCP mantendo o mesmo `REQUEST_STATE_SECRET` e repetir o
  retry completo com sucesso.
- Executar requests equivalentes aos checks 13 a 20 e conferir os corpos. A
  execucao integral do validador ainda nao e esperada ate o A2A existir.

**Estado da branch**

Servidor MCP integralmente conforme, inclusive MRTR.

### Commit 9 — `feat: criar cliente MCP do agente`

**Implementar**

- Cliente HTTP independente no agente.
- Antes do primeiro `tools/call`, executar `tools/list` em runtime e
  conservar somente a descoberta, nao uma lista fixa no codigo.
- Executar a descoberta e a leitura do resource na inicializacao preguiçosa do
  cliente, antes da primeira tool; nao confundir runtime discovery com chamada
  hardcoded.
- Ler `politica://uso` e extrair a versao da primeira linha.
- Gerador monotonicamente diferente de ids JSON-RPC.
- Em todo request, incluir `_meta`, cliente/capabilities e tracepropagacao.
- Enviar todos os headers espelhados exigidos.
- Se nao houver `traceparent` de entrada, nao inventar um originado de uma
  outra Task.
- Manter o `traceparent` selecionado no estado privado da Task; continuacoes
  usam o trace da Task, mesmo quando o segundo `SendMessage` nao trouxer o
  header ou trouxer outro valor.
- Expor no log interno request method/id, sem registrar `requestState`.

**Gate**

- Script de integracao com MCP recem-iniciado:
  1. lista tools;
  2. le resource;
  3. chama reserva livre;
  4. chama conflito;
  5. retoma manualmente.
- O log MCP mostra `tools/list` antes de `tools/call`.
- Retry possui id diferente.
- O mesmo trace-id chega ao MCP.
- Os headers `MCP-Protocol-Version`, `Mcp-Method` e `Mcp-Name` sao conferidos
  contra cada corpo emitido.

**Estado da branch**

Agente funciona como host MCP em modo script, sem A2A.

### Commit 10 — `feat: publicar card e Task A2A basica`

**Implementar**

- Processo do agente na porta `7300`.
- `GET /.well-known/agent-card.json` conforme o exemplo v1.0.
- `/a2a` com JSON-RPC 2.0, validacao de method e ids.
- Card inclui nome, descricao, provider, versao, supported interface, modos
  padrao, capabilities sem streaming/push e skill `reservar-sala`.
- Modelo de Task com id, contextId, status, historico e artifacts.
- `SendMessage` cria Task e transita por `TASK_STATE_SUBMITTED` e
  `TASK_STATE_WORKING` antes do resultado.
- `GetTask` devolve a representacao publica atual.
- A representacao publica nunca inclui campos privados.
- Pedido de sala livre conclui com artifact `reserva` contendo a versao lida do
  resource.
- Erro `isError` da tool vira `TASK_STATE_FAILED`, com o texto exato no historico.
- Task terminal rejeita continuacao com erro.
- `GetTask` de id desconhecido e metodo A2A desconhecido sao erros JSON-RPC
  explicitos, sem sucesso simulado.

**Gate**

- Checks de card, fluxo livre, artifact, `GetTask`, terminalidade e `FAILED`
  passam quando isolados.
- Resposta A2A nao contem qualquer `requestState`.

**Estado da branch**

A2A completo nos caminhos sincronos e com produto verificavel.

### Commit 11 — `feat: costurar MRTR com Tasks A2A`

**Implementar**

- Ao receber `input_required`, traduzir enum da elicitation para:
  `alternativas: <ids na mesma ordem>`.
- Mudar a Task para `TASK_STATE_INPUT_REQUIRED`.
- Guardar por Task, em mapa privado:
  - request MCP original em formato serializavel;
  - chave de input;
  - alternativas;
  - `requestState`;
  - traceparent recebido ou marker de ausencia.
- Em continuacao, validar `escolha=<id>` localmente apenas contra o `enum`
  recebido; essa e uma validacao de protocolo, nao regra de negocio.
- Escolha invalida repete a pausa sem alterar ou expor o estado privado.
- Escolha aceita repete o request com novo id, mesma chave em
  `inputResponses`, `action: "accept"` e o estado opaco inalterado.
- `escolha=recusar` usa `action: "decline"` e resulta em Task
  `TASK_STATE_CANCELED`.
- Erro de retry move a Task para `TASK_STATE_FAILED` com texto da
  tool/protocolo adequado.
- Manter mapas por Task separados; nenhuma procura global por requestState.

**Gate**

- Executar o validador completo; checks 1 a 36 devem passar porque esta e a
  primeira etapa que integra as duas pontas.
- Duas Tasks pausadas simultaneamente retomam com seus proprios IDs, argumentos
  e estados.
- Fazer vazamento de string controlada em teste e confirmar que nao chega ao
  JSON A2A.
- Remover o estado privado depois de terminalidade, mantendo somente a
  representacao publica da Task.
- Confirmar manualmente as cinco continuacoes centrais: escolha valida,
  escolha invalida, recusa, reuso de Task terminal e duas Tasks pausadas.

**Estado da branch**

Fluxo ponta a ponta completo, incluindo a ponte central do desafio.

### Commit 12 — `docs: documentar e provar a operacao completa`

**Implementar**

- Substituir o README do starter, sem perder os dados do desafio.
- Documentar:
  - pre-requisitos;
  - comando para gerar e exportar `REQUEST_STATE_SECRET`;
  - instalacao reproduzivel;
  - subida do MCP;
  - subida do agente;
  - validador e smoke curls;
  - ponto exato onde `input_required` vira `INPUT_REQUIRED`;
  - ponto exato onde o `requestState` volta ao MCP;
  - onde ficam Tasks, chave, TTL e segredo;
  - limitacoes conhecidas do SDK, se existirem.
- Manter exatamente as quatro secoes exigidas pelo README, mesmo que haja
  subtitulos dentro delas:
  `Como rodar`, `Onde a ponte acontece`, `Decisoes tecnicas` e
  `Saida do validador`.
- Executar a partir de clone limpo seguindo apenas o README.
- Colar a saida completa do validador no bloco exigido, apos a ultima execucao
  com processos recem-iniciados.

**Gate**

- `36 passaram, 0 falharam`.
- Saida de `pytest` completa.
- Nenhum diff em `dados/`, `validador/` ou `exemplos/`.
- README reproduz a subida sem conhecimento anterior do repositorio.
- O trecho apontado como ponte identifica por simbolo/caminho a traducao de
  `input_required` e a construcao do retry com `requestState`.

### Commit 13 — `chore: validar entrega publica final`

**Implementar**

- Corrigir apenas defeitos revelados pela simulacao de clone limpo.
- Confirmar que nao ha segredo, `.env`, reserva persistida ou artefato local
  acidentalmente versionado.
- Conferir lock, versoes, caminhos relativos, branch `main` e remoto do fork
  publico.

**Gate final**

- Clone limpo, instalacao pelo lock, dois processos separados.
- Card acessivel.
- Validador de 36 checks com saida 0.
- Inspecao manual da sequencia no stderr:
  `tools/list` antes do primeiro `tools/call`, trace-id correto e ids de retry
  diferentes.
- Reinicio entre `input_required` e retry MCP bem-sucedido.
- Repetir o fluxo manual do avaliador, incluindo adulteracao, restart e
  capability ausente, sem recorrer ao log do validador como unico sinal.

## 5. Estrategia de testes

### Unitarios

- Regras puras do dominio, por funcao publica e por exemplos independentes.
- Parser dos textos A2A, com entradas fixas validas e invalidas.
- Maquina de estados A2A, observada pela representacao publica da Task.
- Nao testar a implementacao privada do codec: selagem, adulteracao e expiracao
  sao observadas pela chamada e pelo retry HTTP MCP.

### Integracao MCP

- Streamable HTTP real no endpoint `/mcp`.
- Todos os schemas, statuses HTTP e erros JSON-RPC.
- Ciclo completo de MRTR.
- Restart entre pausa e retry.
- Integridade e expiracao do estado.
- Concorrencia logica de dois request states diferentes.

### Integracao A2A/MCP

- Subir dois processos reais.
- Execucao do cliente agente de forma isolada.
- Card e cada metodo A2A.
- Fluxos livre, pausado, invalido, recusado, falho e terminal.
- Propagacao do traceparent e ordem dos requests no log.

### Validador oficial

Sempre iniciar ambos os processos do zero antes de executar:

```bash
python validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301
```

Nao usar uma rodada anterior como prova, pois as reservas em memoria mudam os
resultados e o validador foi escrito para processos recem-iniciados.

## 6. Matriz dos 36 checks

| Checks | Gate do commit | Responsabilidade principal |
|---|---:|---|
| 1-3 | 6 | Descoberta das tres tools e schemas; resultado de `listar_salas` |
| 4-5 | 3 | `_meta` obrigatorio |
| 6 | 6 | Tool inexistente com as tres tools registradas |
| 7-8 | 4 | Resource valido e URI inexistente |
| 9-12 | 5 | Erros de dominio e disponibilidade |
| 13-15 | 8 | Pausa MRTR, schema ordenado e capability |
| 16-20 | 8 | Retry, integridade, estado selado, recusa e sem alternativa |
| 21-23 | 10 | Agent Card v1.0 |
| 24-26 | 10 | Sucesso, artifact, policy version e `GetTask` |
| 27-30 | 11 | Ponte de pausa, ordem, retry valido e escolha invalida |
| 31 | 10 | Terminalidade |
| 32 | 11 | Cancelamento |
| 33-34 | 11 | Isolamento entre Tasks e ausencia de vazamento |
| 35 | 10 | `FAILED` com mensagem |
| 36 | 11 | Determinismo da pausa |

Os checks 1-36 sao repetidos integralmente nos gates 12 e 13.

Essa matriz e de rastreabilidade. A tabela nao autoriza selecionar ou excluir
checks do `validar.py`: a unica aprovacao final e a execucao inteira com 36 PASS.

## 7. Criterios de saida por componente

### Servidor MCP pronto

- Processo sobe sem segredo hardcoded e para imediatamente se o segredo for
  ausente ou curto.
- `tools/list`, `resources/read` e as tres tools respondem no wire esperado.
- Erros de protocolo e de execucao sao distinguidos por camada e status.
- O ciclo MRTR sobrevive a restart mantendo apenas o mesmo segredo externo.
- Logs permitem auditar cada criterio sem incluir o valor integral de
  `requestState`.

### Agente pronto

- Descobre e le a politica, nao fixa suas versoes/capacidades como substitutos
  do protocolo.
- Preserva o trace-id e usa id novo em cada retry.
- Traduz todos os estados A2A sem implementar regra de sala.
- Mantem o estado MRTR privado por Task.
- Nao expoe detalhes MCP indevidos ao cliente A2A.

### Entrega pronta

- README e comandos funcionam em clone limpo.
- `REQUEST_STATE_SECRET` e fornecido apenas pelo ambiente.
- Arquivos protegidos permanecem identicos.
- Nenhuma dependencia de LLM.
- Branch `main` publica com duas execucoes do validador sem ajustes manuais.

## 8. Riscos e prevencoes

1. **API de MRTR divergente entre versoes do SDK**
   - Prevenir com spike versionado no commit 1.
   - Nao implementar uma camada de transporte propria sem evidencia.
2. **SDK responder JSON-RPC internamente em vez de status HTTP 400**
   - Testar status desde o commit 3.
   - Adaptar apenas o envelope HTTP, mantendo codigo e corpo da spec.
3. **`requestState` depender de cache de processo**
   - Incluir dados completos selados e executar teste real de restart.
4. **Argumentos do retry sobrescreverem os dados originais**
   - Testar adulteracao explicita e ler somente o payload verificado.
5. **Agente esconder a pausa do A2A ao usar callback de elicitation**
   - Manter cliente em modo de baixo nivel que devolva
     `input_required` cru ao chamador; nunca registrar callback de resposta
     automatica.
6. **Mistura de estado entre Tasks**
   - Chavear sempre por `taskId` e testar duas pausas ativas.
7. **Vazamento de `requestState` no A2A**
   - Separar DTO publico de estado privado e ter teste negativo de substring.
8. **Reservas de uma execucao contaminarem validacao**
   - Reiniciar processos antes de cada validador completo.
9. **Timezone e comparacao de strings**
   - Normalizar somente para comparacao; preservar os textos originais selados.
10. **Ordem de alternativas no enum**
    - Implementar e testar comparador explicito; nao iterar um conjunto sem
      ordem.

## 9. Checklist previo ao push final

- [ ] `git diff --exit-code -- dados validador exemplos` passa.
- [ ] Dependencias exatas e instalaveis pelo lock.
- [ ] `pytest` passa a partir de clone limpo.
- [ ] MCP e agente estao em dois processos.
- [ ] Portas e endpoints padrao estao corretos.
- [ ] `REQUEST_STATE_SECRET` nao aparece no Git.
- [ ] O segredo foi gerado conforme o README e possui ao menos 32 bytes.
- [ ] RequestState adulterado e expirado recebem -32602.
- [ ] Retry funciona apos restart do MCP.
- [ ] `traceparent` aparece no stderr com o trace-id do validador.
- [ ] Card v1.0 usa `supportedInterfaces`.
- [ ] O retry e um novo id JSON-RPC.
- [ ] Task terminal nao volta a `WORKING`.
- [ ] Nenhum A2A response contem `requestState`.
- [ ] Validador termina com codigo 0 e 36 PASS.
- [ ] README foi validado literalmente a partir de uma pasta limpa.
- [ ] A branch `main` do fork publico contem toda a entrega.

## 10. Status de execucao

- [x] Etapa 01 — ambiente Python, lock, testes e spike do SDK.
- [x] Etapa 02 — modelos, carregamento e validacao deterministica do dominio.
- [x] Etapa 03 — servidor MCP Streamable HTTP e descoberta de `listar_salas`.
- [x] Etapa 04 — resource `politica://uso`.
- [x] Etapa 05 — consulta de disponibilidade.
- [x] Etapa 06 — reserva no caminho livre.
- [x] Etapa 07 — protecao do `requestState`.
- [ ] Etapa 08 — ciclo MRTR da reserva.
- [ ] Etapa 09 — cliente MCP do agente.
- [ ] Etapa 10 — Agent Card e Task A2A basica.
- [ ] Etapa 11 — costura MRTR com Tasks A2A.
- [ ] Etapa 12 — documentacao e prova da operacao completa.
- [ ] Etapa 13 — validacao da entrega publica final.
