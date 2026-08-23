# Automação 2 - Resumo diário Lisboa V2.2

Use o histórico técnico real do Flight Data Bridge, não a quantidade teórica de ciclos.

Informar de forma curta:
- buscas concluídas (`COMPLETE` + `COMPLETE_WITH_SOURCE_ERRORS`);
- buscas `INCOMPLETE`, `FAILED` ou `TIMED_OUT`;
- providers ativos/fallbacks ocorridos;
- menor preço elegível do dia e horário;
- companhia(s) operadora(s), rota, direto/conexão e qualidade;
- `MIN_SINCE_START` e `DELTA_HISTORICAL_MIN` quando disponíveis;
- variação ao longo do dia;
- ofertas elegíveis abaixo de R$4.500;
- quantas foram revalidadas;
- quantas desapareceram;
- bagagem quando confirmada;
- source health relevante.

Nunca usar oferta `HARD_REJECTED` ou `NON_VALIDATABLE` como benchmark válido. Nunca dizer que 16 buscas foram executadas apenas porque 16 estavam programadas.
