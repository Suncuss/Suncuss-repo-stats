/* BirdNET-PiPy adoption dashboard — renders data/dashboard.json with Chart.js. */
(async function () {
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const RAMP = () => css('--ramp').split(',').map((s) => s.trim());
  const S = () => ({ s1: css('--s1'), s2: css('--s2'), s3: css('--s3'), s4: css('--s4'), text: css('--text'), text2: css('--text-2'), text3: css('--text-3'), grid: css('--grid') });
  const fmt = (n) => (n == null ? '–' : Number(n).toLocaleString('en-US'));
  const vkey = (v) => String(v).split(/[.\-]/).map((x) => (/^\d+$/.test(x) ? +x : -1));
  const vcmp = (a, b) => { const x = vkey(a), y = vkey(b); for (let i = 0; i < Math.max(x.length, y.length); i++) { const d = (x[i] ?? 0) - (y[i] ?? 0); if (d) return d; } return 0; };
  const el = (id) => document.getElementById(id);
  const charts = [];

  let data;
  try {
    data = await (await fetch('data/dashboard.json', { cache: 'no-cache' })).json();
  } catch (e) {
    el('meta').textContent = 'failed to load data/dashboard.json';
    return;
  }
  const { estimate: est, ghcr, ha, github: gh } = data;

  // ---- header / errors ------------------------------------------------
  el('meta').innerHTML = `updated ${data.generated.replace('T', ' ').slice(0, 16)} UTC<br>${ghcr.snapshots.length} daily snapshot${ghcr.snapshots.length === 1 ? '' : 's'} since ${ghcr.snapshots[0] || '–'}`;
  const errs = Object.entries(data.errors || {});
  if (errs.length) { el('errors').hidden = false; el('errors').textContent = 'Last run had failures — stale sections: ' + errs.map(([k, v]) => `${k} (${v})`).join('; '); }
  el('m-own').textContent = data.config.own_stations;
  el('m-window').textContent = data.config.active_window_days;

  // ---- headline tiles -------------------------------------------------
  const latestRel = ghcr.releases[ghcr.releases.length - 1];
  const tiles = [
    ['Estimated active installs', fmt(est.total.mid), `range ${fmt(est.total.low)}–${fmt(est.total.high)}`],
    ['Self-hosted stations', fmt(est.self_hosted.active), `estimate · ${fmt(est.self_hosted.not_updating)} not updating`],
    ['Home Assistant installs', fmt(est.ha.estimated), `estimate · ${fmt(est.ha.reporting)} reporting (opt-in ${est.ha.opt_in_rate != null ? Math.round(est.ha.opt_in_rate * 100) + '%' : '–'})`],
    ['Latest release', latestRel ? latestRel.release : '–', latestRel ? `${fmt(latestRel.pulls)} station pulls in ${latestRel.days_live} days` : ''],
    ['GitHub', `${fmt(gh.repo.stars)} ★`, `${fmt(gh.repo.forks)} forks · ${fmt(gh.issues.unique_authors)} issue authors${gh.discussions ? ` · ${fmt(gh.discussions.unique_authors)} discussion authors` : ''}`],
  ];
  el('headline').innerHTML = tiles.map(([l, v, h]) => `<div class="tile"><div class="label">${l}</div><div class="value">${v}</div><div class="hint">${h}</div></div>`).join('');

  // ---- chart helpers --------------------------------------------------
  function base(type, extra = {}) {
    const c = S();
    return {
      type,
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true, labels: { color: c.text2, boxWidth: 12, boxHeight: 12, usePointStyle: true, pointStyle: 'rectRounded' } },
          tooltip: { backgroundColor: c.text, titleColor: css('--surface'), bodyColor: css('--surface'), padding: 8, cornerRadius: 4 },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: c.text2, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 }, border: { color: c.grid } },
          y: { beginAtZero: true, grid: { color: c.grid }, ticks: { color: c.text2, precision: 0 }, border: { display: false } },
        },
        ...extra,
      },
    };
  }
  function make(id, cfg) {
    const canvas = el(id);
    if (!canvas) return;
    if (!cfg.data.labels.length) { canvas.parentElement.innerHTML = '<div class="empty">No data yet — accumulates from daily snapshots.</div>'; return; }
    charts.push(new Chart(canvas, cfg));
  }
  const bar = (color) => ({ backgroundColor: color, borderColor: css('--surface'), borderWidth: 1, borderRadius: 4, borderSkipped: 'bottom', maxBarThickness: 44 });
  const line = (color, fill = false) => ({ borderColor: color, backgroundColor: fill ? color + '55' : color, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0, fill });
  const rampColors = (n) => { const r = RAMP(); if (n <= 1) return [r[r.length - 3]]; return Array.from({ length: n }, (_, i) => r[Math.round((i / (n - 1)) * (r.length - 1))]); };
  const single = (cfg) => { cfg.options.plugins.legend.display = false; return cfg; };
  const table = (id, head, rows) => { el(id).innerHTML = rows.length ? `<table><thead><tr>${head.map((h) => `<th class="${typeof rows[0][head.indexOf(h)] === 'number' ? 'num' : ''}">${h}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((v) => `<td class="${typeof v === 'number' ? 'num' : ''}">${typeof v === 'number' ? fmt(v) : v}</td>`).join('')}</tr>`).join('')}</tbody></table>` : '<div class="empty">No data.</div>'; };

  // ---- version distribution -------------------------------------------
  const selfDist = Object.entries(est.self_hosted.on_release).sort((a, b) => vcmp(a[0], b[0]));
  { const cfg = single(base('bar')); cfg.data = { labels: selfDist.map((x) => x[0]), datasets: [{ label: 'stations', data: selfDist.map((x) => x[1]), ...bar(rampColors(selfDist.length)) }] }; make('c-self-dist', cfg); }
  const haDist = Object.entries(est.ha.versions || {}).sort((a, b) => vcmp(a[0], b[0]));
  { const cfg = single(base('bar')); cfg.data = { labels: haDist.map((x) => x[0]), datasets: [{ label: 'installs', data: haDist.map((x) => x[1]), ...bar(rampColors(haDist.length)) }] }; make('c-ha-dist', cfg); }
  {
    const all = [...new Set([...selfDist.map((x) => x[0]), ...haDist.map((x) => 'v' + x[0])])].sort(vcmp);
    const haMap = Object.fromEntries(haDist.map(([v, n]) => ['v' + v, n]));
    const selfMap = Object.fromEntries(selfDist);
    table('t-dist', ['release', 'self-hosted (est.)', 'HA reporting'], all.map((v) => [v, selfMap[v] ?? 0, haMap[v] ?? 0]));
  }
  {
    const h = est.history, c = S();
    const cfg = base('line');
    cfg.data = { labels: h.map((x) => x.date), datasets: [
      { label: 'total', data: h.map((x) => x.total), ...line(c.s3), pointRadius: h.length < 3 ? 4 : 0 },
      { label: 'self-hosted', data: h.map((x) => x.self_hosted), ...line(c.s1), pointRadius: h.length < 3 ? 4 : 0 },
      { label: 'Home Assistant', data: h.map((x) => x.ha), ...line(c.s2), pointRadius: h.length < 3 ? 4 : 0 },
    ] };
    make('c-est-hist', cfg);
  }
  {
    const h = est.history;
    const rels = [...new Set(h.flatMap((x) => Object.keys(x.on_release)))].sort(vcmp);
    const colors = rampColors(rels.length);
    const cfg = base('line', { scales: { x: { grid: { display: false }, ticks: { color: S().text2, maxTicksLimit: 12 } }, y: { stacked: true, beginAtZero: true, grid: { color: S().grid }, ticks: { color: S().text2, precision: 0 }, border: { display: false } } } });
    cfg.data = { labels: h.map((x) => x.date), datasets: rels.map((r, i) => ({ label: r, data: h.map((x) => x.on_release[r] || 0), ...line(colors[i], true), pointRadius: h.length < 3 ? 4 : 0 })) };
    make('c-self-hist', cfg);
  }

  // ---- GHCR --------------------------------------------------------------
  const rels = ghcr.releases.slice(-14);
  {
    const c = S();
    const cfg = base('bar', { scales: { x: { stacked: true, grid: { display: false }, ticks: { color: c.text2, autoSkip: false, maxRotation: 45, minRotation: 45 } }, y: { stacked: true, beginAtZero: true, grid: { color: c.grid }, ticks: { color: c.text2, precision: 0 }, border: { display: false } } } });
    cfg.data = { labels: rels.map((r) => r.release + (r.mixed ? '*' : '')), datasets: [
      { label: 'arm64', data: rels.map((r) => r.arch.arm64 || 0), ...bar(c.s1) },
      { label: 'amd64', data: rels.map((r) => r.arch.amd64 || 0), ...bar(c.s2) },
    ] };
    cfg.options.plugins.tooltip.callbacks = { afterTitle: (items) => { const r = rels[items[0].dataIndex]; return `built ${r.created.slice(0, 10)} · current for ${r.days_live} days${r.mixed ? ' · mixed with staging' : ''}`; } };
    make('c-releases', cfg);
  }
  table('t-releases', ['release', 'built', 'days current', 'station pulls', 'arm64', 'amd64', 'index GETs', 'mixed', 'backend pulls', 'icecast pulls'],
    [...ghcr.releases].reverse().map((r) => [r.release, r.created.slice(0, 10), r.days_live, r.pulls, r.arch.arm64 || 0, r.arch.amd64 || 0, r.index, r.mixed ? 'yes' : '', r.other_images['birdnet-pipy-backend'] ?? 0, r.other_images['birdnet-pipy-icecast'] ?? 0]));
  {
    const days = ghcr.daily;
    const labels = [...new Set(days.flatMap((d) => Object.keys(d.pulls)))].sort((a, b) => (a === 'staging') - (b === 'staging') || vcmp(a, b));
    const colors = rampColors(labels.filter((l) => l !== 'staging').length);
    const c = S();
    const cfg = base('bar', { scales: { x: { stacked: true, grid: { display: false }, ticks: { color: c.text2, maxTicksLimit: 14 } }, y: { stacked: true, beginAtZero: true, grid: { color: c.grid }, ticks: { color: c.text2, precision: 0 }, border: { display: false } } } });
    cfg.data = { labels: days.map((d) => d.date), datasets: labels.map((l, i) => ({ label: l, data: days.map((d) => Object.values(d.pulls[l] || {}).reduce((a, b) => a + b, 0)), ...bar(l === 'staging' ? c.text3 : colors[i]) })) };
    make('c-daily', cfg);
  }
  table('t-lifetime', ['image', 'downloads'], Object.entries(ghcr.lifetime).map(([k, v]) => [k.replace('birdnet-pipy-', ''), v]));
  table('t-tags', ['image', 'tag', 'index GETs', 'arm64 pulls', 'amd64 pulls'], Object.entries(ghcr.tags).flatMap(([img, tags]) => Object.entries(tags).filter(([t]) => t !== 'ci-test').map(([t, v]) => [img.replace('birdnet-pipy-', ''), t, v.index, v.arch?.arm64 ?? 0, v.arch?.amd64 ?? 0])));

  // ---- Home Assistant -------------------------------------------------------
  {
    const vs = Object.entries(ha.alex_versions).slice(-12), c = S();
    const cfg = base('bar', { scales: { x: { stacked: true, grid: { display: false }, ticks: { color: c.text2, maxRotation: 0 } }, y: { stacked: true, beginAtZero: true, grid: { color: c.grid }, ticks: { color: c.text2, precision: 0 }, border: { display: false } } } });
    cfg.data = { labels: vs.map(([v]) => v), datasets: [
      { label: 'amd64', data: vs.map(([, x]) => x.amd64 || 0), ...bar(c.s1) },
      { label: 'aarch64', data: vs.map(([, x]) => x.aarch64 || 0), ...bar(c.s2) },
    ] };
    cfg.options.plugins.tooltip.callbacks = { afterTitle: (items) => { const x = vs[items[0].dataIndex][1]; return x.age_days != null ? `published ~${x.age_days} days ago` : ''; } };
    make('c-alex-versions', cfg);
  }
  { const w = ha.alex_weekly, cfg = single(base('line')); cfg.data = { labels: w.map((x) => x.date), datasets: [{ label: 'current-version pulls', data: w.map((x) => x.value), ...line(S().s1) }] }; make('c-alex-weekly', cfg); }
  { const h = ha.history, cfg = single(base('line')); cfg.data = { labels: h.map((x) => x.date), datasets: [{ label: 'reporting installs', data: h.map((x) => x.total), ...line(S().s1), pointRadius: h.length < 3 ? 4 : 0 }] }; make('c-ha-hist', cfg); }
  table('t-ha-ref', ['add-on', 'reporting installs'], [['birdnet-pipy (this project)', ha.latest ? ha.latest.total : 0], ...Object.entries(ha.reference).map(([k, v]) => [k.replace(/^[0-9a-f]+_/, ''), v ?? 0])]);

  // ---- GitHub ----------------------------------------------------------------
  {
    const t = gh.traffic.daily, c = S(), cfg = base('line');
    cfg.data = { labels: t.map((x) => x.date), datasets: [
      { label: 'unique cloners', data: t.map((x) => x.clones_unique), ...line(c.s1) },
      { label: 'unique visitors', data: t.map((x) => x.views_unique), ...line(c.s2) },
    ] };
    make('c-traffic', cfg);
  }
  { const m = gh.traffic.monthly, cfg = single(base('bar')); cfg.data = { labels: m.map((x) => x.month), datasets: [{ label: 'unique cloners', data: m.map((x) => x.clones_unique), ...bar(S().s1) }] }; make('c-traffic-month', cfg); }
  { const s = gh.stars, cfg = single(base('line')); cfg.data = { labels: s.map((x) => x.month), datasets: [{ label: 'stars', data: s.map((x) => x.total), ...line(S().s1) }] }; cfg.options.elements = { point: { radius: 3 } }; make('c-stars', cfg); }
  { const m = Object.entries(gh.issues.by_month), cfg = single(base('bar')); cfg.data = { labels: m.map((x) => x[0]), datasets: [{ label: 'issues', data: m.map((x) => x[1]), ...bar(S().s1) }] }; make('c-issues', cfg); }
  table('t-community', ['stars', 'forks', 'watchers', 'issues', 'issue authors', 'discussions', 'discussion authors', 'tags'],
    [[gh.repo.stars, gh.repo.forks, gh.repo.watchers, gh.issues.total, gh.issues.unique_authors, gh.discussions ? gh.discussions.total : '–', gh.discussions ? gh.discussions.unique_authors : '–', gh.tags.length]]);

  // Re-render on theme change so colors follow the palette.
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => location.reload());
})();
