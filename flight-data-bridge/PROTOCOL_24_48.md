# Flight Data Bridge V1.1 - Contrato técnico 24-48

Este documento complementa, sem alterar, as regras 1-23 do **Lisboa V2.2**.

## 24. Camada de aquisição

O Lisboa V2.2 é a autoridade. Providers, APIs e storage são evidência. UNKNOWN nunca vira TRUE. ChatGPT não promove uma oferta rejeitada pelo engine.

## 25. Versionamento

`DATA_BRIDGE_VERSION=1.1.0`, `PROTOCOL_VERSION=LISBOA_V2.2`, `UI_VERSION=1.0.0` são independentes. Mudança de provider, schema, workflow ou UI não altera o protocolo automaticamente.

## 26. Provider architecture

Todo provider implementa `ProviderAdapter`. Respostas proprietárias precisam virar o modelo normalizado antes dos filtros.

## 27. Hierarquia

Skyscanner: `PRIMARY_DISCOVERY`. Ignav: `PRIMARY_DISCOVERY_TEMPORARY` / `SECONDARY_DISCOVERY`. Duffel: `CORROBORATION` opcional.

Revalidação pelo mesmo provider é `SECOND_INDEPENDENT_ACQUISITION`, não confirmação por fonte independente. O resultado registra `same_provider_revalidation` e `independent_source_corroboration` separadamente.

## 28. Independência

`ITINERARY_FINGERPRINT` representa o voo físico. `COMMERCIAL_OFFER_ID` representa fingerprint + provider + agente + pricing/source offer. Preço igual não prova mesma oferta comercial. Campo não comprovado por contrato pode participar apenas como `UNVERIFIED_FIELD`, nunca como evidência positiva de elegibilidade.

## 29. Search universe

12/12 queries são obrigatórias para um provider ser considerado completo. Menos que 12 => `INCOMPLETE`. Open-jaw permanece uma única oferta comercial.

## 30. Search status / source health

Uma falha técnica nunca significa ausência de passagens. `COMPLETE_WITH_SOURCE_ERRORS` só existe quando o provider ativo fechou 12/12, mas houve erro em outra fonte/fonte de maior prioridade. O fallback é sempre explícito.

## 31. Freshness

Snapshot: 90 min. Alert validation: 10 min. Expiração de oferta, quando menor, prevalece.

## 32. Normalized schema

Schema em `schema/snapshot.schema.json`. Inclui search metadata, provider results, offers, directions, segments, connections, derived state, validation results e price history.

## 33. Missing data

`HARD_REJECTED`: violação comprovada. `NON_VALIDATABLE`: evidência insuficiente. Nenhum gera alerta. Bagagem desconhecida é reportada como desconhecida, mas não reprova por si só. Operating carrier ausente nunca herda marketing carrier.

## 34. Revalidação

Discovery completo -> normalize -> filters -> quality -> price -> segunda aquisição independente -> exact itinerary match -> commercial refresh -> filters de novo -> price de novo -> freshness -> candidate.

## 35. Booking integrity

Não combinar vendedores ou one-ways independentes. Compra única precisa cobrir os dois legs obrigatórios. Alternativas de vendedores full-trip podem existir como ofertas comerciais distintas. Refresh nunca escolhe outra oferta apenas por preço menor.

## 36. IDs

`SOURCE_OFFER_ID`: id proprietário. `ITINERARY_FINGERPRINT` e `OFFER_ID`: identidade física. `COMMERCIAL_OFFER_ID`: fingerprint + provider + agente + source/pricing option.

## 37. Price history

Somente `ELIGIBLE/HARD_FILTER_PASS=true`. Métricas são informativas e jamais mudam threshold ou hard filters.

## 38. Histórico

Toda tentativa gera registro; ofertas rejeitadas e não-validáveis mantêm reason codes. Nada é descartado silenciosamente.

## 39. Errors

Estruturados: `AUTH_REQUIRED`, `INVALID_API_KEY`, `RATE_LIMITED`, `BILLING_REQUIRED`, `INVALID_REQUEST`, `NOT_FOUND`, `UPSTREAM_DEPENDENCY`, `PROVIDER_TIMEOUT`, `PROVIDER_NETWORK_ERROR`, `PROVIDER_HTTP_ERROR`, `SEARCH_PARTIAL`, `POLL_TIMEOUT`, `POLL_FAILED`, `SCHEMA_INVALID`, `NORMALIZATION_ERROR`, `OPERATING_CARRIER_UNKNOWN`, `CONNECTION_COUNTRY_UNKNOWN`, `PRICE_UNCONFIRMED`, `CURRENCY_UNSUPPORTED`, `OFFER_EXPIRED`, `OFFER_DISAPPEARED`, `BOOKING_OPTION_MISSING`, `MULTIPLE_BOOKING_REQUIRED`. Mapeamento não comprovado é marcado como provisional, não congelado como fato.

## 40. Segurança

Secrets somente em GitHub Actions Secrets. Session tokens ficam em memória e nunca entram em `to_dict()`. Dados live pessoais devem preferencialmente ficar em repositório privado.

## 41. Concorrência

Workflow usa `cancel-in-progress=false`. Nova execução aguarda a anterior no mesmo grupo, em vez de cancelá-la silenciosamente.

## 42. Projetos públicos

Apenas referência de engenharia/licença compatível. Scraping/browser/LLM extraction não é primary discovery. Código de terceiros só entra após revisão explícita; na V1.1.0 nenhum SDK público foi adicionado como dependência runtime.

## 43. Provider fallback

Sempre explícito. Um provider secundário só vira discovery ativo se fechar 12/12 e passar os mesmos filtros. Equivalência de cobertura entre providers não é presumida.

## 44. Web search

Auxiliar para auditoria, nunca substituição silenciosa de provider live quebrado e nunca preenchimento oculto de campo crítico.

## 45. Regressão

A suíte em `tests/` cobre boundaries e falhas materiais do contrato, incluindo fixtures OpenAPI Ignav, health/error mapping e booking revalidation.

## 46. Production gate

Ver `PRODUCTION_GATE.md`. Unit tests e playground não equivalem a produção validada.

## 47. Interface ChatGPT

ChatGPT lê metadata/status/health/TTL antes de ofertas. Só `ALERT_CANDIDATES` revalidados podem gerar alerta. Resumo usa histórico real.

## 48. Precedência

1. Lisboa V2.2 hard rules
2. normalized verified data
3. provider live data
4. history
5. web auxiliar

Preço nunca vence elegibilidade. Ausência nunca vira aprovação. Silêncio é resultado correto.
