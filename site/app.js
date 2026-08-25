/* BirdNET-PiPy adoption dashboard — renders data/dashboard.json with Chart.js in the app's visual vocabulary. */
(async function () {
  // Tailwind values as used by the app; series colours = app accents (green-600, blue-600, amber-600), validated for colour vision.
  const C = { g50: '#f9fafb', g100: '#f3f4f6', g200: '#e5e7eb', g400: '#9ca3af', g500: '#6b7280', g600: '#4b5563', g900: '#111827',
    s1: '#16a34a', s2: '#2563eb', s3: '#d97706' };
  const RAMP = ['#bbf7d0', '#86efac', '#4ade80', '#22c55e', '#16a34a', '#15803d', '#166534', '#14532d']; // green-200…900, ordinal by release age
  const fmt = (n) => (n == null ? '–' : Number(n).toLocaleString('en-US'));
  const vkey = (v) => String(v).split(/[.\-]/).map((x) => (/^\d+$/.test(x) ? +x : -1));
  const vcmp = (a, b) => { const x = vkey(a), y = vkey(b); for (let i = 0; i < Math.max(x.length, y.length); i++) { const d = (x[i] ?? 0) - (y[i] ?? 0); if (d) return d; } return 0; };
  const el = (id) => document.getElementById(id);
  const charts = {};

  let data;
  try {
    data = await (await fetch('data/dashboard.json', { cache: 'no-cache' })).json();
  } catch (e) {
    el('meta').textContent = 'Failed to load data/dashboard.json.';
    return;
  }
  const { estimate: est, ghcr, ha, github: gh } = data;
  const IMAGES = ['birdnet-pipy-frontend', 'birdnet-pipy-backend', 'birdnet-pipy-icecast'];
  const short = (img) => img.replace('birdnet-pipy-', '');

  // ---- header / errors / method ------------------------------------------
  el('meta').textContent = `Last updated ${data.generated.replace('T', ' ').slice(0, 16)} UTC; ${ghcr.snapshots.length} daily snapshot${ghcr.snapshots.length === 1 ? '' : 's'} since ${ghcr.snapshots[0] || '–'}.`;
  const errs = Object.entries(data.errors || {});
  if (errs.length) { el('errors').hidden = false; el('errors').textContent = 'The last run had failures, so some sections are stale: ' + errs.map(([k, v]) => `${k} (${v})`).join('; '); }
  el('m-own').textContent = data.config.own_stations;
  el('m-window').textContent = data.config.active_window_days;
  el('footer').innerHTML = `Generated ${data.generated.replace('T', ' ').slice(0, 16)} UTC · <a href="data/dashboard.json">dashboard.json</a>`;

  // ---- headline tiles ---------------------------------------------------------
  const latestRel = ghcr.releases[ghcr.releases.length - 1];
  const tiles = [
    ['Estimated active installs', fmt(est.total.mid), `range ${fmt(est.total.low)}–${fmt(est.total.high)}`],
    ['Self-hosted stations', fmt(est.self_hosted.active), `estimate · ${fmt(est.self_hosted.not_updating)} not updating`],
    ['Home Assistant installs', fmt(est.ha.estimated), `${fmt(est.ha.reporting)} reporting · opt-in ${est.ha.opt_in_rate != null ? Math.round(est.ha.opt_in_rate * 100) + '%' : '–'}`],
    ['Latest release', latestRel ? latestRel.release : '–', latestRel ? `${fmt(latestRel.pulls)} station pulls in ${latestRel.days_live} days` : ''],
    ['GitHub', `${fmt(gh.repo.stars)} stars`, `${fmt(gh.repo.forks)} forks · ${fmt(gh.issues.unique_authors)} issue authors${gh.discussions ? ` · ${fmt(gh.discussions.unique_authors)} discussion authors` : ''}`],
  ];
  el('headline').innerHTML = tiles.map(([l, v, h]) => `<div class="card tile"><div class="label">${l}</div><div class="value">${v}</div><div class="hint">${h}</div></div>`).join('');

  // ---- chart helpers ----------------------------------------------------------
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 11;
  function base(type, { stacked = false } = {}) {
    return {
      type,
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true, position: 'top', align: 'center', labels: { color: C.g600, boxWidth: 12, boxHeight: 12, usePointStyle: true, pointStyle: 'rectRounded', font: { size: 12 } } },
          tooltip: { backgroundColor: C.g900, titleColor: '#fff', bodyColor: '#fff', padding: 8, cornerRadius: 6, boxPadding: 3 },
        },
        scales: {
          x: { stacked, grid: { display: false }, ticks: { color: C.g500, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 }, border: { color: C.g200 } },
          y: { stacked, beginAtZero: true, grid: { color: C.g200 }, ticks: { color: C.g500, precision: 0 }, border: { display: false } },
        },
      },
    };
  }
  function make(id, cfg) {
    const canvas = el(id);
    if (!canvas) return;
    if (charts[id]) { charts[id].destroy(); delete charts[id]; }
    const holder = canvas.parentElement;
    const empty = holder.querySelector('.empty');
    if (!cfg.data.labels.length) { canvas.hidden = true; if (!empty) holder.insertAdjacentHTML('beforeend', '<div class="empty">No data yet — accumulates from daily snapshots.</div>'); return; }
    canvas.hidden = false; if (empty) empty.remove();
    charts[id] = new Chart(canvas, cfg);
  }
  const bar = (color) => ({ backgroundColor: color, borderColor: '#fff', borderWidth: 1, borderRadius: 4, borderSkipped: 'bottom', maxBarThickness: 44 });
  const line = (color, fill = false) => ({ borderColor: color, backgroundColor: fill ? color + '66' : color, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0, fill });
  const rampColors = (n) => (n <= 1 ? [C.s1] : Array.from({ length: n }, (_, i) => RAMP[Math.round((i / (n - 1)) * (RAMP.length - 1))]));
  const single = (cfg) => { cfg.options.plugins.legend.display = false; return cfg; };
  const dots = (n) => (n < 3 ? 4 : 0);
  const table = (id, head, rows, numFrom = 1) => {
    el(id).innerHTML = rows.length
      ? `<table><thead><tr>${head.map((h, i) => `<th class="${i >= numFrom ? 'num' : ''}">${h}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((v, i) => `<td class="${i >= numFrom ? 'num' : ''}">${typeof v === 'number' ? fmt(v) : v}</td>`).join('')}</tr>`).join('')}</tbody></table>`
      : '<div class="empty">No data.</div>';
  };
  // Period tabs (Observation Summary pattern): options -> days back; null = everything.
  function tabs(id, options, initial, onChange) {
    const host = el(id);
    if (!host) return;
    let active = initial;
    const render = () => { host.innerHTML = options.map(([label, days]) => `<button type="button" aria-pressed="${days === active}" data-days="${days ?? ''}">${label}</button>`).join(''); };
    host.addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; active = b.dataset.days === '' ? null : +b.dataset.days; render(); onChange(active); });
    render(); onChange(active);
  }
  const sinceDays = (rows, days, key = 'date') => (days == null ? rows : rows.filter((r) => (Date.now() - new Date(r[key] + 'T00:00:00Z')) / 864e5 <= days));

  // ---- version distribution ---------------------------------------------------
  const selfDist = Object.entries(est.self_hosted.on_release).sort((a, b) => vcmp(a[0], b[0]));
  { const cfg = single(base('bar')); cfg.data = { labels: selfDist.map((x) => x[0]), datasets: [{ label: 'stations', data: selfDist.map((x) => x[1]), ...bar(rampColors(selfDist.length)) }] }; make('c-self-dist', cfg); }
  const haDist = Object.entries(est.ha.versions || {}).sort((a, b) => vcmp(a[0], b[0]));
  { const cfg = single(base('bar')); cfg.options.scales.x.ticks = { color: C.g500, autoSkip: false, maxRotation: 45, minRotation: 45 }; cfg.data = { labels: haDist.map((x) => x[0]), datasets: [{ label: 'installs', data: haDist.map((x) => x[1]), ...bar(rampColors(haDist.length)) }] }; make('c-ha-dist', cfg); }
  {
    const all = [...new Set([...selfDist.map((x) => x[0]), ...haDist.map((x) => 'v' + x[0])])].sort(vcmp);
    const haMap = Object.fromEntries(haDist.map(([v, n]) => ['v' + v, n]));
    const selfMap = Object.fromEntries(selfDist);
    table('t-dist', ['release', 'self-hosted (est.)', 'HA reporting'], all.map((v) => [v, selfMap[v] ?? 0, haMap[v] ?? 0]));
  }
  tabs('range-hist', [['7-Day', 7], ['30-Day', 30], ['90-Day', 90], ['All', null]], null, (days) => {
    const h = sinceDays(est.history, days);
    const cfg = base('line');
    cfg.data = { labels: h.map((x) => x.date), datasets: [
      { label: 'total', data: h.map((x) => x.total), ...line(C.s1), pointRadius: dots(h.length) },
      { label: 'self-hosted', data: h.map((x) => x.self_hosted), ...line(C.s2), pointRadius: dots(h.length) },
      { label: 'Home Assistant', data: h.map((x) => x.ha), ...line(C.s3), pointRadius: dots(h.length) },
    ] };
    make('c-est-hist', cfg);
    const rels = [...new Set(h.flatMap((x) => Object.keys(x.on_release)))].sort(vcmp);
    const colors = rampColors(rels.length);
    const mix = base('line', { stacked: true }); mix.options.scales.x.stacked = false;
    mix.data = { labels: h.map((x) => x.date), datasets: rels.map((r, i) => ({ label: r, data: h.map((x) => x.on_release[r] || 0), ...line(colors[i], true), pointRadius: dots(h.length) })) };
    make('c-self-hist', mix);
    el('hist-caption').textContent = `One point per daily snapshot since ${est.history[0]?.date || '–'}${days ? `; showing the last ${days} days` : ''}.`;
  });

  // ---- GHCR ------------------------------------------------------------------------
  const rels = ghcr.releases.slice(-12);
  function renderReleases(image) {
    const cfg = base('bar', { stacked: true });
    cfg.options.scales.x.ticks = { color: C.g500, autoSkip: false, maxRotation: 45, minRotation: 45 };
    cfg.options.plugins.tooltip.callbacks = { afterTitle: (items) => { const r = rels[items[0].dataIndex]; return `built ${r.created.slice(0, 10)} · current for ${r.days_live} days${r.mixed ? ' · mixed with staging' : ''}`; } };
    const labels = rels.map((r) => r.release + (r.mixed ? '*' : ''));
    if (image === 'birdnet-pipy-frontend') {
      cfg.data = { labels, datasets: [
        { label: 'arm64', data: rels.map((r) => r.arch.arm64 || 0), ...bar(C.s1) },
        { label: 'amd64', data: rels.map((r) => r.arch.amd64 || 0), ...bar(C.s2) },
      ] };
      el('releases-title').textContent = 'Station pulls per release · frontend platform manifests';
    } else {
      single(cfg);
      cfg.data = { labels, datasets: [{ label: 'platform pulls', data: rels.map((r) => r.other_images[image] ?? 0), ...bar(C.s1) }] };
      el('releases-title').textContent = `Platform pulls per release · ${short(image)} (${image === 'birdnet-pipy-backend' ? 'pulled ~2.5× per station' : 'rarely rebuilt, so one digest spans releases'})`;
    }
    make('c-releases', cfg);
  }
  {
    const seg = el('image-seg');
    let active = 'birdnet-pipy-frontend';
    const render = () => { seg.innerHTML = IMAGES.map((img) => `<button type="button" aria-pressed="${img === active}" data-image="${img}">${short(img)[0].toUpperCase() + short(img).slice(1)}</button>`).join(''); };
    seg.addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; active = b.dataset.image; render(); renderReleases(active); });
    render(); renderReleases(active);
  }
  const relRow = (r) => [r.release, r.created.slice(0, 10), r.days_live, r.pulls, r.arch.arm64 || 0, r.arch.amd64 || 0, r.index, r.mixed ? 'yes' : '', r.other_images['birdnet-pipy-backend'] ?? 0, r.other_images['birdnet-pipy-icecast'] ?? 0];
  const relHead = ['release', 'built', 'days current', 'station pulls', 'arm64', 'amd64', 'index GETs', 'mixed', 'backend pulls', 'icecast pulls'];
  table('t-releases', relHead, [...ghcr.releases].reverse().slice(0, 8).map(relRow), 2);
  table('t-releases-all', relHead, [...ghcr.releases].reverse().map(relRow), 2);
  {
    const days = ghcr.daily;
    const labels = [...new Set(days.flatMap((d) => Object.keys(d.pulls)))].sort((a, b) => (a === 'staging') - (b === 'staging') || vcmp(a, b));
    const colors = rampColors(labels.filter((l) => l !== 'staging').length);
    const cfg = base('bar', { stacked: true });
    cfg.data = { labels: days.map((d) => d.date), datasets: labels.map((l, i) => ({ label: l, data: days.map((d) => Object.values(d.pulls[l] || {}).reduce((a, b) => a + b, 0)), ...bar(l === 'staging' ? C.g400 : colors[i]) })) };
    make('c-daily', cfg);
  }
  table('t-lifetime', ['image', 'downloads'], Object.entries(ghcr.lifetime).map(([k, v]) => [short(k), v]));
  table('t-tags', ['image', 'tag', 'index', 'arm64', 'amd64'], Object.entries(ghcr.tags).flatMap(([img, tags]) => Object.entries(tags).filter(([t]) => t !== 'ci-test').map(([t, v]) => [short(img), t, v.index, v.arch?.arm64 ?? 0, v.arch?.amd64 ?? 0])), 2);

  // ---- Home Assistant ----------------------------------------------------------------
  {
    const vs = Object.entries(ha.alex_versions).slice(-12);
    const cfg = base('bar', { stacked: true });
    cfg.data = { labels: vs.map(([v]) => v), datasets: [
      { label: 'amd64', data: vs.map(([, x]) => x.amd64 || 0), ...bar(C.s1) },
      { label: 'aarch64', data: vs.map(([, x]) => x.aarch64 || 0), ...bar(C.s2) },
    ] };
    cfg.options.plugins.tooltip.callbacks = { afterTitle: (items) => { const x = vs[items[0].dataIndex][1]; return x.age_days != null ? `published ~${x.age_days} days ago` : ''; } };
    make('c-alex-versions', cfg);
  }
  { const w = ha.alex_weekly, cfg = single(base('line')); cfg.data = { labels: w.map((x) => x.date), datasets: [{ label: 'current-version pulls', data: w.map((x) => x.value), ...line(C.s1) }] }; make('c-alex-weekly', cfg); }
  { const h = ha.history, cfg = single(base('line')); cfg.data = { labels: h.map((x) => x.date), datasets: [{ label: 'reporting installs', data: h.map((x) => x.total), ...line(C.s1), pointRadius: dots(h.length) }] }; make('c-ha-hist', cfg); }
  table('t-ha-ref', ['add-on', 'reporting installs'], [['birdnet-pipy (this project)', ha.latest ? ha.latest.total : 0], ...Object.entries(ha.reference).map(([k, v]) => [k.replace(/^[0-9a-f]+_/, ''), v ?? 0])]);

  // ---- GitHub ---------------------------------------------------------------------------
  tabs('range-traffic', [['7-Day', 7], ['30-Day', 30], ['90-Day', 90], ['All Time', null]], 90, (days) => {
    const t = sinceDays(gh.traffic.daily, days);
    const cfg = base('line');
    cfg.data = { labels: t.map((x) => x.date), datasets: [
      { label: 'unique cloners', data: t.map((x) => x.clones_unique), ...line(C.s1), pointRadius: dots(t.length) },
      { label: 'unique visitors', data: t.map((x) => x.views_unique), ...line(C.s2), pointRadius: dots(t.length) },
    ] };
    make('c-traffic', cfg);
  });
  { const m = gh.traffic.monthly, cfg = single(base('bar')); cfg.data = { labels: m.map((x) => x.month), datasets: [{ label: 'unique cloners', data: m.map((x) => x.clones_unique), ...bar(C.s1) }] }; make('c-traffic-month', cfg); }
  { const s = gh.stars, cfg = single(base('line')); cfg.data = { labels: s.map((x) => x.month), datasets: [{ label: 'stars', data: s.map((x) => x.total), ...line(C.s1), pointRadius: 3 }] }; make('c-stars', cfg); }
  { const m = Object.entries(gh.issues.by_month), cfg = single(base('bar')); cfg.data = { labels: m.map((x) => x[0]), datasets: [{ label: 'issues', data: m.map((x) => x[1]), ...bar(C.s1) }] }; make('c-issues', cfg); }
  table('t-community', ['stars', 'forks', 'watchers', 'issues', 'issue authors', 'discussions', 'discussion authors', 'tags'],
    [[gh.repo.stars, gh.repo.forks, gh.repo.watchers, gh.issues.total, gh.issues.unique_authors, gh.discussions ? gh.discussions.total : '–', gh.discussions ? gh.discussions.unique_authors : '–', gh.tags.length]], 0);
})();
