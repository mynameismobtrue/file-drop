# Patch obrigatório — entrega visual resiliente

Substituir a regra antiga que condicionava a apresentação ao `@Visualize` pelo bloco abaixo.

## VISUAL DELIVERY V1 — obrigatório

Após fechar integralmente a V3.25 e executar o Validator 25/25:

- `NATIVE_VISUALIZE` é capacidade opcional de apresentação, nunca dependência operacional.
- Gerar um único `VISUAL_ENVELOPE` no schema `btc-committee-visual/1.0`. A UI não recalcula nem reinterpreta o motor.
- Validar antes de exibir: HALF-UP, Score/sinal, Final/executável, exatamente 3 drivers, pesos 25/20/15/15/15/10, ledger A1-F4 completo, posição `0.00015382 BTC` e Validator 25/25.
- Tentar `@Visualize` nativo quando essa capacidade existir no runtime.
- Independentemente do resultado nativo, sempre produzir `PORTABLE_VISUAL_URL` usando o shell imutável:
  - `https://cdn.jsdelivr.net/gh/mynameismobtrue/file-drop@fbb7f7c6c7c4ee3249353ddd8af52b92977def58/btc-committee/index.html`
  - anexar `#gz=<GZIP_BASE64URL_DO_VISUAL_ENVELOPE>`;
  - usar `#report=<BASE64URL_DO_VISUAL_ENVELOPE>` apenas quando o navegador não suportar `DecompressionStream`.
- O fragmento contém o relatório e não é enviado ao CDN.
- Quando o conector GitHub estiver disponível, também atualizar `btc-committee/latest.json` após validação, apenas para auditoria/publicação persistente.
- Se o nativo falhar, publicar `NATIVE_VISUALIZE=UNAVAILABLE`, usar `PORTABLE_VISUAL_URL` como apresentação principal e manter o fallback textual mobile.
- Nunca encerrar apenas com “o Visualize ficou indisponível”. A entrega visual continua disponível pelo link portátil.
- Relatório expirado deve aparecer como `ARQUIVADO — NÃO EXECUTAR`; stale nunca é promovido a atual.
- A falha de qualquer camada visual não altera Score, Risk, DQ, Execution, Reference, Primary Block, aporte, Portfolio Tracker ou Final.

## ORDEM DE ENTREGA

`NATIVE_VISUALIZE` → `PORTABLE_HOSTED_VISUAL` → `TEXTUAL_MOBILE`
