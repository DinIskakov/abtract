/* abtract job page: polls /api/jobs/{id} every 2s while queued/running, then renders the report from /api/runs/*. */
(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const jobId = decodeURIComponent((location.pathname.match(/^\/jobs\/([^/]+)/) || [])[1] || '');
  const AGENT_KINDS = ['text', 'dom', 'vision'];
  const POLL_MS = 2000;
  const state = { job: null, meta: { models: {} }, runs: {}, episodes: {}, reportKey: null, timer: null, logPinned: true };

  // ---------------------------------------------------------------- helpers
  const fmtPct = v => v == null ? '–' : `${Math.round(v * 100)}%`;
  const fmtUsd = v => v == null ? '–' : (v >= 1 ? `$${v.toFixed(2)}` : `$${v.toFixed(4)}`);
  const fmtS = v => v == null ? '–' : (v >= 60 ? `${(v / 60).toFixed(1)}m` : `${v.toFixed(1)}s`);
  const fmtNum = v => v == null ? '–' : v.toFixed(1);
  const fmtDate = ts => ts ? new Date(ts * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
  const modelName = id => (state.meta.models[id] && state.meta.models[id].display_name) || id;
  const cap = s => s ? s[0].toUpperCase() + s.slice(1) : '';

  function el(tag, attrs = {}, ...children) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') e.className = v;
      else if (k === 'html') e.innerHTML = v;
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
    if (!r.ok) {
      const err = new Error((body && (body.error || body.detail)) ? String(body.error || JSON.stringify(body.detail)) : `${r.status} ${r.statusText}`);
      err.status = r.status;
      throw err;
    }
    return body;
  }

  async function getRun(id) {
    if (!state.runs[id]) state.runs[id] = await api(`/api/runs/${encodeURIComponent(id)}`);
    return state.runs[id];
  }
  async function getEpisodes(id) {
    if (!state.episodes[id]) state.episodes[id] = await api(`/api/runs/${encodeURIComponent(id)}/episodes`);
    return state.episodes[id];
  }

  function deltaEl(base, value, kind) {
    // kind: 'pct' (absolute points, higher is better) | 'lower' (relative %, lower is better)
    if (base == null || value == null) return el('span', { class: 'delta flat' }, '–');
    const d = value - base;
    const flat = Math.abs(d) < 1e-9;
    const good = kind === 'pct' ? d > 0 : d < 0;
    const cls = flat ? 'flat' : (good ? 'good' : 'bad');
    const arrow = flat ? '' : (d > 0 ? '▲ ' : '▼ ');
    const txt = kind === 'pct' ? `${d >= 0 ? '+' : ''}${Math.round(d * 100)} pts` : (base ? `${d >= 0 ? '+' : ''}${Math.round(d / base * 100)}%` : '–');
    return el('span', { class: `delta ${cls}` }, arrow + txt);
  }

  // ---------------------------------------------------------------- tiny safe markdown (headings, lists, bold/italic/code, links, paragraphs)
  const escapeHtml = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function inline(s) {
    // s is already HTML-escaped, so only our own markup can reach the DOM
    return s
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>')
      .replace(/(^|[\s(])_([^_\n]+)_(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  }
  function markdown(text) {
    const out = [];
    let list = null, para = [];
    const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; } };
    const flushList = () => { if (list) { out.push(`</${list}>`); list = null; } };
    for (const raw of String(text || '').replace(/\r\n?/g, '\n').split('\n')) {
      const line = escapeHtml(raw.replace(/\s+$/, ''));
      if (!line.trim()) { flushPara(); flushList(); continue; }
      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { flushPara(); flushList(); out.push('<hr>'); continue; }
      const h = line.match(/^(#{1,3})\s+(.*)$/);
      if (h) { flushPara(); flushList(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); continue; }
      const li = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
      if (li) {
        flushPara();
        const kind = /^\s*\d/.test(line) ? 'ol' : 'ul';
        if (list !== kind) { flushList(); out.push(`<${kind}>`); list = kind; }
        out.push(`<li>${inline(li[1])}</li>`);
        continue;
      }
      if (list && /^\s{2,}/.test(raw)) { out[out.length - 1] = out[out.length - 1].replace(/<\/li>$/, ` ${inline(line.trim())}</li>`); continue; }
      flushList();
      para.push(line.trim());
    }
    flushPara(); flushList();
    return out.join('\n');
  }

  // ---------------------------------------------------------------- phases
  const INTAKE_STEPS = [
    { label: 'Mirroring site', re: /mirror|fetch|crawl|snapshot|import|host|download|clone/i },
    { label: 'Choosing tasks', re: /task/i },
    { label: 'Running swarm', re: /swarm|episode|agent|judg|scor/i },
    { label: 'Writing findings', re: /finding|report|writ|summar|analy/i },
  ];
  const RE_OPT = /optimi|rewrit|propos|patch|generat|new version|validat|check/i;
  const RE_SWARM = /swarm|episode|agent|judg|scor/i;
  const RE_REPORT = /finding|report|writ|summar|analy|compar/i;

  const decVersion = v => { const m = /^v(\d+)$/.exec(v || ''); return m ? `v${Math.max(0, +m[1] - 1)}` : null; };
  // The runner takes run_ids[-1] at start as the baseline (POST /api/jobs seeds it) and appends every run it produces;
  // the API tells us which one is the baseline so the produced runs can be counted.
  const producedRuns = job => job.run_ids.filter(id => id !== job.baseline_run_id);
  const hasBaselineStep = job => /\(baseline\)/i.test(job.phase || '') || (job.log || []).some(l => /swarm on \S+ \(baseline\)/i.test(l));

  function loopStartVersion(job) {
    const base = job.baseline_run_id && state.runs[job.baseline_run_id];
    if (base) return base.site_version;
    const first = producedRuns(job)[0];
    if (first && state.runs[first]) return decVersion(state.runs[first].site_version) || job.site_version;
    return job.site_version;
  }

  function stepsFor(job) {
    if (job.type !== 'loop') return INTAKE_STEPS.map(s => ({ label: s.label }));
    const start = loopStartVersion(job);
    const steps = [];
    if (hasBaselineStep(job)) steps.push({ label: start ? `Baseline swarm on ${start}` : 'Baseline swarm' });
    const produced = producedRuns(job).map(id => state.runs[id]).filter(Boolean);
    for (let i = 0; i < Math.max(1, job.iterations || 1); i++) {
      const from = i === 0 ? start : produced[i - 1]?.site_version;
      const to = produced[i]?.site_version;
      steps.push({ label: from ? `Optimizing ${from}` : `Optimizing · iteration ${i + 1}` });
      steps.push({ label: to ? `Running swarm on ${to}` : `Running swarm · iteration ${i + 1}` });
    }
    steps.push({ label: 'Writing findings' });
    return steps;
  }

  function currentStep(job, steps) {
    if (job.status === 'queued') return -1;
    if (job.status === 'done') return steps.length;
    const phase = job.phase || '';
    const last = steps.length - 1;
    if (job.type !== 'loop') {
      const idx = INTAKE_STEPS.findIndex(s => s.re.test(phase));
      if (idx >= 0) return idx;
      return job.run_ids.length ? last : 0;
    }
    const offset = hasBaselineStep(job) ? 1 : 0;
    const produced = producedRuns(job).length;
    const iterations = Math.max(1, job.iterations || 1);
    const k = Math.min(produced, iterations - 1);
    if (/\(baseline\)/i.test(phase)) return 0;
    if (RE_REPORT.test(phase) && produced >= iterations) return last;
    if (RE_SWARM.test(phase)) return Math.min(offset + 2 * k + 1, last - 1);
    if (RE_OPT.test(phase)) return Math.min(offset + 2 * k, last - 1);
    return Math.min(offset + 2 * produced, last);
  }

  // ---------------------------------------------------------------- rendering: head + progress
  function target(job) {
    if (job.url) return job.url;
    if (job.site_id) return `${job.site_id}/${job.site_version || ''}`;
    return job.id;
  }

  function renderHead(job) {
    $('#crumb-id').textContent = job.id;
    const t = $('#target');
    t.innerHTML = '';
    const text = target(job).replace(/^https?:\/\//, '');
    t.append(job.url ? el('a', { href: job.url, target: '_blank', rel: 'noopener', title: job.url }, text) : text);
    document.title = `abtract — ${text}`;
    const type = $('#type');
    type.classList.remove('hidden');
    type.textContent = job.type === 'loop' ? `optimize loop × ${job.iterations || 1}` : 'intake';
    const st = $('#status');
    st.className = `pill ${job.status}`;
    st.textContent = job.status;
    const meta = $('#meta');
    meta.innerHTML = '';
    meta.append(
      el('span', {}, `started ${fmtDate(job.created_at)}`),
      job.site_id ? el('span', {}, `site ${job.site_id}${job.site_version ? ' · ' + job.site_version : ''}`) : '',
      el('span', { title: (job.model_ids || []).join(', ') }, `${(job.model_ids || []).length} model${job.model_ids && job.model_ids.length === 1 ? '' : 's'}: ${(job.model_ids || []).map(modelName).join(', ') || '–'}`),
      el('span', {}, `agents: ${(job.agent_kinds || []).join(', ') || '–'}`),
    );
    const dash = $('#nav-dashboard');
    dash.href = job.site_id ? `/dashboard?site=${encodeURIComponent(job.site_id)}` : '/dashboard';
  }

  function renderStepper(job) {
    const box = $('#stepper');
    box.innerHTML = '';
    const steps = stepsFor(job);
    const cur = job.status === 'failed' ? Math.max(0, currentStep(job, steps)) : currentStep(job, steps);
    steps.forEach((s, i) => {
      let cls = 'pending', tick = `${i + 1}`;
      if (i < cur) { cls = 'done'; tick = '✓'; }
      else if (i === cur) {
        if (job.status === 'failed') { cls = 'failed'; tick = '✕'; }
        else if (job.status === 'running') { cls = 'active'; tick = '●'; }
      }
      box.append(el('div', { class: `step-item ${cls}`, title: s.label }, el('div', { class: 'track' }), el('div', { class: 'lbl' }, el('span', { class: 'tick' }, tick), s.label)));
    });
  }

  function renderProgress(job) {
    const phase = $('#phase');
    phase.innerHTML = '';
    const bar = $('#progress'), fill = $('#progress > i'), txt = $('#progress-text');
    const total = job.progress_total || 0, done = job.progress_done || 0;
    bar.classList.remove('indeterminate');
    if (job.status === 'queued') {
      phase.append(el('span', { class: 'spin' }), 'Queued — waiting for a worker');
      fill.style.width = '0%'; txt.textContent = '';
    } else if (job.status === 'running') {
      phase.append(el('span', { class: 'spin' }), job.phase || 'Running…');
      if (total > 0) { fill.style.width = `${Math.min(100, Math.round(done / total * 100))}%`; txt.textContent = `${done} / ${total} · ${Math.round(done / total * 100)}%`; }
      else { bar.classList.add('indeterminate'); txt.textContent = ''; }
    } else if (job.status === 'done') {
      phase.append(el('span', { style: 'color:var(--good)' }, '✓'), job.findings ? 'Done — findings below' : 'Done');
      fill.style.width = '100%'; txt.textContent = total > 0 ? `${total} / ${total}` : '';
    } else {
      phase.append(el('span', { style: 'color:var(--bad)' }, '✕'), job.phase ? `Failed during: ${job.phase}` : 'Failed');
      fill.style.width = total > 0 ? `${Math.min(100, Math.round(done / total * 100))}%` : '0%';
      fill.style.background = 'var(--bad)';
      txt.textContent = total > 0 ? `${done} / ${total}` : '';
    }
    const err = $('#error');
    err.classList.toggle('hidden', !job.error);
    err.textContent = job.error || '';

    const log = $('#log');
    const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 24;
    log.innerHTML = '';
    (job.log || []).forEach((line, i) => log.append(el('span', { class: 'ln' }, String(i + 1).padStart(3, ' ')), `${line}\n`));
    if (nearBottom || state.logPinned) log.scrollTop = log.scrollHeight;
    state.logPinned = false;
  }

  function runIdsWithBaseline(job) {
    const ids = job.run_ids.slice();
    if (job.baseline_run_id && !ids.includes(job.baseline_run_id)) ids.unshift(job.baseline_run_id);
    return ids;
  }

  async function renderRunsSoFar(job) {
    const box = $('#runs-so-far');
    const ids = runIdsWithBaseline(job);
    if (!ids.length || job.status === 'done') { box.classList.add('hidden'); return; }
    box.classList.remove('hidden');
    box.innerHTML = '';
    let loadedNew = false;
    for (const id of ids) {
      let r = null;
      try { if (!state.runs[id]) loadedNew = true; r = await getRun(id); } catch (_) { /* not written yet */ }
      const href = job.site_id ? `/dashboard?site=${encodeURIComponent(job.site_id)}` : '/dashboard';
      box.append(el('a', { class: 'run-chip', href, title: id },
        el('span', { class: 'v' }, r ? r.site_version : id),
        id === job.baseline_run_id ? el('span', { class: 'v' }, 'baseline') : null,
        r ? el('b', {}, `${fmtPct(r.overall.success_rate)} success`) : el('span', { class: 'v' }, 'summary pending'),
        r ? el('span', { class: 'v' }, `${r.overall.episodes} episodes`) : null));
    }
    if (loadedNew && job.type === 'loop') renderStepper(job); // version labels may now resolve
  }

  // ---------------------------------------------------------------- provisional results (no run cache; each job poll is a fresh snapshot)
  function renderLivePreview(job) {
    const box = $('#live-preview');
    box.classList.toggle('hidden', job.status === 'done');
    if (job.status === 'done') return;
    const p = job.live_preview;
    const key = JSON.stringify([job.status, job.phase, p, state.meta.models]);
    if (state.previewKey === key) return;
    state.previewKey = key;
    box.replaceChildren(el('div', { class: 'card-head' }, el('h2', {}, 'Initial findings'),
      el('span', { class: 'pill pending' }, job.status === 'failed' ? 'Partial results' : 'Live · preliminary')));
    const status = job.status === 'failed' ? 'The run stopped. These are the results collected before it stopped.' :
      p?.completed ? 'Results update as attempts finish. Early results may change as more agents report back.' :
      p?.total ? 'Agents are working through your tasks. The first completed attempt will appear here automatically.' :
      p?.pages_scanned ? 'We’re checking the fetched pages and preparing tasks for the agents.' :
      'We’re fetching your website. Initial checks will appear here as pages arrive.';
    box.append(el('p', { class: 'preview-note', role: 'status' }, status));
    if (!p) return;
    if (job.model_ids.length === 1 && job.model_ids[0] === 'mock') {
      box.append(el('p', { class: 'preview-note' }, 'Offline workflow test: mock results do not measure website quality.'));
    }
    box.append(el('p', { class: 'sub' }, `${p.site_version} · ${p.pages_scanned} page${p.pages_scanned === 1 ? '' : 's'} scanned`));
    if (p.total) {
      const assessed = p.passed + p.failed;
      box.append(el('div', { class: 'stat-row preview-stats' },
        stat('Completed attempts', p.completed - p.skipped, v => `${v} / ${p.total}`, 'lower', null, 'remaining attempts are still untested'),
        stat('Success so far', assessed ? p.passed / assessed : null, fmtPct, 'pct', null, `${assessed} assessed · ${p.errors} execution errors`)));
    }
    if (p.findings.length) {
      box.append(el('h3', {}, 'What completed attempts show'),
        el('ul', { class: 'preview-notes' }, ...p.findings.map(note => el('li', {}, note))));
    }
    if (p.recent.length) {
      box.append(el('h3', {}, 'Latest completed attempts'));
      const rows = el('div', { class: 'preview-attempts' });
      for (const r of p.recent) {
        const good = r.outcome === 'passed', failed = r.outcome === 'failed';
        rows.append(el('article', { class: 'preview-attempt' },
          el('div', { class: 'preview-attempt-head' },
            el('span', { class: `pill ${good ? 'ok' : failed ? 'fail' : 'pending'}` }, cap(r.outcome)),
            el('span', { class: 'sub' }, `${modelName(r.model_id)} · ${r.agent_kind}`)),
          el('div', { class: 'preview-prompt' }, r.prompt),
          r.reason ? el('div', { class: 'preview-reason' }, r.reason) : null));
      }
      box.append(rows);
    } else if (p.task_sample.length) {
      box.append(el('h3', {}, 'Tasks the agents are testing'),
        el('ul', { class: 'preview-notes' }, ...p.task_sample.map(prompt => el('li', {}, prompt))));
    }
    if (p.observations.length) {
      box.append(el('h3', {}, 'Initial page checks'),
        el('p', { class: 'sub' }, 'These checks describe fetched HTML. The swarm will test their effect on real tasks.'),
        el('ul', { class: 'preview-notes' }, ...p.observations.map(note => el('li', {}, note))));
    } else if (p.pages_scanned && !p.completed) {
      box.append(el('p', { class: 'preview-note' }, 'No potential obstacles found by the initial HTML checks yet. Agent tests may find other issues.'));
    }
  }

  // ---------------------------------------------------------------- rendering: report
  function stat(label, value, fmt, kind, before, sub) {
    const vals = el('div', { class: 'stat-vals' });
    if (before != null) vals.append(el('span', { class: 'a' }, fmt(before)), el('span', { class: 'arrow' }, '→'));
    vals.append(el('span', { class: 'b' }, fmt(value)));
    return el('div', { class: 'stat' }, el('div', { class: 'stat-label' }, label), vals,
      before != null ? deltaEl(before, value, kind) : (sub ? el('span', { class: 'sub' }, sub) : null));
  }

  function barsCard(title, blocks, nameFn, before) {
    // blocks: {key: MetricBlock}; before: optional {key: MetricBlock} from the baseline run
    const rows = Object.entries(blocks || {}).sort((x, y) => y[1].success_rate - x[1].success_rate);
    const list = el('div', { class: 'bars' });
    if (!rows.length) list.append(el('div', { class: 'empty' }, 'no data'));
    for (const [k, b] of rows) {
      const prev = before && before[k] ? before[k].success_rate : null;
      const track = el('div', { class: 'track' });
      if (prev != null) track.append(el('i', { class: 'ghost', style: `width:${Math.round(prev * 100)}%` }));
      track.append(el('i', { style: `width:${Math.round(b.success_rate * 100)}%` }));
      list.append(el('div', { class: 'bar-row', title: `${b.episodes} episodes · ${fmtNum(b.avg_steps)} steps · ${fmtS(b.avg_duration_s)} · ${fmtUsd(b.avg_cost_usd)}` },
        el('span', { class: 'k' }, nameFn(k)), track,
        el('span', { class: 'v' }, prev != null ? el('span', { class: 'prev' }, fmtPct(prev)) : null, el('b', {}, fmtPct(b.success_rate)))));
    }
    return el('section', { class: 'card' }, el('div', { class: 'card-head' }, el('h2', {}, title), before ? el('span', { class: 'sub' }, 'grey = before') : null), list);
  }

  function tasksTable(run, episodes, cmp) {
    const agents = (run.agent_kinds && run.agent_kinds.length ? run.agent_kinds : AGENT_KINDS);
    const byTask = {};
    for (const e of episodes) (byTask[e.task_id] = byTask[e.task_id] || []).push(e);
    const cmpByTask = {};
    if (cmp) for (const row of cmp.per_task) cmpByTask[row.key] = row;
    const tasks = run.tasks && run.tasks.length ? run.tasks : Object.keys(byTask).map(id => ({ id, prompt: id }));
    const table = el('table', { class: 'tbl' });
    table.append(el('thead', {}, el('tr', {},
      el('th', {}, `Task (${tasks.length})`),
      ...agents.map(a => el('th', { class: 'pf', style: 'text-align:center' }, a)),
      el('th', {}, 'Dominant failure'),
      cmp ? el('th', { class: 'num' }, `before ${cmp.a.site_version}`) : null,
      el('th', { class: 'num' }, cmp ? `after ${cmp.b.site_version}` : 'Success'),
      cmp ? el('th', { class: 'num' }, 'Δ') : null)));
    const tb = el('tbody');
    for (const t of tasks) {
      const eps = byTask[t.id] || [];
      const cells = agents.map(a => {
        const mine = eps.filter(e => e.agent_kind === a);
        const ok = mine.filter(e => e.success === true).length;
        const cls = !mine.length ? 'none' : ok === mine.length ? 'ok' : ok === 0 ? 'fail' : 'mixed';
        const title = mine.length ? mine.map(e => `${modelName(e.model_id)}: ${e.success === true ? 'pass' : e.success === false ? `fail (${e.failure_mode || '?'})` : 'not judged'}`).join('\n') : 'no episodes';
        return el('td', { class: 'pf' }, el('span', { class: `pf-cell ${cls}`, title }, mine.length ? `${ok}/${mine.length}` : '–'));
      });
      const fails = {};
      for (const e of eps) if (e.success === false) fails[e.failure_mode || 'unknown'] = (fails[e.failure_mode || 'unknown'] || 0) + 1;
      const dom = Object.entries(fails).sort((x, y) => y[1] - x[1])[0];
      const pt = run.per_task && run.per_task[t.id];
      const rate = pt ? pt.success_rate : (eps.length ? eps.filter(e => e.success === true).length / eps.length : null);
      const c = cmpByTask[t.id];
      tb.append(el('tr', {},
        el('td', { class: 'wrap', title: t.prompt }, el('div', {}, t.prompt), el('div', { class: 'task-meta' }, t.kind ? el('span', { class: 'chip' }, t.kind) : null, t.trap ? el('span', { class: 'chip trap' }, t.trap) : null)),
        ...cells,
        el('td', { class: 'fm' }, dom ? `${dom[0]} (${dom[1]})` : '—'),
        cmp ? el('td', { class: 'num' }, c && c.a ? fmtPct(c.a.success_rate) : '–') : null,
        el('td', { class: 'num' }, fmtPct(rate)),
        cmp ? el('td', { class: 'num' }, deltaEl(c && c.a ? c.a.success_rate : null, c && c.b ? c.b.success_rate : rate, 'pct')) : null,
      ));
    }
    table.append(tb);
    return el('section', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Tasks'), el('span', { class: 'sub' }, `pass / attempts per agent kind across ${(run.model_ids || []).length || '?'} models · hover a cell for per-model results`)),
      el('div', { class: 'table-wrap' }, table));
  }

  function findingsCard(job) {
    if (!job.findings) return null;
    return el('section', { class: 'card' },
      el('div', { class: 'card-head' }, el('h2', {}, 'Findings'), el('span', { class: 'sub' }, 'what tripped the agents, in plain language')),
      el('div', { class: 'md', html: markdown(job.findings) }));
  }

  async function renderReport(job) {
    const key = `${job.id}:${job.status}:${job.run_ids.join(',')}:${(job.findings || '').length}`;
    if (state.reportKey === key) return;
    state.reportKey = key;
    const box = $('#report');
    box.innerHTML = '';
    box.classList.remove('hidden');
    const lastId = job.run_ids[job.run_ids.length - 1];
    if (!lastId) {
      const f = findingsCard(job);
      box.append(f || el('section', { class: 'card' }, el('div', { class: 'empty' }, 'This job finished without producing a swarm run.')));
      return;
    }
    box.append(el('section', { class: 'card' }, el('div', { class: 'empty' }, 'Loading report…')));
    let run, episodes, cmp = null;
    try {
      [run, episodes] = await Promise.all([getRun(lastId), getEpisodes(lastId)]);
      let baseId = null;
      if (job.type === 'loop') baseId = job.baseline_run_id || (job.run_ids.length > 1 ? job.run_ids[0] : null);
      if (baseId === lastId && job.run_ids.length > 1) baseId = job.run_ids[0] !== lastId ? job.run_ids[0] : null;
      if (baseId && baseId !== lastId) {
        try { cmp = await api(`/api/compare?a=${encodeURIComponent(baseId)}&b=${encodeURIComponent(lastId)}`); } catch (_) { cmp = null; }
      }
    } catch (e) {
      box.innerHTML = '';
      box.append(el('section', { class: 'card' }, el('div', { class: 'empty' }, `could not load run ${lastId}: ${e.message}`)), findingsCard(job) || '');
      return;
    }
    box.innerHTML = '';
    if (run.model_ids.length === 1 && run.model_ids[0] === 'mock') {
      box.append(el('section', { class: 'card' }, 'Offline workflow test: the mock agents give up by default. These scores do not measure your website’s quality.'));
    }
    const O = run.overall, B = cmp ? cmp.a.overall : null;
    const headline = el('section', { class: 'card' },
      el('div', { class: 'card-head' },
        el('h2', {}, cmp ? `Before vs after · ${cmp.a.site_version} → ${cmp.b.site_version}` : `Results · ${run.site_version}`),
        el('span', { class: 'sub' }, `${O.episodes} episodes · ${(run.tasks || []).length} tasks · ${run.model_ids.length} model${run.model_ids.length === 1 ? '' : 's'} · total ${fmtUsd(O.total_cost_usd)}`)),
      el('div', { class: 'stat-row', style: 'margin-bottom:0' },
        stat('Success rate', O.success_rate, fmtPct, 'pct', B && B.success_rate, 'of all agent × model × task attempts'),
        stat('Avg steps', O.avg_steps, fmtNum, 'lower', B && B.avg_steps, 'per attempt'),
        stat('Avg time', O.avg_duration_s, fmtS, 'lower', B && B.avg_duration_s, 'per attempt'),
        stat('Avg cost', O.avg_cost_usd, fmtUsd, 'lower', B && B.avg_cost_usd, 'per attempt, list prices')));
    box.append(headline);
    box.append(el('div', { class: 'report-grid2' },
      barsCard('Success by agent kind', run.per_agent, cap, cmp ? Object.fromEntries(cmp.per_agent.filter(r => r.a).map(r => [r.key, r.a])) : null),
      barsCard('Success by model', run.per_model, modelName, cmp ? Object.fromEntries(cmp.per_model.filter(r => r.a).map(r => [r.key, r.a])) : null)));
    box.append(tasksTable(run, episodes, cmp));
    const f = findingsCard(job);
    if (f) box.append(f);
    const allIds = runIdsWithBaseline(job);
    if (job.type === 'loop' && allIds.length > 1) {
      const chips = el('div', { class: 'runs-so-far' });
      for (const id of allIds) {
        let r = null;
        try { r = await getRun(id); } catch (_) { /* ignore */ }
        chips.append(el('span', { class: 'run-chip', title: id }, el('span', { class: 'v' }, r ? r.site_version : id),
          id === job.baseline_run_id ? el('span', { class: 'v' }, 'baseline') : null, r ? el('b', {}, fmtPct(r.overall.success_rate)) : null));
      }
      box.append(el('section', { class: 'card' }, el('div', { class: 'card-head' }, el('h2', {}, 'Every iteration'), el('span', { class: 'sub' }, 'success rate per version this loop produced')), chips));
    }
    renderStepper(job);
  }

  // ---------------------------------------------------------------- CTAs
  async function startLoop(job, iterations, btn) {
    const lastId = job.run_ids[job.run_ids.length - 1];
    let run = null;
    try { run = await getRun(lastId); } catch (_) { /* fall back to the job's fields */ }
    const site_id = job.site_id || (run && run.site_id);
    const site_version = (run && run.site_version) || job.site_version;
    btn.disabled = true;
    const status = $('#cta-status');
    status.textContent = 'Starting optimize loop…'; status.classList.remove('err');
    try {
      const res = await api('/api/jobs', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'loop', url: job.url, site_id, site_version, run_id: lastId, iterations, model_ids: job.model_ids, agent_kinds: job.agent_kinds }),
      });
      location.href = `/jobs/${encodeURIComponent(res.job_id)}`;
    } catch (e) {
      status.textContent = e.message; status.classList.add('err');
      btn.disabled = false;
    }
  }

  function renderCta(job) {
    const box = $('#cta');
    box.innerHTML = '';
    const dashHref = job.site_id ? `/dashboard?site=${encodeURIComponent(job.site_id)}` : '/dashboard';
    if (job.status === 'failed') {
      box.append(el('a', { class: 'btn primary lg', href: '/' }, 'Try again'),
        job.site_id ? el('a', { class: 'btn lg', href: dashHref }, 'Open full dashboard') : '',
        el('span', { class: 'spacer' }), el('span', { class: 'sub' }, 'The log above has the details.'));
      return;
    }
    if (job.status !== 'done') {
      box.append(job.site_id ? el('a', { class: 'btn', href: dashHref }, 'Open full dashboard') : '',
        el('span', { class: 'spacer' }), el('span', { class: 'sub' }, 'This page refreshes every 2 seconds. You can leave and come back.'));
      return;
    }
    const hasRun = job.run_ids.length > 0;
    if (hasRun) {
      const sel = el('select', { id: 'iterations', 'aria-label': 'iterations' }, ...[1, 2, 3].map(n => el('option', { value: n, selected: n === 1 }, `${n} iteration${n === 1 ? '' : 's'}`)));
      const btn = el('button', { class: 'btn primary lg', onclick: () => startLoop(job, Number(sel.value), btn) }, job.type === 'loop' ? 'Optimize again' : 'Optimize in a loop');
      box.append(btn, el('label', {}, 'for', sel));
    }
    box.append(el('a', { class: 'btn lg', href: dashHref }, 'Open full dashboard'), el('a', { class: 'btn lg ghost', href: '/' }, 'New run'),
      el('span', { class: 'spacer' }), el('span', { id: 'cta-status', class: 'form-status' }, hasRun ? 'Gemini rewrites what tripped the agents, then the swarm re-runs on the new version.' : ''));
  }

  // ---------------------------------------------------------------- polling
  function render(job) {
    renderHead(job);
    renderStepper(job);
    renderProgress(job);
    renderRunsSoFar(job);
    renderCta(job);
    renderLivePreview(job);
    if (job.status === 'done') renderReport(job);
    else $('#report').classList.add('hidden');
  }

  async function poll() {
    let job;
    try { job = await api(`/api/jobs/${encodeURIComponent(jobId)}`); }
    catch (e) {
      if (e.status === 404) { $('#body').classList.add('hidden'); $('#notfound').classList.remove('hidden'); $('#status').textContent = 'missing'; $('#status').className = 'pill failed'; $('#target').textContent = jobId; return; }
      $('#status').textContent = 'reconnecting…';
      state.timer = setTimeout(poll, POLL_MS * 2);
      return;
    }
    state.job = job;
    render(job);
    if (job.status === 'queued' || job.status === 'running') state.timer = setTimeout(poll, POLL_MS);
  }

  $('#crumb-id').textContent = jobId;
  api('/api/meta').then(m => { state.meta = m; if (state.job) render(state.job); }).catch(() => { /* names fall back to ids */ });
  poll();
})();
