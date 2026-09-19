/* abtract landing page: /api/models, /api/demo-url, /api/jobs -> POST /api/jobs -> /jobs/{id}. */
(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const AGENTS = [
    ['text', 'Text', 'plain HTTP, no JavaScript'],
    ['dom', 'DOM', 'real browser, accessibility tree'],
    ['vision', 'Vision', 'real browser, screenshots'],
  ];

  function el(tag, attrs = {}, ...children) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') e.className = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (v === true) e.setAttribute(k, '');
      else e.setAttribute(k, v);
    }
    for (const c of children.flat(Infinity)) {
      if (c == null || c === false) continue;
      e.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return e;
  }

  async function api(path, opts) {
    const r = await fetch(path, { cache: 'no-store', ...opts });
    let body = null;
    try { body = await r.json(); } catch (_) { /* not json */ }
    if (!r.ok) throw new Error((body && (body.error || body.detail)) ? String(body.error || JSON.stringify(body.detail)) : `${r.status} ${r.statusText}`);
    return body;
  }

  const fmtPrice = v => v == null ? '–' : (v >= 10 ? `$${v.toFixed(0)}` : `$${v.toFixed(2)}`);
  function ago(ts) {
    if (!ts) return '';
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 45) return 'just now';
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 86400) return `${Math.round(s / 3600)} h ago`;
    if (s < 7 * 86400) return `${Math.round(s / 86400)} d ago`;
    return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
  function setStatus(msg, isErr = false) {
    const s = $('#form-status');
    s.textContent = msg || '';
    s.classList.toggle('err', !!isErr);
  }

  // ---------------------------------------------------------------- options
  function modelRow(m) {
    const price = m.provider === 'mock' ? 'free · no API keys' : `${fmtPrice(m.input_price_per_m)} in / ${fmtPrice(m.output_price_per_m)} out per M tok`;
    return el('label', { class: 'check-row', title: m.id },
      el('input', { type: 'checkbox', name: 'model', value: m.id, checked: !!m.default }),
      el('span', { class: 'name' }, m.display_name || m.id, ' ',
        m.supports_vision ? el('span', { class: 'badge' }, 'vision') : null,
        m.provider === 'mock' ? el('span', { class: 'badge mock' }, 'offline') : null),
      el('span', { class: 'price' }, price));
  }

  function renderModels(models) {
    const box = $('#models');
    box.innerHTML = '';
    const online = models.filter(m => m.provider !== 'mock');
    const offline = models.filter(m => m.provider === 'mock');
    for (const m of online) box.append(modelRow(m));
    if (offline.length) {
      box.append(el('div', { class: 'divider' }, 'offline'));
      for (const m of offline) box.append(modelRow(m));
    }
    if (!models.length) box.append(el('span', { class: 'muted' }, 'no models in the registry'));
    box.addEventListener('change', updateSummary);
  }

  function renderAgents() {
    const box = $('#agents');
    box.innerHTML = '';
    for (const [id, name, desc] of AGENTS) {
      box.append(el('label', { class: 'check-row' },
        el('input', { type: 'checkbox', name: 'agent', value: id, checked: true }),
        el('span', { class: 'name' }, name, ' ', el('span', { class: 'desc' }, desc))));
    }
    box.addEventListener('change', updateSummary);
  }

  const checked = name => [...document.querySelectorAll(`input[name="${name}"]:checked`)].map(i => i.value);
  function updateSummary() {
    const m = checked('model').length, a = checked('agent').length;
    $('#options-sub').textContent = `${m} model${m === 1 ? '' : 's'} × ${a} agent kind${a === 1 ? '' : 's'}`;
  }

  // ---------------------------------------------------------------- recent jobs
  function jobTarget(j) {
    if (j.url) return j.url.replace(/^https?:\/\//, '');
    if (j.site_id) return `${j.site_id}/${j.site_version || ''}`;
    return j.id;
  }
  async function loadJobs() {
    const box = $('#jobs');
    let jobs;
    try { jobs = await api('/api/jobs?limit=12'); }
    catch (e) { box.innerHTML = ''; box.append(el('div', { class: 'empty' }, `could not load jobs: ${e.message}`)); return; }
    box.innerHTML = '';
    if (!jobs.length) { box.append(el('div', { class: 'empty' }, 'No jobs yet. Paste a URL above or try the demo site.')); return; }
    for (const j of jobs) {
      const status = j.status || 'queued';
      const label = status === 'running' && j.phase ? `${j.phase}` : status;
      box.append(el('a', { class: 'job-row', href: `/jobs/${encodeURIComponent(j.id)}` },
        el('span', { class: 'target', title: j.url || j.id }, jobTarget(j)),
        el('span', { class: 'type' }, j.type === 'loop' ? `loop ×${j.iterations || 1}` : 'intake'),
        el('span', { class: 'when' }, ago(j.created_at)),
        el('span', { class: `pill ${status}`, title: j.error || j.phase || '' }, label)));
    }
  }

  // ---------------------------------------------------------------- submit
  let demoUrl = null;
  async function loadDemoUrl() {
    try { demoUrl = (await api('/api/demo-url')).url || null; } catch (_) { demoUrl = null; }
    $('#demo').disabled = !demoUrl;
    if (!demoUrl) $('#demo').title = 'demo site URL unavailable';
  }

  async function submit(ev) {
    ev.preventDefault();
    const url = $('#url').value.trim();
    if (!url) { setStatus('Paste a URL first.', true); $('#url').focus(); return; }
    const model_ids = checked('model');
    const agent_kinds = checked('agent');
    if (!model_ids.length) { setStatus('Pick at least one model.', true); $('#options').open = true; return; }
    if (!agent_kinds.length) { setStatus('Pick at least one agent kind.', true); $('#options').open = true; return; }
    const go = $('#go');
    go.disabled = true;
    setStatus('Starting job…');
    try {
      const res = await api('/api/jobs', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'intake', url, model_ids, agent_kinds }),
      });
      setStatus('Job started, opening progress…');
      location.href = `/jobs/${encodeURIComponent(res.job_id)}`;
    } catch (e) {
      setStatus(e.message, true);
      go.disabled = false;
    }
  }

  // ---------------------------------------------------------------- wiring
  $('#intake').addEventListener('submit', submit);
  $('#demo').addEventListener('click', () => {
    if (!demoUrl) return;
    $('#url').value = demoUrl;
    $('#url').focus();
    setStatus('Demo site loaded: a fake GPU-cloud landing page with 10 deliberate agent traps.');
  });
  $('#url').addEventListener('input', () => setStatus(''));

  renderAgents();
  updateSummary();
  api('/api/models').then(r => { renderModels(r.models || []); updateSummary(); })
    .catch(e => { $('#models').innerHTML = ''; $('#models').append(el('span', { class: 'muted' }, `could not load models: ${e.message}`)); });
  loadDemoUrl();
  loadJobs();
  setInterval(loadJobs, 10000);
})();
