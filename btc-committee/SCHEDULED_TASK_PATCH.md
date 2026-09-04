# Patch obrigatório — entrega visual resiliente

Substituir a regra antiga que condicionava a apresentação ao `@Visualize` pelo bloco abaixo.

## VISUAL DELIVERY V1 — obrigatório

Após fechar integralmente a V3.25 e executar o Validator 25/25:

- `NATIVE_VISUALIZE` é uma capacidade opcional de apresentação, nunca dependência operacional.
- Gerar um único `VISUAL_ENVELOPE` no schema `btc-committee-visual/1.0`. A UI não pode recalcular nem reinterpretar o motor.
- Validar antes de exibir: HALF-UP, Score/sinal, Final/executável, exatamente 3 drivers, pesos 25/20/15/15/15/10, ledger A1-F4 completo, posição `0.00015382 BTC` e Validator 25/25.
- Tentar `@Visualize` nativo.
- Em paralelo, sempre produzir `HOSTED_VISUAL_URL` usando `https://mynameismobtrue.github.io/file-drop/btc-committee/`:
  - atualizar `btc-committee/latest.json` quando o conector GitHub estiver disponível; ou
  - gerar link portátil `#gz=<GZIP_BASE64URL_DO_VISUAL_ENVELOPE>` quando não houver escrita.
- Se o nativo falhar, publicar `NATIVE_VISUALIZE=UNAVAILABLE`, usar `HOSTED_VISUAL_URL` como apresentação principal e manter o fallback textual mobile.
- Nunca dizer apenas que “o Visualize ficou indisponível”. A entrega visual é considerada disponível quando `HOSTED_VISUAL_URL` está íntegra.
- Relatório expirado deve aparecer como `ARQUIVADO — NÃO EXECUTAR`; stale nunca é promovido a atual.
- A falha da camada visual não altera Score, Risk, DQ, Execution, Primary Block, aporte, Portfolio Tracker ou Final.
