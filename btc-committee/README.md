# Comitê BTC Diário — Visual Resiliente V1

Camada visual resiliente para o protocolo **Comitê BTC Diário V3.25 Congelada**.

## Causa raiz corrigida

O relatório dependia do recurso nativo `@Visualize` do runtime do ChatGPT. Essa capacidade não é carregada em todos os runtimes, especialmente em algumas execuções agendadas. Assim, a análise podia estar íntegra enquanto a apresentação visual desaparecia.

A arquitetura agora remove esse ponto único de falha:

1. `@Visualize` nativo é um renderizador opcional.
2. O visual operacional usa um shell estático imutável, fixado por commit e servido com MIME correto por raw.githack CDN, sem configuração de GitHub Pages ou Vercel.
3. Cada relatório viaja no fragmento portátil `#gz=` ou `#report=`; o fragmento não é enviado ao CDN.
4. A página valida Score, HALF-UP, tiers, Final, exatamente 3 drivers, ledger DQ, posição BTC e Validator antes de renderizar.
5. Envelope inconsistente é bloqueado; a UI nunca tenta corrigir, completar ou reinterpretar a V3.25.
6. Relatório expirado ou cache local é rotulado **ARQUIVADO — NÃO EXECUTAR**.
7. GitHub Pages permanece apenas como espelho opcional e manual, depois de habilitado nas configurações do repositório.

## Shell operacional

O gerador utiliza um shell imutável no commit:

`fbb7f7c6c7c4ee3249353ddd8af52b92977def58`

Base técnica:

`https://rawcdn.githack.com/mynameismobtrue/file-drop/fbb7f7c6c7c4ee3249353ddd8af52b92977def58/btc-committee/index.html`

O shell contém apenas apresentação e validação. O resultado diário é carregado pelo fragmento da URL, de modo que o CDN não recebe nem armazena o envelope do relatório.

O monitor de saúde exige publicamente:

- `text/html` para o shell;
- JavaScript executável com MIME apropriado;
- `text/css` para estilos;
- contrato do relatório válido;
- geração correta do link portátil.

## Publicação de um novo relatório

1. Gerar o envelope `btc-committee-visual/1.0` depois de fechar integralmente a V3.25.
2. Validar:

```bash
python3 btc-committee/validate_report.py btc-committee/latest.json
```

3. Gerar o link visual portátil:

```bash
python3 btc-committee/make_visual_url.py btc-committee/latest.json
```

O padrão é GZIP + Base64URL em `#gz=`. Use `--plain` apenas para navegadores sem `DecompressionStream`.

4. Quando houver escrita GitHub, também atualizar `btc-committee/latest.json` para auditoria e histórico de publicação. Isso não é requisito para o link portátil funcionar.

## Contrato obrigatório para a tarefa das 16:30

A tarefa deve concluir o motor econômico antes de renderizar. Depois disso:

1. Gerar um único `VISUAL_ENVELOPE`.
2. Validar o envelope.
3. Tentar o `@Visualize` nativo quando disponível.
4. Sempre gerar `PORTABLE_VISUAL_URL` com `make_visual_url.py` ou algoritmo equivalente.
5. Entregar o link portátil como camada visual garantida, mesmo quando o nativo funcionar.
6. Se o nativo falhar, registrar apenas `NATIVE_VISUALIZE=UNAVAILABLE`; o link portátil passa a ser a apresentação principal.
7. Manter o fallback textual mobile como terceira camada.

## Hierarquia de entrega

`NATIVE_VISUALIZE` → `PORTABLE_HOSTED_VISUAL` → `TEXTUAL_MOBILE`

A falha de uma camada não altera Score, Risk, DQ, Execution, Reference, Primary Block, Portfolio Tracker, aporte ou Final.

## Monitoramento

- `btc-visualize-ci.yml` valida contrato, assets e smoke test local.
- `btc-visualize-health.yml` testa periodicamente o shell público imutável, MIME HTML/JS/CSS, health contract, envelope atual e geração do link portátil.
- `pages.yml` é manual-only para não gerar falhas recorrentes enquanto GitHub Pages não estiver habilitado.
