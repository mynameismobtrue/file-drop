# Automação 1 - Monitor Lisboa V2.2 + Flight Data Bridge V1.0

Leia o Flight Data Bridge. O Lisboa V2.2 permanece autoridade.

1. Leia `SEARCH_METADATA`.
2. Exija `IS_COMPLETE=true` e `SEARCH_STATUS` igual a `COMPLETE` ou `COMPLETE_WITH_SOURCE_ERRORS`.
3. Verifique `SOURCE_HEALTH` e `TTL_STATUS`. Snapshot stale/unavailable não comprova disponibilidade agora.
4. Leia apenas `ALERT_CANDIDATES` para possível alerta.
5. Para cada candidato exija:
   - `derived.HARD_FILTER_PASS=true`;
   - `derived.ELIGIBILITY_STATE=ELIGIBLE`;
   - `derived.ALERT_PRICE_PASS=true`;
   - `derived.VERIFIED_ALERT_CANDIDATE=true`;
   - `validation_status` = `VALIDATED` ou `PRICE_CHANGED`;
   - `derived.VALIDATION_FRESH=true`;
   - preço total BRL < R$4.500;
   - ausência de qualquer regra proibida do Lisboa V2.2.
6. Nunca promover `REJECTED_OFFERS` ou `NON_VALIDATABLE_OFFERS`.
7. Se nenhum candidato passar, permanecer em silêncio.
8. Se houver candidato, comunicar preço por pessoa, qualidade A/B/C, marketing carrier, operating carrier de todos os segmentos, GRU/VCP, datas/horários locais, chegada LIS, volta 03/11, conexões/duração, duração total, bagagem confirmada/não confirmada, agente/fonte e link.
9. Se `SEARCH_STATUS=COMPLETE_WITH_SOURCE_ERRORS`, informar discretamente que houve fallback/degradação e qual `ACTIVE_DISCOVERY_PROVIDER` sustentou 12/12, sem afirmar equivalência de cobertura.

Nunca fazer web search para substituir silenciosamente um bridge quebrado. Web pode ser auditoria auxiliar declarada.
