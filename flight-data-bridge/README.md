# Flight Data Bridge V1.0

**DATA_BRIDGE_VERSION:** `1.0.0`  
**PROTOCOL_VERSION:** `LISBOA_V2.2`  
**UI_VERSION:** `1.0.0`  
**STATE:** `PRE_PRODUCTION`

## Objetivo

Separar aquisição de dados da decisão:

`PROVIDER -> RAW RESPONSE -> NORMALIZAÇÃO -> SCHEMA VALIDATION -> HARD FILTERS -> QUALITY -> PRICE -> REVALIDAÇÃO -> VERIFIED_ALERT_CANDIDATE -> CHATGPT`

O protocolo Lisboa V2.2 é a autoridade. Providers são fontes de evidência e não podem alterar rota, datas, companhias proibidas, conexão, duração, preço-alvo ou regras de alerta.

## Regras V2.2 preservadas

- ida: `GRU` ou `VCP` -> `LIS`;
- saída: 26, 27 ou 28/10/2026;
- chegada final em Lisboa: somente 27 ou 28/10/2026;
- volta: sair de `LIS` em 03/11/2026 para `GRU` ou `VCP`;
- econômica;
- máximo 1 conexão por sentido;
- conexão <= 300 min; 300 passa, 301 rejeita;
- duração <= 1080 min por sentido; 1080 passa, 1081 rejeita;
- sem self-transfer, protected self-transfer, troca de aeroporto ou compra separada obrigatória;
- sem conexão na África;
- TAAG (`DT`) proibida em marketing e operating carrier, em qualquer segmento;
- alerta somente com preço total por pessoa estritamente `< R$4.500`;
- R$4.500,00 não alerta;
- bagagem desconhecida permanece desconhecida e não é inferida;
- UNKNOWN nunca vira TRUE.

## Providers

### Skyscanner

`ROLE=PRIMARY_DISCOVERY` quando `SKYSCANNER_API_KEY` existir e 12/12 queries concluírem.

Fluxo: `create -> poll -> RESULT_STATUS_COMPLETE`. O retorno de `create` nunca é tratado como busca completa. Para candidato abaixo do threshold, o bridge executa uma segunda aquisição completa do mesmo itinerário e depois `itineraryrefresh` da mesma pricing option. Uma pricing option diferente não substitui silenciosamente a original.

### Ignav

`ROLE=PRIMARY_DISCOVERY_TEMPORARY` / fallback explícito quando configurado via `IGNAV_API_KEY`.

Usa `POST /api/fares/search` com dois legs em uma única busca comercial, inclusive open-jaw. `max_stops=1` fica dentro de cada leg. Top-level: `market=BR`, `cabin_class=economy`, `allow_self_transfer=false`, `airlines_exclude=["DT"]`.

Candidato de alerta é revalidado com `booking-links(ignav_id)`. O `itinerary` retornado pela revalidação é a versão corrente. Se não existir opção única cobrindo ambos os legs, não há alerta.

### Duffel

`ROLE=CORROBORATION`, opcional. Ausência no Duffel nunca invalida uma oferta válida de outro provider. Matching entre providers só ocorre por fingerprint normalizado de segmentos. Test mode não é evidência de preço real.

## Universo de busca

12 combinações por provider completo:

`2 origens x 3 datas de ida x 2 destinos de retorno = 12`.

Open-jaw é uma única pesquisa comercial. É proibido fabricar open-jaw somando duas tarifas one-way independentes.

## Estados

Search: `STARTED | PARTIAL | COMPLETE | COMPLETE_WITH_SOURCE_ERRORS | INCOMPLETE | FAILED | TIMED_OUT`

Source health: `LIVE | DEGRADED | UNAVAILABLE | AUTH_REQUIRED | RATE_LIMITED | BILLING_REQUIRED | ERROR`

Freshness: `LIVE | STALE | UNAVAILABLE`

Eligibility: `ELIGIBLE | HARD_REJECTED | NON_VALIDATABLE`

Validation: `NOT_REQUIRED | VALIDATED | PRICE_CHANGED | DISAPPEARED | NON_VALIDATABLE | ERROR`

`SOURCE_HEALTH` mede capacidade técnica do provider. `TTL_STATUS` mede idade temporal da evidência. Um não substitui o outro.

## Fallback

Fallback nunca é silencioso. Se Skyscanner falha e Ignav fecha 12/12:

- `PRIMARY_STATUS=FAILED/INCOMPLETE/...`
- `ACTIVE_DISCOVERY_PROVIDER=IGNAV`
- `SEARCH_STATUS=COMPLETE_WITH_SOURCE_ERRORS`
- `SOURCE_HEALTH=DEGRADED`
- `COVERAGE_EQUIVALENCE_NOT_ASSERTED=true`

O bridge não declara que dois providers possuem a mesma cobertura comercial.

## Freshness

- `FLIGHT_SEARCH_TTL=90 min` para snapshot.
- `ALERT_VALIDATION_TTL=10 min` para alerta.
- se `OFFER_EXPIRES_AT` vencer antes, usa-se a validade menor.
- snapshot stale serve para histórico, não para afirmar disponibilidade agora.

## Persistência

- `snapshot.json`: último ciclo completo somente;
- `status.json`: tentativa mais recente, inclusive falha;
- `history/YYYY-MM-DD/*.json`: auditoria imutável por tentativa.

Ciclo incompleto nunca sobrescreve `snapshot.json`.

## Segredos

Nunca serializar API keys ou session tokens. Secrets previstos:

- `SKYSCANNER_API_KEY`
- `IGNAV_API_KEY`
- `DUFFEL_ACCESS_TOKEN` (opcional)

Variáveis previstas:

- `FLIGHT_BRIDGE_LIVE_ENABLED=true`
- `FLIGHT_BRIDGE_PRODUCTION_APPROVED=true` somente depois do production gate e aprovação explícita.

## Produção

A suíte unitária não basta. O estado permanece `PRE_PRODUCTION` até cumprir `PRODUCTION_GATE.md`, testar provider live, revisar 12/12, validar snapshot real, revisar rejeitados/não-validáveis e aprovar explicitamente o schedule.
