# Comitê BTC Diário — Visual Permanente V1

Camada visual resiliente para o protocolo **Comitê BTC Diário V3.25 Congelada**.

## Problema corrigido

O relatório dependia do recurso nativo `@Visualize` do runtime do ChatGPT. Esse recurso não está presente em todos os runtimes, especialmente em algumas execuções agendadas. Quando a capacidade nativa não era carregada, a análise podia estar correta, mas a apresentação visual desaparecia.

A correção remove esse acoplamento:

1. `@Visualize` passa a ser apenas um renderizador opcional.
2. O visual permanente é servido pelo GitHub Pages em `/btc-committee/`.
3. A página aceita um envelope publicado em `latest.json` ou um envelope portátil no fragmento `#report=`/`#gz=`.
4. O navegador valida Score, HALF-UP, tiers, Final, DQ ledger, posição BTC e Validator antes de renderizar.
5. Envelope inconsistente é bloqueado; a UI nunca tenta “consertar” ou reinterpretar a V3.25.
6. Falha de rede pode exibir somente o último envelope íntegro salvo localmente, rotulado como **ARQUIVADO / NÃO EXECUTAR**.

## Rotas

- Painel estável: `https://mynameismobtrue.github.io/file-drop/btc-committee/`
- Saúde estática: `https://mynameismobtrue.github.io/file-drop/btc-committee/health.json`
- Última publicação: `https://mynameismobtrue.github.io/file-drop/btc-committee/latest.json`

## Publicação de um novo relatório

1. Substituir `latest.json` por um envelope `btc-committee-visual/1.0`.
2. Executar:

```bash
python3 btc-committee/validate_report.py btc-committee/latest.json
```

3. Para gerar um link que não depende de gravação no GitHub:

```bash
python3 btc-committee/make_visual_url.py btc-committee/latest.json
```

O link portátil usa `#gz=` com GZIP + Base64URL e carrega o envelope no fragmento da URL. O fragmento não é enviado ao servidor. Use `--plain` apenas para navegadores sem `DecompressionStream`.

## Contrato obrigatório para a tarefa das 16:30

A tarefa deve encerrar a análise econômica antes de renderizar. Depois disso:

1. Gerar o envelope visual conforme `latest.json`.
2. Validar o envelope.
3. Tentar o `@Visualize` nativo, quando disponível.
4. **Sempre** fornecer também o visual permanente:
   - preferencialmente, publicar o envelope em `btc-committee/latest.json`;
   - se a escrita no GitHub não estiver disponível, gerar o link portátil `#gz=`.
5. Se o recurso nativo falhar, não declarar que “a visualização ficou indisponível”. Declarar apenas `NATIVE_VISUALIZE=UNAVAILABLE` e usar o painel permanente como apresentação principal.
6. O fallback textual mobile continua obrigatório como terceira camada, nunca como única camada visual.

## Hierarquia de entrega

`NATIVE_VISUALIZE` → `HOSTED_VISUAL` → `TEXTUAL_MOBILE`

A falha de uma camada não invalida as demais nem altera Score, Risk, DQ, Execution, Primary Block ou Final.
