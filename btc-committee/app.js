(() => {
  'use strict';
  const ALLOWED_SIGNALS = [0, 50, 100, 150, 200, 300, 400, 500];
  const SCORE_WEIGHTS = { valuation: 25, trend: 20, flows: 15, onchain: 15, macro: 15, micro: 10 };
  const SIGNAL_FOR_SCORE = score => score <= 54 ? 0 : score <= 61 ? 50 : score <= 68 ? 100 : score <= 74 ? 150 : score <= 79 ? 200 : score <= 84 ? 300 : score <= 89 ? 400 : 500;
  const q = s => document.querySelector(s);
  const root = q('#root');
  const banner = q('#banner');
  const infraText = q('#infraText');
  const esc = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const brl = value => Number.isFinite(Number(value)) ? new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(Number(value)) : 'INDISPONÍVEL';
  const pct = value => Number.isFinite(Number(value)) ? `${Number(value) >= 0 ? '+' : ''}${new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value))}%` : 'INDISPONÍVEL';
  const num = (value, digits = 2) => Number.isFinite(Number(value)) ? new Intl.NumberFormat('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Number(value)) : '—';
  const formatDateTime = iso => {
    const d = new Date(iso);
    return Number.isFinite(d.getTime()) ? new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(d) + ' BRT' : 'timestamp inválido';
  };
  const displayStatus = (text, kind = 'warn') => { banner.className = `status-banner show ${kind}`; banner.textContent = text; };

  function decodeBase64Url(value) {
    const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
    const pad = normalized.length % 4 ? '='.repeat(4 - normalized.length % 4) : '';
    const binary = atob(normalized + pad);
    const bytes = Uint8Array.from(binary, c => c.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  }

  async function reportFromHash() {
    const hash = new URLSearchParams(location.hash.replace(/^#/, ''));
    const gzipEncoded = hash.get('gz');
    if (gzipEncoded) {
      if (!('DecompressionStream' in window)) throw new Error('Este navegador não suporta o link portátil compactado. Use a publicação estável.');
      const normalized = gzipEncoded.replace(/-/g, '+').replace(/_/g, '/');
      const pad = normalized.length % 4 ? '='.repeat(4 - normalized.length % 4) : '';
      const binary = atob(normalized + pad);
      const bytes = Uint8Array.from(binary, c => c.charCodeAt(0));
      const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
      return JSON.parse(await new Response(stream).text());
    }
    const encoded = hash.get('report');
    if (!encoded) return null;
    return JSON.parse(decodeBase64Url(encoded));
  }

  async function loadReport() {
    const embedded = await reportFromHash();
    if (embedded) return { payload: embedded, mode: 'LINK_PORTÁTIL' };
    const response = await fetch(`./latest.json?nocache=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`latest.json retornou HTTP ${response.status}`);
    return { payload: await response.json(), mode: 'LATEST_PUBLICADO' };
  }

  function validateEnvelope(envelope) {
    const errors = [];
    const r = envelope?.report;
    if (envelope?.schema_version !== 'btc-committee-visual/1.0') errors.push('schema_version incompatível');
    if (!r || typeof r !== 'object') return ['report ausente'];
    if (!/^\d{8}-\d{4}-BRT$/.test(r.cycle?.id || '')) errors.push('cycle.id inválido');
    const score = Number(r.decision?.score_final);
    const raw = Number(r.score?.total_raw);
    const theoretical = Number(r.decision?.signal_theoretical_brl);
    const executable = Number(r.decision?.executable_now_brl);
    if (!Number.isInteger(score) || score < 0 || score > 100) errors.push('score_final inválido');
    if (!Number.isFinite(raw) || Math.floor(raw + .5) !== score) errors.push('HALF-UP inconsistente');
    if (!ALLOWED_SIGNALS.includes(theoretical)) errors.push('sinal teórico fora dos tiers');
    if (Number.isInteger(score) && SIGNAL_FOR_SCORE(score) !== theoretical) errors.push('sinal teórico incompatível com score');
    if (!ALLOWED_SIGNALS.includes(executable)) errors.push('executável fora dos tiers');
    if (r.decision?.final === 'AUTORIZADA' ? executable !== theoretical : executable !== 0) errors.push('teórico versus executável inconsistente');
    if (!Array.isArray(r.drivers) || r.drivers.length !== 3) errors.push('drivers deve conter exatamente 3 itens');
    const breakdown = r.score?.breakdown || {};
    let sum = 0;
    for (const [key, weight] of Object.entries(SCORE_WEIGHTS)) {
      const item = breakdown[key];
      if (!item || Number(item.weight) !== weight) errors.push(`peso inválido em ${key}`);
      const value = Number(item?.value);
      if (!Number.isFinite(value) || value < 0 || value > weight) errors.push(`valor inválido em ${key}`);
      else sum += value;
    }
    if (Number.isFinite(raw) && Math.abs(sum - raw) > .001) errors.push('TOTAL_RAW não corresponde à soma dos blocos');
    if (Number(r.validator?.evaluated_count) !== 25 || r.validator?.result !== 'PASS') errors.push('validator não é 25/25 PASS');
    if (!Array.isArray(r.validator?.asserts) || r.validator.asserts.length !== 25) errors.push('lista de asserts incompleta');
    if (!Number.isInteger(Number(r.gates?.dq?.score)) || Number(r.gates?.dq?.score) < 0 || Number(r.gates?.dq?.score) > 100) errors.push('DQ inválido');
    if (!Array.isArray(r.dq_ledger?.items) || r.dq_ledger.items.length !== 24) errors.push('ledger DQ deve conter 24 itens');
    return errors;
  }

  function archivedState(report) {
    const expires = new Date(report.cycle?.execution_expires_at || '');
    if (!Number.isFinite(expires.getTime())) return { archived: true, text: 'Relatório sem validade temporal executável. Use apenas para consulta.' };
    const archived = Date.now() > expires.getTime();
    return { archived, text: archived ? `RELATÓRIO ARQUIVADO — janela executável expirou em ${formatDateTime(expires.toISOString())}. Não executar esta indicação agora.` : `Relatório dentro da janela executável até ${formatDateTime(expires.toISOString())}.` };
  }

  function scoreBars(report) {
    const labels = { valuation: 'Valuation', trend: 'Trend', flows: 'Flows', onchain: 'On-chain', macro: 'Macro', micro: 'Micro MB' };
    return Object.entries(SCORE_WEIGHTS).map(([key, weight]) => {
      const value = Number(report.score.breakdown[key].value);
      return `<div class="bar"><span>${labels[key]}</span><div class="track"><div class="fill" style="width:${Math.max(0, Math.min(100, value / weight * 100))}%"></div></div><span class="bar-value">${num(value)} / ${weight}</span></div>`;
    }).join('');
  }

  function renderPortfolio(p) {
    const current = p?.current || {};
    const last = p?.last_verified || {};
    const shown = current.available ? current : last;
    const valueLabel = current.available ? 'Patrimônio no ciclo' : 'Último patrimônio verificável';
    const markLabel = current.available ? current.mark_type : last.mark_type;
    const state = shown.direction_since_origin || 'INDISPONÍVEL';
    const gainClass = Number(shown.gain_origin_brl) >= 0 ? 'gain-box' : 'gain-box';
    return `<section class="portfolio" aria-label="Minha posição no Mercado Bitcoin">
      <div class="portfolio-head"><div><div class="section-kicker">Minha posição no MB</div></div><div class="seal">posição confirmada em 22/08/2026<br>${esc(p.position_btc)} BTC</div></div>
      <div class="portfolio-main">
        <div><div class="portfolio-value">${shown.available === false ? 'INDISPONÍVEL' : brl(shown.value_brl)}</div><div class="portfolio-state">${esc(state)}</div><div class="portfolio-meta">${esc(valueLabel)} · ${esc(markLabel || 'sem mark')}<br>${shown.mark_timestamp ? formatDateTime(shown.mark_timestamp) : 'timestamp indisponível'}</div></div>
        <div class="${gainClass}"><div class="gain">${brl(shown.gain_origin_brl)}</div><div class="pct">${pct(shown.gain_origin_pct)}</div><div class="label">desde 11/06 · base aproximada ${brl(p.display_baseline_brl)}</div></div>
      </div>
      ${current.available ? '' : `<div class="primary-block"><b>Patrimônio atual indisponível.</b> O card mostra somente o último mark oficial verificável; nenhum preço stale ou proxy foi promovido a preço atual.</div>`}
    </section>`;
  }

  function renderDQLedger(report) {
    const groups = {};
    for (const item of report.dq_ledger.items) (groups[item.block] ||= []).push(item);
    return Object.entries(groups).map(([block, items]) => `<details><summary><span>Bloco ${esc(block)} · ${items.filter(x => x.qualified === 1).length}/4 qualificados</span><span>abrir</span></summary><div class="detail-body">${items.map(i => `<div class="row"><span>${esc(i.id)}</span><b>${i.qualified === 1 ? 'PASS_ALL_REQUIREMENTS' : esc(i.reason_codes.join(' / '))}</b></div>`).join('')}</div></details>`).join('');
  }

  function renderAsserts(asserts) {
    return `<div class="audit-grid">${asserts.map(a => `<div class="assert"><b>${esc(a.id)}</b><span>${esc(a.status.replace('PASS-', ''))}</span></div>`).join('')}</div>`;
  }

  function renderSources(sources) {
    return sources.map(s => {
      const safeUrl = /^https:\/\//.test(s.url || '') ? s.url : '#';
      return `<a class="source" href="${esc(safeUrl)}" target="_blank" rel="noopener noreferrer"><b>${esc(s.label)}</b><small>${esc(s.role)} · ${esc(s.tier)}</small></a>`;
    }).join('');
  }

  function render(envelope, mode) {
    const r = envelope.report;
    const archive = archivedState(r);
    displayStatus(archive.text, 'warn');
    infraText.textContent = mode === 'LINK_PORTÁTIL' ? 'Visual por link portátil' : 'Visual publicado';
    const distance = r.decision.distance_to_next_threshold_points == null ? '—' : `+${r.decision.distance_to_next_threshold_points} pts`;
    root.className = '';
    root.removeAttribute('aria-busy');
    root.innerHTML = `
      <section class="hero">
        <div class="hero-grid">
          <div>
            <div class="eyebrow">Executável agora</div>
            <div class="amount">${brl(r.decision.executable_now_brl)}</div>
            <div class="action">${esc(r.decision.action)}</div>
            <div class="summary">${esc(r.decision.summary)}</div>
            <div class="primary-block"><b>Primary Block:</b> ${esc(r.decision.primary_block)}</div>
          </div>
          <div class="metrics">
            <div class="metric"><div class="metric-k">Sinal teórico</div><div class="metric-v">${brl(r.decision.signal_theoretical_brl)}</div><div class="metric-s">exclusivamente pelo Score</div></div>
            <div class="metric"><div class="metric-k">Opportunity Score</div><div class="metric-v">${r.decision.score_final}/100</div><div class="metric-s">${esc(r.decision.score_class)}</div></div>
            <div class="metric"><div class="metric-k">Próximo threshold</div><div class="metric-v">${distance}</div><div class="metric-s">${esc(r.decision.next_threshold_label || 'não aplicável')}</div></div>
            <div class="metric"><div class="metric-k">Final</div><div class="metric-v" style="font-size:17px">${esc(r.decision.final)}</div><div class="metric-s">V3.25 congelada</div></div>
          </div>
        </div>
      </section>
      ${renderPortfolio(r.portfolio)}
      <nav class="tabs" role="tablist" aria-label="Seções do relatório">
        <button class="tab" role="tab" aria-selected="true" data-panel="why">Por quê?</button>
        <button class="tab" role="tab" aria-selected="false" data-panel="score">Score</button>
        <button class="tab" role="tab" aria-selected="false" data-panel="wallet">Minha carteira</button>
        <button class="tab" role="tab" aria-selected="false" data-panel="mb">Mercado MB</button>
        <button class="tab" role="tab" aria-selected="false" data-panel="audit">Auditoria</button>
      </nav>
      <section id="why" class="panel active" role="tabpanel"><div class="grid">
        <div class="card"><div class="card-title">Exatamente 3 drivers materiais</div>${r.drivers.map((d, i) => `<div class="driver"><b>${i + 1} · ${esc(d.title)}</b><p>${esc(d.detail)}</p></div>`).join('')}</div>
        <div class="card s6"><div class="card-title">Gates 2×2</div><div class="gate-grid"><div class="gate"><div class="metric-k">Risk</div><div class="v">${esc(r.gates.risk.status)}</div><div class="s">${esc(r.gates.risk.note)}</div></div><div class="gate"><div class="metric-k">DQ</div><div class="v">${r.gates.dq.score}/100</div><div class="s">${esc(r.gates.dq.class)}</div></div><div class="gate"><div class="metric-k">Execution</div><div class="v">${esc(r.gates.execution.status)}</div><div class="s">${esc(r.gates.execution.note)}</div></div><div class="gate"><div class="metric-k">Validator</div><div class="v">${r.validator.evaluated_count}/25 ${esc(r.validator.result)}</div><div class="s">Materiality ${esc(r.gates.materiality)}</div></div></div></div>
        <div class="card s6"><div class="card-title">Ciclo</div><div class="row"><span>ID</span><b>${esc(r.cycle.id)}</b></div><div class="row"><span>Início</span><b>${formatDateTime(r.cycle.started_at)}</b></div><div class="row"><span>Conclusão</span><b>${formatDateTime(r.cycle.completed_at)}</b></div><div class="row"><span>Regime</span><b>${esc(r.cycle.regime)}</b></div></div>
      </div></section>
      <section id="score" class="panel" role="tabpanel"><div class="grid">
        <div class="card s8"><div class="card-title">Composição do Opportunity Score</div>${scoreBars(r)}</div>
        <div class="card s4"><div class="card-title">Fechamento</div><div class="big">${num(r.score.total_raw)}</div><div class="muted">TOTAL_RAW</div><div class="row"><span>SCORE_FINAL</span><b>${r.decision.score_final}</b></div><div class="row"><span>Classe</span><b>${esc(r.decision.score_class)}</b></div><div class="row"><span>Sinal</span><b>${brl(r.decision.signal_theoretical_brl)}</b></div></div>
        <div class="card"><div class="card-title">Anti-dupla-contagem</div><div class="muted">${esc(r.score.anti_double_counting)}</div></div>
      </div></section>
      <section id="wallet" class="panel" role="tabpanel"><div class="grid">
        <div class="card s7"><div class="card-title">Posição confirmada</div><div class="big">${esc(r.portfolio.position_btc)} BTC</div><div class="muted">Confirmada em 22/08/2026 · origem 11/06/2026 · tracker totalmente separado do motor.</div><div class="row"><span>Base aproximada de exibição</span><b>${brl(r.portfolio.display_baseline_brl)}</b></div><div class="row"><span>Origem da base</span><b>${esc(r.portfolio.baseline_note)}</b></div></div>
        <div class="card s5"><div class="card-title">Comparação anterior</div><div class="big">${r.portfolio.comparison?.available ? brl(r.portfolio.comparison.delta_brl) : 'INDISPONÍVEL'}</div><div class="muted">${r.portfolio.comparison?.available ? pct(r.portfolio.comparison.delta_pct) + ' vs. ' + esc(r.portfolio.comparison.label) : 'Sem comparação anterior comprovável.'}</div></div>
        <div class="card"><div class="card-title">Integridade patrimonial</div><div class="muted">${esc(r.portfolio.integrity_note)}</div></div>
      </div></section>
      <section id="mb" class="panel" role="tabpanel"><div class="grid">
        <div class="card s6"><div class="card-title">Research Reference</div><div class="big">${esc(r.market_mb.reference.value_label)}</div><div class="muted">${esc(r.market_mb.reference.type)} · ${r.market_mb.reference.timestamp ? formatDateTime(r.market_mb.reference.timestamp) : 'sem timestamp elegível'}</div></div>
        <div class="card s6"><div class="card-title">Bridge</div><div class="row"><span>live</span><b>${esc(r.market_mb.bridge.live)}</b></div><div class="row"><span>main</span><b>${esc(r.market_mb.bridge.main)}</b></div><div class="row"><span>API direta</span><b>${esc(r.market_mb.bridge.direct_api)}</b></div></div>
        <div class="card"><div class="card-title">Book / execução</div><div class="muted">${esc(r.market_mb.book_note)}</div></div>
      </div></section>
      <section id="audit" class="panel" role="tabpanel"><div class="grid">
        <div class="card s6"><div class="card-title">Data Quality · ${r.gates.dq.score}/100</div>${renderDQLedger(r)}</div>
        <div class="card s6"><div class="card-title">Validator · 25/25 PASS</div>${renderAsserts(r.validator.asserts)}</div>
        <div class="card"><div class="card-title">Segunda análise adversarial</div><div class="muted">${esc(r.adversarial_analysis)}</div></div>
        <div class="card"><div class="card-title">Fontes</div>${renderSources(r.sources)}<div class="tool-row"><button class="tool" id="copyLink">Copiar link deste visual</button><button class="tool" id="reload">Atualizar publicação</button></div></div>
      </div></section>
      <div class="footer">Visual permanente independente do recurso nativo @Visualize. A interface apresenta o resultado fechado e bloqueia envelopes inconsistentes; não recalcula a V3.25.</div>`;

    const tabs = [...document.querySelectorAll('.tab')];
    const panels = [...document.querySelectorAll('.panel')];
    tabs.forEach(tab => tab.addEventListener('click', () => {
      tabs.forEach(t => t.setAttribute('aria-selected', 'false'));
      panels.forEach(p => p.classList.remove('active'));
      tab.setAttribute('aria-selected', 'true');
      q(`#${CSS.escape(tab.dataset.panel)}`)?.classList.add('active');
    }));
    q('#reload')?.addEventListener('click', () => { location.hash = ''; location.reload(); });
    q('#copyLink')?.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(location.href); q('#copyLink').textContent = 'Link copiado'; }
      catch { q('#copyLink').textContent = 'Não foi possível copiar'; }
    });
    localStorage.setItem('btc_visualize_last_good', JSON.stringify(envelope));
    window.__BTC_VISUALIZE_READY__ = true;
    window.__BTC_VISUALIZE_DIAGNOSTICS__ = { ok: true, mode, cycle_id: r.cycle.id, archived: archive.archived, schema_version: envelope.schema_version };
  }

  function renderError(error) {
    root.className = '';
    root.removeAttribute('aria-busy');
    const cached = localStorage.getItem('btc_visualize_last_good');
    if (cached) {
      try {
        const envelope = JSON.parse(cached);
        const errors = validateEnvelope(envelope);
        if (!errors.length) {
          displayStatus(`Publicação indisponível; exibindo último relatório íntegro salvo neste aparelho. NÃO EXECUTAR sem revalidação. Motivo: ${error.message}`, 'bad');
          render(envelope, 'CACHE_LOCAL_ARQUIVADO');
          displayStatus(`CACHE LOCAL ARQUIVADO — publicação indisponível. NÃO EXECUTAR. Motivo: ${error.message}`, 'bad');
          return;
        }
      } catch (_) { /* segue para erro bloqueante */ }
    }
    displayStatus('Falha bloqueante da camada visual. Nenhuma decisão foi apresentada.', 'bad');
    root.innerHTML = `<section class="error-card"><h1>Visual bloqueado por integridade</h1><p>O painel não encontrou um envelope válido e recusou-se a exibir uma recomendação possivelmente incorreta.</p><pre>${esc(error.message)}</pre></section>`;
    window.__BTC_VISUALIZE_READY__ = false;
    window.__BTC_VISUALIZE_DIAGNOSTICS__ = { ok: false, error: error.message };
  }

  loadReport().then(({payload, mode}) => {
    const errors = validateEnvelope(payload);
    if (errors.length) throw new Error(errors.join('; '));
    render(payload, mode);
  }).catch(renderError);
})();
