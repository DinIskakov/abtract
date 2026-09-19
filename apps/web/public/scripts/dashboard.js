/* eslint-disable @typescript-eslint/no-unused-vars */
/* abtract dashboard browser behavior; talks to the product routes under /api/*. */
(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const state = {
    overview: null, meta: { models: {}, agent_kinds: ['text', 'dom', 'vision'] },
    siteId: null, site: null, runs: [], charts: {},
    runId: null, run: null, episodes: [], runA: null, runB: null, liveTimer: null,
    seq: { compare: 0, run: 0, episode: 0 },
  };

  // ---------------------------------------------------------------- helpers
  const fmtPct = v => v == null ? '–' : `${Math.round(v * 100)}%`;
  const fmtUsd = v => v == null ? '–' : (v >= 1 ? `$${v.toFixed(2)}` : `$${v.toFixed(4)}`);
  const fmtS = v => v == null ? '–' : (v >= 60 ? `${(v / 60).toFixed(1)}m` : `${v.toFixed(1)}s`);
  const fmtNum = v => v == null ? '–' : v.toFixed(1);
  const fmtDate = ts => ts ? new Date(ts * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
  const modelName = id => (state.meta.models[id] && state.meta.models[id].display_name) || id;
  const shortModel = id => modelName(id);

  function el(tag, attrs = {}, ...children) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null) continue;
      if (k === 'class') e.className = v;
      else if (k === 'html') e.innerHTML = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v);
    }
    for (const c of children.flat(Infinity)) {
      if (c == null || c === false) continue;
      e.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return e;
  }

  async function api(path) {
    const r = await fetch(path, { cache: 'no-store' });
    if (!r.ok) {
      let msg = `${r.status}`;
      try { msg = (await r.json()).error || msg; } catch (_) { /* ignore */ }
      throw new Error(`${path} -> ${msg}`);
    }
    return r.json();
  }
  async function apiText(path) {
    const r = await fetch(path, { cache: 'no-store' });
    if (!r.ok) throw new Error(`${path} -> ${r.status}`);
    return r.text();
  }

  function setStatus(msg, isErr = false) {
    const s = $('#status');
    s.textContent = msg;
    s.classList.toggle('err', isErr);
  }

  function deltaEl(delta, kind) {
    // kind: 'pct' (success rate, absolute pts, higher is better) | 'lower' (relative %, lower is better)
    if (delta == null || delta.base == null || delta.value == null) return el('span', { class: 'delta flat' }, '–');
    const d = delta.value - delta.base;
    const higherIsBetter = kind === 'pct';
    const flat = Math.abs(d) < 1e-9;
    const good = higherIsBetter ? d > 0 : d < 0;
    const cls = flat ? 'flat' : (good ? 'good' : 'bad');
    const arrow = flat ? '' : (d > 0 ? '▲ ' : '▼ ');
    const txt = kind === 'pct'
      ? `${d >= 0 ? '+' : ''}${Math.round(d * 100)} pts`
      : (delta.base ? `${d >= 0 ? '+' : ''}${Math.round(d / delta.base * 100)}%` : '–');
    return el('span', { class: `delta ${cls}` }, arrow + txt);
  }

  function latestRun(runs) {
    if (!runs || !runs.length) return null;
    return runs.slice().sort((a, b) => (a.created_at || 0) - (b.created_at || 0))[runs.length - 1];
  }

  function runLabel(r) {
    const ok = r.overall ? ` · ${fmtPct(r.overall.success_rate)}` : '';
    return `${r.site_version} · ${r.run_id}${ok}`;
  }

  function fillSelect(sel, options, value) {
    sel.innerHTML = '';
    for (const [v, label] of options) sel.append(el('option', { value: v }, label));
    if (value != null && options.some(o => o[0] === value)) sel.value = value;
  }

  // ---------------------------------------------------------------- charts
  function barChart(canvasId, labels, data, fmt, opts = {}) {
    if (typeof Chart === 'undefined') return;
    const canvas = $('#' + canvasId);
    if (state.charts[canvasId]) state.charts[canvasId].destroy();
    const css = getComputedStyle(document.documentElement);
    const color = token => css.getPropertyValue(token).trim();
    Chart.defaults.color = color('--muted');
    Chart.defaults.font.family = 'Arial, Helvetica, sans-serif';
    Chart.defaults.font.size = 14;
    canvas.setAttribute('aria-label', labels.map((label, i) => `${label}: ${fmt(data[i])}`).join('; ') || 'No results yet');
    const last = data.length - 1;
    state.charts[canvasId] = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          data,
          borderColor: color('--blue'), backgroundColor: color('--blue-soft'),
          borderWidth: 2, pointRadius: data.map((_, i) => i === last ? 4 : 3),
          pointBackgroundColor: color('--blue'), pointHoverRadius: 6, tension: 0, fill: true,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: { duration: matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 250 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: color('--ink'), titleColor: color('--surface'), bodyColor: color('--surface'), borderColor: color('--border'), borderWidth: 1,
            callbacks: { label: c => ` ${fmt(c.parsed.y)}` },
          },
        },
        scales: {
          x: { grid: { display: false }, border: { color: color('--axis') }, ticks: { color: color('--muted') } },
          y: {
            beginAtZero: true, max: opts.max, grid: { color: color('--grid') }, border: { display: false },
            ticks: { callback: v => fmt(v), maxTicksLimit: 5, color: color('--muted') },
          },
        },
      },
    });
  }

  function hero(id, label, values, versions, fmt, kind) {
    const box = $('#' + id);
    box.innerHTML = '';
    const idx = values.map((v, i) => v == null ? -1 : i).filter(i => i >= 0);
    if (!idx.length) { box.append(el('span', { class: 'val' }, '–')); return; }
    const li = idx[idx.length - 1];
    const pi = idx.length > 1 ? idx[idx.length - 2] : -1;
    box.append(el('span', { class: 'val' }, fmt(values[li])), el('span', { class: 'ver' }, versions[li]));
    if (pi >= 0) box.append(deltaEl({ base: values[pi], value: values[li] }, kind), el('span', { class: 'ver' }, `vs ${versions[pi]}`));
  }

  function renderTimeline() {
    const site = state.site;
    const versions = site ? site.versions : [];
    const labels = versions.map(v => v.version);
    const latest = versions.map(v => latestRun(v.runs));
    const succ = latest.map(r => r ? r.overall.success_rate : null);
    const cost = latest.map(r => r ? r.overall.avg_cost_usd : null);
    const time = latest.map(r => r ? r.overall.avg_duration_s : null);
    barChart('chart-success', labels, succ, fmtPct, { max: 1 });
    barChart('chart-cost', labels, cost, fmtUsd);
    barChart('chart-time', labels, time, fmtS);
    hero('hero-success', 'Success', succ, labels, fmtPct, 'pct');
    hero('hero-cost', 'Cost', cost, labels, fmtUsd, 'lower');
    hero('hero-time', 'Time', time, labels, fmtS, 'lower');
    const nRuns = versions.reduce((n, v) => n + v.runs.length, 0);
    $('#timeline-sub').textContent = site ? `${versions.length} version${versions.length === 1 ? '' : 's'}, ${nRuns} run${nRuns === 1 ? '' : 's'} · latest run per version` : 'no sites yet';
  }

  // ---------------------------------------------------------------- A vs B
  async function renderCompare() {
    const cards = $('#compare-cards');
    const table = $('#compare-tasks');
    const seq = ++state.seq.compare;
    if (!state.runA || !state.runB) { cards.innerHTML = ''; table.innerHTML = ''; cards.append(el('div', { class: 'empty' }, 'Pick two runs to compare.')); return; }
    let cmp;
    try { cmp = await api(`/api/compare?a=${encodeURIComponent(state.runA)}&b=${encodeURIComponent(state.runB)}`); }
    catch (e) { if (seq !== state.seq.compare) return; cards.innerHTML = ''; table.innerHTML = ''; cards.append(el('div', { class: 'empty' }, `compare failed: ${e.message}`)); return; }
    if (seq !== state.seq.compare) return; // a newer selection superseded this request
    cards.innerHTML = ''; table.innerHTML = '';
    const A = cmp.a.overall, B = cmp.b.overall;
    const stat = (label, a, b, fmt, kind) => el('div', { class: 'stat' },
      el('div', { class: 'stat-label' }, label),
      el('div', { class: 'stat-vals' }, el('span', { class: 'a' }, fmt(a)), el('span', { class: 'arrow' }, '→'), el('span', { class: 'b' }, fmt(b))),
      deltaEl({ base: a, value: b }, kind));
    cards.append(
      stat('Success rate', A.success_rate, B.success_rate, fmtPct, 'pct'),
      stat('Avg steps', A.avg_steps, B.avg_steps, fmtNum, 'lower'),
      stat('Avg time', A.avg_duration_s, B.avg_duration_s, fmtS, 'lower'),
      stat('Avg cost', A.avg_cost_usd, B.avg_cost_usd, fmtUsd, 'lower'),
    );
    table.append(el('thead', {}, el('tr', {},
      el('th', {}, 'Task'), el('th', {}, 'Trap'),
      el('th', { class: 'num' }, `A ${cmp.a.site_version}`), el('th', { class: 'num' }, `B ${cmp.b.site_version}`), el('th', { class: 'num' }, 'Δ success'),
      el('th', { class: 'num' }, 'A steps'), el('th', { class: 'num' }, 'B steps'), el('th', { class: 'num' }, 'A cost'), el('th', { class: 'num' }, 'B cost'))));
    const tb = el('tbody');
    for (const row of cmp.per_task) {
      const a = row.a, b = row.b;
      tb.append(el('tr', {},
        el('td', { class: 'wrap', title: row.prompt }, row.prompt),
        el('td', {}, row.trap ? el('span', { class: 'chip trap' }, row.trap) : ''),
        el('td', { class: 'num' }, a ? fmtPct(a.success_rate) : '–'),
        el('td', { class: 'num' }, b ? fmtPct(b.success_rate) : '–'),
        el('td', { class: 'num' }, deltaEl({ base: a && a.success_rate, value: b && b.success_rate }, 'pct')),
        el('td', { class: 'num' }, a ? fmtNum(a.avg_steps) : '–'),
        el('td', { class: 'num' }, b ? fmtNum(b.avg_steps) : '–'),
        el('td', { class: 'num' }, a ? fmtUsd(a.avg_cost_usd) : '–'),
        el('td', { class: 'num' }, b ? fmtUsd(b.avg_cost_usd) : '–'),
      ));
    }
    table.append(tb);
  }

  // ---------------------------------------------------------------- run detail
  function renderHeatmap() {
    const table = $('#heatmap');
    table.innerHTML = '';
    const run = state.run;
    if (!run) { table.append(el('tbody', {}, el('tr', {}, el('td', { class: 'empty' }, 'No run selected.')))); return; }
    const models = run.model_ids.length ? run.model_ids : [...new Set(state.episodes.map(e => e.model_id))];
    const agents = run.agent_kinds.length ? run.agent_kinds : state.meta.agent_kinds;
    const byKey = {};
    for (const e of state.episodes) byKey[`${e.task_id}|${e.model_id}|${e.agent_kind}`] = e;
    const tasks = run.tasks.length ? run.tasks : [...new Set(state.episodes.map(e => e.task_id))].map(id => ({ id, prompt: id }));
    table.append(el('thead', {}, el('tr', {}, el('th', {}, `Task (${tasks.length})`), ...models.map(m => el('th', { class: 'model', title: m }, shortModel(m))))));
    const tb = el('tbody');
    for (const t of tasks) {
      const tr = el('tr', {}, el('td', { class: 'task-cell' },
        el('div', { class: 'task-prompt', title: t.prompt }, t.prompt),
        el('div', { class: 'task-meta' }, el('span', { class: 'chip' }, t.kind || 'task'), t.trap ? el('span', { class: 'chip trap' }, t.trap) : null)));
      for (const m of models) {
        const segs = el('div', { class: 'segs' });
        for (const a of agents) {
          const e = byKey[`${t.id}|${m}|${a}`];
          const cls = !e ? 'none' : e.success === true ? 'ok' : e.success === false ? 'fail' : 'pending';
          const outcome = !e ? 'no episode' : e.success === true ? 'success' : e.success === false ? `failed (${e.failure_mode || '?'})` : 'not judged';
          const title = e ? `${modelName(m)} · ${a} agent · ${outcome} · ${e.n_steps} steps · ${fmtS(e.duration_s)} · ${fmtUsd(e.cost_usd)}` : `${a} agent: no episode`;
          const seg = el('button', { type: 'button', class: `seg ${cls}`, title, 'aria-label': title, disabled: e ? null : '' }, a[0].toUpperCase());
          if (e) {
            seg.addEventListener('click', () => openEpisode(run.run_id, e.id));
          }
          segs.append(seg);
        }
        tr.append(el('td', { class: 'hm-cell' }, segs));
      }
      tb.append(tr);
    }
    table.append(tb);
  }

  function blockTable(tableId, blocks, nameFn = k => k) {
    const table = $('#' + tableId);
    table.innerHTML = '';
    const rows = Object.entries(blocks || {}).sort((x, y) => y[1].success_rate - x[1].success_rate);
    if (!rows.length) { table.append(el('tbody', {}, el('tr', {}, el('td', { class: 'empty' }, 'no data')))); return; }
    table.append(el('thead', {}, el('tr', {},
      el('th', {}, ''), el('th', { class: 'num' }, 'n'), el('th', {}, 'success'), el('th', { class: 'num' }, 'steps'),
      el('th', { class: 'num' }, 'time'), el('th', { class: 'num' }, 'cost'), el('th', {}, 'failures'))));
    const tb = el('tbody');
    for (const [k, b] of rows) {
      const fm = Object.entries(b.failure_modes || {}).sort((x, y) => y[1] - x[1]).map(([m, n]) => `${m} ${n}`).join(', ');
      tb.append(el('tr', {},
        el('td', { class: 'name', title: k }, nameFn(k)),
        el('td', { class: 'num' }, b.episodes),
        el('td', {}, el('span', { class: 'bar' }, el('i', { style: `width:${Math.max(2, Math.round(b.success_rate * 80))}px` }), el('b', {}, fmtPct(b.success_rate)))),
        el('td', { class: 'num' }, fmtNum(b.avg_steps)),
        el('td', { class: 'num' }, fmtS(b.avg_duration_s)),
        el('td', { class: 'num' }, fmtUsd(b.avg_cost_usd)),
        el('td', { class: 'fm', title: fm }, fm || '—'),
      ));
    }
    table.append(tb);
  }

  function renderBreakdown() {
    const run = state.run;
    blockTable('tbl-model', run ? run.per_model : {}, modelName);
    blockTable('tbl-agent', run ? run.per_agent : {});
    blockTable('tbl-trap', run ? run.per_trap : {});
    $('#breakdown-sub').textContent = run ? `${run.run_id} · ${run.overall.episodes} episodes · total ${fmtUsd(run.overall.total_cost_usd)}` : '';
  }

  async function selectRun(runId) {
    state.runId = runId;
    const seq = ++state.seq.run;
    if (!runId) { state.run = null; state.episodes = []; renderHeatmap(); renderBreakdown(); return; }
    let run, episodes;
    try {
      [run, episodes] = await Promise.all([api(`/api/runs/${encodeURIComponent(runId)}`), api(`/api/runs/${encodeURIComponent(runId)}/episodes`)]);
    } catch (e) { if (seq === state.seq.run) setStatus(e.message, true); return; }
    if (seq !== state.seq.run) return; // superseded by a newer selection
    state.run = run; state.episodes = episodes;
    const r = state.run;
    $('#run-meta').textContent = `${r.site_id}/${r.site_version} · ${fmtDate(r.created_at)} · ${state.episodes.length} episodes · ${fmtPct(r.overall.success_rate)} success`;
    renderHeatmap();
    renderBreakdown();
  }

  // ---------------------------------------------------------------- episode drawer
  function actionText(a) {
    if (!a) return '';
    const parts = Object.entries(a).filter(([k, v]) => k !== 'type' && v != null).map(([k, v]) => `${k}: ${JSON.stringify(v)}`);
    return parts.join('  ');
  }

  function lightbox(src) {
    const lb = el('div', { class: 'lightbox', onclick: () => lb.remove() }, el('img', { src, alt: 'screenshot' }));
    document.body.append(lb);
  }

  async function openEpisode(runId, epId) {
    const body = $('#drawer-body'), title = $('#drawer-title');
    body.innerHTML = ''; title.innerHTML = '';
    title.append('Loading…');
    showDrawer(true);
    const seq = ++state.seq.episode;
    let ep;
    try { ep = await api(`/api/runs/${encodeURIComponent(runId)}/episodes/${encodeURIComponent(epId)}`); }
    catch (e) { if (seq === state.seq.episode) { title.textContent = 'Failed to load episode'; body.append(el('div', { class: 'empty' }, e.message)); } return; }
    if (seq !== state.seq.episode) return;
    const task = (state.run && state.run.tasks || []).find(t => t.id === ep.task_id) || { id: ep.task_id, prompt: ep.task_id };
    const outcome = ep.success === true ? 'ok' : ep.success === false ? 'fail' : 'pending';
    const outcomeText = ep.success === true ? 'success' : ep.success === false ? `failed · ${ep.failure_mode || 'unknown'}` : 'not judged';
    title.innerHTML = '';
    title.append(el('div', {}, `${modelName(ep.model_id)} · ${ep.agent_kind} agent`),
      el('div', { class: 'meta' }, `${ep.id} · ${ep.site_id}/${ep.site_version} · ${fmtDate(ep.started_at)}`));
    const u = ep.usage || {};
    body.append(el('div', { class: 'ep-summary' },
      el('div', { class: 'prompt' }, task.prompt),
      el('div', { class: 'row' }, el('span', { class: 'k' }, 'outcome'), el('span', { class: `pill ${outcome}` }, outcomeText)),
      ep.judge_reason ? el('div', { class: 'row' }, el('span', { class: 'k' }, 'judge'), el('span', { class: 'v' }, ep.judge_reason)) : null,
      task.expected_answer ? el('div', { class: 'row' }, el('span', { class: 'k' }, 'expected'), el('span', { class: 'v' }, task.expected_answer)) : null,
      ep.final_answer ? el('div', { class: 'row' }, el('span', { class: 'k' }, 'final answer'), el('span', { class: 'v' }, ep.final_answer)) : null,
      ep.final_url ? el('div', { class: 'row' }, el('span', { class: 'k' }, 'final url'), el('a', { class: 'v', href: ep.final_url, target: '_blank', rel: 'noopener' }, ep.final_url)) : null,
      ep.error ? el('div', { class: 'row' }, el('span', { class: 'k' }, 'error'), el('span', { class: 'v', style: 'color:var(--bad)' }, ep.error)) : null,
      el('div', { class: 'row' }, el('span', { class: 'k' }, 'usage'), el('span', { class: 'v' },
        `${ep.n_steps} steps · ${fmtS(ep.duration_s)} · ${fmtUsd(ep.cost_usd)} · ${(u.input_tokens || 0).toLocaleString()} in / ${(u.output_tokens || 0).toLocaleString()} out tokens · ${u.llm_calls || 0} LLM calls`)),
      task.trap ? el('div', { class: 'row' }, el('span', { class: 'k' }, 'trap'), el('span', { class: 'chip trap' }, task.trap)) : null,
    ));
    const steps = el('div', { class: 'steps' });
    for (const s of ep.steps || []) {
      const main = el('div', { class: 'step-main' },
        el('div', { class: 'step-head' }, el('span', { class: 'idx' }, `#${s.index + 1}`), el('span', { class: 'url', title: s.url }, s.url), el('span', {}, `${s.latency_ms} ms`), s.observation_chars ? el('span', {}, `${s.observation_chars.toLocaleString()} chars seen`) : null),
        s.thought ? el('div', { class: 'step-thought' }, s.thought) : null,
        el('pre', { class: 'step-action' }, el('span', { class: 't' }, s.action ? s.action.type : '?'), '  ', actionText(s.action)),
        s.error ? el('div', { class: 'step-error' }, s.error) : null,
      );
      const step = el('div', { class: `step${s.error ? ' err' : ''}` }, main);
      if (s.screenshot_url) step.append(el('img', { class: 'thumb', src: s.screenshot_url, loading: 'lazy', alt: `step ${s.index + 1} screenshot`, onclick: () => lightbox(s.screenshot_url) }));
      steps.append(step);
    }
    if (!(ep.steps || []).length) steps.append(el('div', { class: 'empty' }, 'No steps recorded.'));
    body.append(el('h3', { style: 'margin:10px 0 8px' }, `Trace (${(ep.steps || []).length} steps)`), steps);
  }

  let drawerTrigger = null;
  function showDrawer(on) {
    const wasOpen = !$('#drawer').classList.contains('hidden');
    if (on && !wasOpen) drawerTrigger = document.activeElement;
    $('#drawer').classList.toggle('hidden', !on);
    $('#drawer-backdrop').classList.toggle('hidden', !on);
    document.body.style.overflow = on ? 'hidden' : '';
    if (on) $('#drawer-close').focus();
    else if (wasOpen && drawerTrigger) drawerTrigger.focus();
  }

  // ---------------------------------------------------------------- versions & file viewer
  function renderVersions() {
    const c = $('#versions');
    c.innerHTML = '';
    const site = state.site;
    if (!site || !site.versions.length) { c.append(el('div', { class: 'empty' }, 'No versions yet.')); return; }
    for (const v of site.versions.slice().reverse()) {
      const r = latestRun(v.runs);
      const files = el('div', { class: 'files' });
      for (const f of v.changed_files || []) {
        const open = () => showFile(site.site_id, v.version, f, v.parent);
        files.append(el('span', { class: 'chip file', role: 'button', tabindex: '0', title: `view ${f}`, onclick: open,
          onkeydown: ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); open(); } } }, f));
      }
      c.append(el('div', { class: 'version' },
        el('div', { class: 'version-head' },
          el('span', { class: 'v' }, v.version),
          v.parent ? el('span', { class: 'parent' }, `← ${v.parent}`) : el('span', { class: 'parent' }, 'initial import'),
          r ? el('span', { class: `pill ${r.overall.success_rate >= 0.7 ? 'ok' : r.overall.success_rate >= 0.4 ? 'pending' : 'fail'}` }, `${fmtPct(r.overall.success_rate)} success`) : el('span', { class: 'pill pending' }, 'no runs yet'),
          el('span', { class: 'date' }, fmtDate(v.created_at))),
        v.notes ? el('details', { class: 'version-notes' }, el('summary', {}, 'Optimizer notes'), el('div', { class: 'notes' }, v.notes)) : null,
        (v.changed_files || []).length ? el('div', {}, el('span', { class: 'sub' }, `${v.changed_files.length} file${v.changed_files.length === 1 ? '' : 's'}: `), files) : null,
      ));
    }
  }

  function diffLines(a, b) {
    // Line-level LCS diff -> rows of [leftLine|null, rightLine|null, tag]. Falls back to naive pairing for big files.
    const n = a.length, m = b.length;
    if (n * m > 4_000_000) {
      const rows = [];
      for (let i = 0; i < Math.max(n, m); i++) rows.push([a[i] ?? null, b[i] ?? null, a[i] === b[i] ? '=' : '~']);
      return rows;
    }
    const dp = new Uint32Array((n + 1) * (m + 1));
    const W = m + 1;
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i * W + j] = a[i] === b[j] ? dp[(i + 1) * W + j + 1] + 1 : Math.max(dp[(i + 1) * W + j], dp[i * W + j + 1]);
    const rows = [];
    let i = 0, j = 0, dels = [], adds = [];
    const flush = () => {
      const k = Math.max(dels.length, adds.length);
      for (let x = 0; x < k; x++) rows.push([dels[x] ?? null, adds[x] ?? null, '~']);
      dels = []; adds = [];
    };
    while (i < n || j < m) {
      if (i < n && j < m && a[i] === b[j]) { flush(); rows.push([a[i], b[j], '=']); i++; j++; }
      else if (j < m && (i >= n || dp[i * W + j + 1] >= dp[(i + 1) * W + j])) { adds.push(b[j]); j++; }
      else { dels.push(a[i]); i++; }
    }
    flush();
    return rows;
  }

  async function showFile(siteId, version, path, parent) {
    const fv = $('#file-viewer');
    fv.classList.remove('hidden');
    fv.innerHTML = '';
    fv.append(el('div', { class: 'fv-head' }, el('span', {}, `loading ${path}…`)));
    const get = (v) => apiText(`/api/sites/${encodeURIComponent(siteId)}/versions/${encodeURIComponent(v)}/file?path=${encodeURIComponent(path)}`).catch(() => null);
    const [cur, prev] = await Promise.all([get(version), parent ? get(parent) : Promise.resolve(null)]);
    fv.innerHTML = '';
    const closeBtn = el('button', { class: 'btn', onclick: () => fv.classList.add('hidden') }, 'Close');
    if (cur == null) { fv.append(el('div', { class: 'fv-head' }, el('span', {}, `${path}: not a text file or missing`), closeBtn)); return; }
    const L = prev == null ? [] : prev.split('\n'), R = cur.split('\n');
    const rows = prev == null ? R.map(l => [null, l, '+']) : diffLines(L, R);
    const changed = rows.filter(r => r[2] !== '=').length;
    fv.append(el('div', { class: 'fv-head' },
      el('span', {}, `${path}`),
      el('span', { class: 'fv-cols' }, el('span', {}, prev == null ? (parent ? `${parent}: (file did not exist)` : 'no parent version') : `A: ${parent}`), el('span', {}, `B: ${version}`), el('span', {}, `${changed} changed line${changed === 1 ? '' : 's'}`)),
      closeBtn));
    const tbl = el('table', { class: 'diff' });
    let ln = 0, rn = 0;
    for (const [l, r, tag] of rows) {
      const lc = l == null ? 'blank' : (tag === '=' ? '' : 'del');
      const rc = r == null ? 'blank' : (tag === '=' ? '' : 'add');
      const lcell = el('td', { class: lc });
      const rcell = el('td', { class: rc });
      if (l != null) lcell.append(el('span', { class: 'ln' }, ++ln), l);
      if (r != null) rcell.append(el('span', { class: 'ln' }, ++rn), r);
      tbl.append(el('tr', {}, lcell, rcell));
    }
    fv.append(el('div', { class: 'fv-body' }, tbl));
    fv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // ---------------------------------------------------------------- site selection & loading
  function selectSite(siteId, { keepRuns = true } = {}) {
    const ov = state.overview;
    state.site = (ov.sites || []).find(s => s.site_id === siteId) || ov.sites[0] || null;
    state.siteId = state.site ? state.site.site_id : null;
    if (state.siteId) { const u = new URL(location.href); u.searchParams.set('site', state.siteId); history.replaceState(null, '', u); }
    state.runs = state.site ? state.site.versions.flatMap(v => v.runs).sort((a, b) => a.created_at - b.created_at) : [];
    const opts = state.runs.map(r => [r.run_id, runLabel(r)]);
    const ids = state.runs.map(r => r.run_id);
    const last = ids[ids.length - 1] || null, prev = ids[ids.length - 2] || last;
    if (!keepRuns || !ids.includes(state.runB)) state.runB = last;
    if (!keepRuns || !ids.includes(state.runA)) state.runA = prev;
    if (!keepRuns || !ids.includes(state.runId)) state.runId = last;
    fillSelect($('#run-a'), opts, state.runA);
    fillSelect($('#run-b'), opts, state.runB);
    fillSelect($('#run-select'), opts, state.runId);
    renderTimeline();
    renderVersions();
    renderCompare();
    selectRun(state.runId);
  }

  async function load({ silent = false } = {}) {
    if (!silent) setStatus('loading…');
    try {
      const [ov, meta] = await Promise.all([api('/api/overview'), api('/api/meta').catch(() => state.meta)]);
      state.overview = ov; state.meta = meta || state.meta;
    } catch (e) { setStatus(e.message, true); return; }
    const sel = $('#site-select');
    const siteIds = state.overview.sites.map(s => s.site_id);
    const wanted = state.siteId || new URLSearchParams(location.search).get('site');
    fillSelect(sel, siteIds.map(s => [s, s]), siteIds.includes(wanted) ? wanted : siteIds[0]);
    $('#empty-state').classList.toggle('hidden', siteIds.length > 0);
    document.querySelectorAll('#main > .card').forEach(card => card.classList.toggle('hidden', !siteIds.length));
    $('.workspace-nav').classList.toggle('hidden', !siteIds.length);
    sel.disabled = !siteIds.length;
    if (!siteIds.length) {
      setStatus('No experiments yet');
      state.site = null; renderTimeline(); renderVersions(); renderHeatmap(); renderBreakdown();
      return;
    }
    selectSite(sel.value);
    setStatus(`updated ${new Date().toLocaleTimeString()}`);
  }

  function setLive(on) {
    if (state.liveTimer) { clearInterval(state.liveTimer); state.liveTimer = null; }
    if (on) state.liveTimer = setInterval(() => load({ silent: true }), 15000);
  }

  // ---------------------------------------------------------------- wiring
  $('#site-select').addEventListener('change', e => selectSite(e.target.value, { keepRuns: false }));
  $('#run-a').addEventListener('change', e => { state.runA = e.target.value; renderCompare(); });
  $('#run-b').addEventListener('change', e => { state.runB = e.target.value; renderCompare(); });
  $('#run-select').addEventListener('change', e => selectRun(e.target.value));
  $('#refresh').addEventListener('click', () => load());
  $('#live').addEventListener('change', e => setLive(e.target.checked));
  $('#drawer-close').addEventListener('click', () => showDrawer(false));
  $('#drawer-backdrop').addEventListener('click', () => showDrawer(false));
  document.addEventListener('keydown', e => {
    if (e.key === 'Tab' && !$('#drawer').classList.contains('hidden')) {
      const items = [...$('#drawer').querySelectorAll('button, a[href], [tabindex="0"]')].filter(node => node.getClientRects().length);
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
    if (e.key === 'Escape') { showDrawer(false); const lb = $('.lightbox'); if (lb) lb.remove(); } });

  load();
})();
