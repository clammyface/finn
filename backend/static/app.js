// ================= helpers =================
const view = document.getElementById("view");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) {
    let msg = "Error " + r.status;
    try { msg = (await r.json()).detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
}

const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; }
  },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) {} },
};

const DEFAULTS = { hours: 24, price: 3, vol: 2,
  types: ["results", "M&A", "management_change", "fund_raise", "litigation", "credit_rating", "pledging"] };
const getSettings = () => ({ ...DEFAULTS, ...store.get("finn-settings", {}) });
const saveSettings = (s) => store.set("finn-settings", s);

// Inbox zero: ids the investor has marked as handled, kept on this phone.
const getDone = () => new Set(store.get("finn-done", []));
const saveDone = (set) => store.set("finn-done", [...set].slice(-2000));

const LABELS = { results: "Results", "M&A": "M&A", management_change: "Management", fund_raise: "Fund raise",
  litigation: "Litigation", insider_trading: "Insider trade", earnings_call: "Earnings call",
  investor_meetings: "Investor meet", credit_rating: "Credit rating", dividend: "Dividend",
  bonus_split: "Bonus/Split", capex: "Capex", press_release: "News", postal_ballot: "Postal ballot",
  agm_egm: "AGM/EGM", pledging: "Pledge", unclassified: "Routine" };
const PLURAL = { results: "results", "M&A": "M&A deals", management_change: "management changes",
  fund_raise: "fund raises", litigation: "legal/regulatory items", credit_rating: "rating actions",
  pledging: "pledge changes", capex: "capex plans", insider_trading: "insider trades",
  bonus_split: "bonus/split", dividend: "dividends", press_release: "news items" };
const SINGULAR = { results: "result", "M&A": "M&A deal", management_change: "management change",
  fund_raise: "fund raise", litigation: "legal/regulatory item", credit_rating: "rating action",
  pledging: "pledge change", capex: "capex plan", insider_trading: "insider trade",
  bonus_split: "bonus/split", dividend: "dividend", press_release: "news item" };
const ALL_TYPES = ["results", "M&A", "management_change", "fund_raise", "litigation", "credit_rating",
  "pledging", "insider_trading", "capex", "dividend", "bonus_split", "press_release"];

const fmtTime = (iso) => iso ? new Date(iso).toLocaleString("en-IN",
  { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
const fmtNum = (v) => v == null ? "–" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: 1 });
const signed = (v, d = 1) => (v >= 0 ? "+" : "−") + Math.abs(Number(v)).toFixed(d);
function chg(v) {
  if (v == null) return '<span class="text-zinc-600">–</span>';
  return `<span class="${v >= 0 ? "text-emerald-400" : "text-rose-400"}">${signed(v)}%</span>`;
}
const chip = (t, cls = "bg-zinc-800 text-zinc-300") =>
  `<span class="rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}">${esc(t)}</span>`;
const H = (t, extra = "") => `<h2 class="mb-2 flex items-baseline gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">${t}${extra}</h2>`;
const section = (title, inner, extra) => `<section class="mb-6">${H(title, extra)}<div class="space-y-3">${inner}</div></section>`;
const empty = (msg) => `<p class="rounded-xl bg-card/60 px-4 py-3 text-sm text-zinc-500">${esc(msg)}</p>`;
const list = (items) => `<ul class="space-y-2">${(items || []).map((x) =>
  `<li class="text-sm leading-snug text-zinc-300">${esc(x)}</li>`).join("")}</ul>`;
const loading = (msg) => `<div class="py-20 text-center text-sm text-zinc-500">
  <div class="mx-auto mb-3 h-6 w-6 animate-spin rounded-full border-2 border-zinc-700 border-t-accent"></div>${esc(msg)}</div>`;
const errorBox = (e) => `<div class="mt-6 rounded-xl border border-rose-900 bg-rose-950/40 p-4 text-sm text-rose-200">${esc(e.message || e)}</div>`;
const scoreColor = (s) => s == null ? "text-zinc-500" : s >= 7 ? "text-emerald-400" : s >= 4 ? "text-accent" : "text-rose-400";

function spark(values, w = 120, h = 32, stroke = "#a1a1aa") {
  const v = (values || []).filter((x) => x != null);
  if (v.length < 2) return "";
  const min = Math.min(...v), max = Math.max(...v), span = max - min || 1;
  const pts = v.map((x, i) => `${((i / (v.length - 1)) * w).toFixed(1)},${(h - ((x - min) / span) * h).toFixed(1)}`).join(" ");
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" class="mt-1 overflow-visible">
    <polyline fill="none" stroke="${stroke}" stroke-width="1.5" stroke-linejoin="round" points="${pts}"/></svg>`;
}

// ================= routing =================
const VIEWS = { today: renderToday, alerts: renderAlerts, research: renderResearch, settings: renderSettings };
let current = null;
function go(tab, arg) {
  current = tab;
  document.querySelectorAll(".tab").forEach((b) => {
    b.classList.toggle("text-accent", b.dataset.tab === tab);
    b.classList.toggle("text-zinc-500", b.dataset.tab !== tab);
  });
  history.replaceState(null, "", "#" + tab + (arg ? "/" + arg : ""));
  window.scrollTo(0, 0);
  VIEWS[tab](arg);
}
document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => go(b.dataset.tab)));

// One click handler for everything rendered into the view (no inline JS with data in it).
view.addEventListener("click", (e) => {
  const el = e.target.closest("[data-act]");
  if (!el) return;
  const { act } = el.dataset;
  if (act === "window") { const s = getSettings(); s.hours = Number(el.dataset.h); saveSettings(s); renderToday(); }
  else if (act === "done") markDone(el.dataset.id, true, el.closest("[data-card]"));
  else if (act === "undo") markDone(el.dataset.id, false);
  else if (act === "research") { e.preventDefault(); go("research", el.dataset.sym); }
  else if (act === "go") go(el.dataset.tab);
  else if (act === "filter") { ledgerFilter = ledgerFilter === el.dataset.v ? null : el.dataset.v; drawLedger(); }
  else if (act === "type") toggleType(el.dataset.t);
  else if (act === "reset-done") { saveDone(new Set()); renderSettings(); }
});

function markDone(ids, done, card) {
  const set = getDone();
  ids.split(",").forEach((id) => (done ? set.add(id) : set.delete(id)));
  saveDone(set);
  if (done && card) { card.classList.add("fade-out"); setTimeout(renderToday, 220); }
  else renderToday();
}

// Like email conversations: one card per company + category, newest evidence folded inside.
// Done clears the whole thread; a new filing in it later brings the story back.
function threads(items) {
  const groups = new Map();
  for (const i of items) {                       // already sorted: priority, then newest
    const k = i.symbol + "|" + i.category;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(i);
  }
  return [...groups.values()].map((g) => {
    const lead = g.find((i) => i.results) || g.find((i) => i.people && i.people.length) || g[0];
    const seen = new Set();
    const people = g.flatMap((i) => i.people || []).filter((p) => p.name && !seen.has(p.name) && seen.add(p.name));
    return { ...lead, tier: g[0].tier, priority: g[0].priority, people,
      related: g.filter((i) => i !== lead), ids: g.map((i) => i.id).join(",") };
  });
}

// ================= Today =================
let todayCache = null;     // keeps re-renders after "Done" instant

async function renderToday() {
  const s = getSettings();
  if (!todayCache || todayCache.hours !== s.hours) {
    view.innerHTML = loading("Sorting your filings… the first load can take a minute while the server wakes up.");
    try {
      const [d, p, rl] = await Promise.all([api(`/api/digest?hours=${s.hours}`), api("/api/portfolio"),
        api("/api/research").catch(() => [])]);
      todayCache = { hours: s.hours, d, p, scores: Object.fromEntries(rl.map((r) => [r.symbol, r.score])) };
    } catch (e) { view.innerHTML = errorBox(e); return; }
  }
  if (current !== "today") return;
  const { d, p, scores } = todayCache;
  const done = getDone();
  const px = Object.fromEntries(p.stocks.map((x) => [x.symbol, x]));
  const notLow = d.items.filter((i) => i.tier !== "low");
  const high = threads(notLow).filter((t) => t.tier === "high");
  const open = threads(notLow.filter((i) => !done.has(i.id)));
  const openHigh = open.filter((t) => t.tier === "high");
  const openMid = open.filter((t) => t.tier === "medium");
  const handled = notLow.filter((i) => done.has(i.id));
  const low = d.items.filter((i) => i.tier === "low");
  const windows = [[24, "24h"], [72, "3d"], [168, "7d"], [720, "30d"]];
  const movers = p.stocks.slice().sort((a, b) => Math.abs(b.pct_change) - Math.abs(a.pct_change));

  const headline = !high.length ? "All quiet"
    : !openHigh.length ? "Inbox zero"
    : `${openHigh.length} need${openHigh.length === 1 ? "s" : ""} you`;
  const sub = !high.length ? "Nothing in this window needs a decision."
    : !openHigh.length ? `You've handled all ${high.length} item${high.length > 1 ? "s" : ""} that needed you.`
    : `${openMid.length} worth a glance · ${low.length} routine filed away`;

  view.innerHTML = `
    <header class="mb-4">
      <p class="font-mono text-[11px] text-zinc-500">Data as of ${fmtTime(d.as_of)}</p>
      <h1 class="mt-1 flex items-center gap-2 text-3xl font-semibold tracking-tight">${esc(headline)}
        ${high.length && !openHigh.length ? '<span class="text-emerald-400">✓</span>' : ""}</h1>
      <p class="text-sm text-zinc-400">${esc(sub)}</p>
    </header>
    ${briefCard(p.stocks, openHigh, movers)}
    <div class="mb-4 flex gap-2">${windows.map(([h, l]) =>
      `<button data-act="window" data-h="${h}" class="rounded-full px-3 py-1 font-mono text-xs ${h === s.hours ? "bg-accent text-ink" : "bg-card text-zinc-400"}">${l}</button>`).join("")}</div>
    <div class="no-scrollbar -mx-4 mb-6 flex gap-2 overflow-x-auto px-4">${movers.map((m) => stockPill(m, scores[m.symbol])).join("")}</div>
    ${section("Needs you", openHigh.map((i) => fullCard(i, px[i.symbol])).join("") ||
      empty(high.length ? "Done for this window. Go do something else." : "Nothing urgent in this window."), count(openHigh.length))}
    ${section("Worth a glance", openMid.map((t) => compactCard(t)).join("") || empty("Nothing here."), count(openMid.length))}
    ${handled.length ? `<details class="mb-3 rounded-2xl bg-card/60">
      <summary class="cursor-pointer px-4 py-3 text-sm text-zinc-400">Handled · ${handled.length} · tap to review</summary>
      <div class="divide-y divide-line px-4 pb-2">${handled.map((i) => lineItem(i, true)).join("")}</div></details>` : ""}
    <details class="mb-6 rounded-2xl bg-card/60">
      <summary class="cursor-pointer px-4 py-3 text-sm text-zinc-400">Filed away · ${low.length} routine filings · tap to show</summary>
      <div class="divide-y divide-line px-4 pb-2">${low.map((i) => lineItem(i)).join("")}</div>
    </details>`;
}
const count = (n) => n ? `<span class="font-mono text-zinc-600">${n}</span>` : "";

// The brief is computed from the data on the phone: zero AI cost, always consistent with the cards.
function briefCard(stocks, openHigh, movers) {
  if (!stocks.length) return "";
  const avg = stocks.reduce((a, s) => a + s.pct_change, 0) / stocks.length;
  const up = stocks.filter((s) => s.pct_change > 0).length, down = stocks.filter((s) => s.pct_change < 0).length;
  const parts = [`Portfolio ${signed(avg, 2)}% on average, ${up} up and ${down} down`];
  const cats = {};
  openHigh.forEach((i) => { cats[i.category] = (cats[i.category] || 0) + 1; });
  const catText = Object.entries(cats).sort((a, b) => b[1] - a[1])
    .map(([c, n]) => `${n} ${(n > 1 ? PLURAL[c] : SINGULAR[c]) || LABELS[c] || c}`);
  if (catText.length) parts.push(catText.join(", ") + " waiting for you");
  const m = movers[0];
  if (m) parts.push(`biggest move ${m.symbol} ${signed(m.pct_change)}%${m.vol_ratio >= 1.5 ? ` on ${m.vol_ratio}× volume` : ""}`);
  const hour = new Date().getHours();
  const label = hour < 12 ? "Morning brief" : hour < 17 ? "Afternoon brief" : "Evening brief";
  const text = parts.map((x) => x[0].toUpperCase() + x.slice(1)).join(". ");
  return `<div class="mb-4 rounded-2xl border-l-2 border-accent bg-card px-4 py-3">
    <div class="mb-1 font-mono text-[10px] uppercase tracking-wider text-accent">${label}</div>
    <p class="text-sm leading-relaxed text-zinc-300">${esc(text)}.</p></div>`;
}

function stockPill(p, score) {
  const up = p.pct_change >= 0;
  return `<button data-act="research" data-sym="${esc(p.symbol)}" class="shrink-0 rounded-xl bg-card px-3 py-2 text-left ring-1 ring-line">
    <div class="flex items-center gap-1.5 text-xs font-semibold">${esc(p.symbol)}
      ${score != null ? `<span class="rounded bg-zinc-800 px-1 font-mono text-[10px] ${scoreColor(score)}" title="Management credibility">${esc(score)}/10</span>` : ""}</div>
    <div class="tabular font-mono text-xs ${up ? "text-emerald-400" : "text-rose-400"}">${signed(p.pct_change, 2)}%${p.vol_ratio >= 2 ? `<span class="ml-1 text-accent">${p.vol_ratio}×</span>` : ""}</div>
    ${spark(p.closes_30d, 56, 16, up ? "#34d399" : "#fb7185")}</button>`;
}

const doneBtn = (ids) => `<button data-act="done" data-id="${esc(ids)}" class="ml-auto rounded-full bg-zinc-800 px-3 py-1 text-xs font-medium text-zinc-300 active:bg-accent active:text-ink">Done ✓</button>`;

function fullCard(i, px) {
  const moved = px && (i.time || "").slice(0, 10) === px.date && Math.abs(px.pct_change) >= 2;
  return `<article data-card="${esc(i.id)}" class="rounded-2xl bg-card p-4 ring-1 ring-line">
    <div class="mb-1.5 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
      <span class="font-semibold text-zinc-100">${esc(i.symbol)}</span>
      ${chip(LABELS[i.category] || i.category, "bg-accent/15 text-accent")}
      ${moved ? chip(`${signed(px.pct_change)}% that day`, px.pct_change >= 0 ? "bg-emerald-500/15 text-emerald-300" : "bg-rose-500/15 text-rose-300") : ""}
      <span class="ml-auto font-mono text-[11px]">${fmtTime(i.time)}</span></div>
    <p class="text-[15px] leading-snug">${esc(i.summary || i.subject)}</p>
    ${i.results?.current?.revenue != null ? resultsBlock(i.results) : ""}
    ${i.people && i.people.length ? peopleBlock(i.people) : ""}
    ${relatedBlock(i.related)}
    <div class="mt-3 flex items-center gap-4 text-xs">
      ${i.pdf ? `<a href="${esc(i.pdf)}" target="_blank" rel="noopener" class="text-sky-400">Filing ↗</a>` : ""}
      <a href="#research/${esc(i.symbol)}" data-act="research" data-sym="${esc(i.symbol)}" class="text-sky-400">Promise ledger →</a>
      ${doneBtn(i.ids || i.id)}</div>
  </article>`;
}

function resultsBlock(r) {
  const rows = [["Revenue", "revenue"], ["EBITDA", "ebitda"], ["PBT", "pbt"], ["PAT", "pat"]];
  return `<div class="mt-3 rounded-xl bg-ink/70 p-3">
    <div class="grid grid-cols-4 pb-1 text-[11px] text-zinc-500"><span>${esc(r.label || "Quarter")}</span>
      <span class="text-right">${esc(r.unit || "")}</span><span class="text-right">QoQ</span><span class="text-right">YoY</span></div>
    ${rows.map(([n, k]) => `<div class="tabular grid grid-cols-4 border-t border-line py-1.5 font-mono text-[13px]">
      <span class="font-sans text-zinc-400">${n}</span><span class="text-right">${fmtNum(r.current?.[k])}</span>
      <span class="text-right">${chg(r.qoq?.[k])}</span><span class="text-right">${chg(r.yoy?.[k])}</span></div>`).join("")}
    <p class="pt-1 text-[11px] leading-snug text-zinc-500">${esc(r.basis || "")}${r.ebitda_margin != null ? ` · EBITDA margin ${r.ebitda_margin}%` : ""}
      · EBITDA = PBT + interest + depreciation − other income, computed in Python from the filing</p>
  </div>`;
}

function peopleBlock(people) {
  return people.map((p) => `<div class="mt-3 rounded-xl bg-ink/70 p-3">
    <div class="text-sm font-semibold">${esc(p.name)} <span class="font-normal text-zinc-400">· ${esc(p.role)} · ${esc(p.change)}</span></div>
    ${p.bio ? `<p class="mt-1 text-sm text-zinc-300">${esc(p.bio)}</p>` : ""}
    ${p.previous && p.previous.length ? `<p class="mt-1 text-xs text-zinc-500">Before: ${p.previous.map(esc).join(" · ")}</p>` : ""}
    ${p.source ? `<a href="${esc(p.source)}" target="_blank" rel="noopener" class="mt-1 inline-block text-xs text-sky-400">Source ↗</a>` : ""}
  </div>`).join("");
}

function compactCard(i, withDone = true) {
  return `<div data-card="${esc(i.id)}" class="rounded-xl bg-card/70 px-4 py-3">
    <div class="flex items-center gap-2 text-xs text-zinc-500"><span class="font-semibold text-zinc-200">${esc(i.symbol)}</span>
      ${chip(LABELS[i.category] || i.category)}${i.is_intimation ? chip("Upcoming", "bg-sky-500/10 text-sky-300") : ""}
      <span class="ml-auto font-mono text-[11px]">${fmtTime(i.time)}</span></div>
    <p class="mt-1 text-sm text-zinc-300">${esc(i.summary || i.subject)}</p>
    ${relatedBlock(i.related)}
    <div class="mt-2 flex items-center gap-4 text-xs">
      ${i.pdf ? `<a href="${esc(i.pdf)}" target="_blank" rel="noopener" class="text-sky-400">Filing ↗</a>` : ""}
      ${withDone ? doneBtn(i.ids || i.id) : ""}</div>
  </div>`;
}

function relatedBlock(related) {
  if (!related || !related.length) return "";
  return `<details class="mt-2"><summary class="cursor-pointer text-xs text-zinc-500">+ ${related.length} more filing${related.length > 1 ? "s" : ""} on this</summary>
    <div class="mt-1 divide-y divide-line">${related.map((r) => {
      const link = r.pdf ? `href="${esc(r.pdf)}" target="_blank" rel="noopener"` : "";
      return `<a ${link} class="flex gap-3 py-1.5 text-xs"><span class="w-24 shrink-0 font-mono text-[11px] text-zinc-500">${fmtTime(r.time)}</span>
        <span class="text-zinc-400">${esc(r.summary || r.subject)}</span></a>`;
    }).join("")}</div></details>`;
}

function lineItem(i, undo = false) {
  const link = i.pdf ? `href="${esc(i.pdf)}" target="_blank" rel="noopener"` : "";
  return `<div class="flex items-center gap-3 py-2 text-xs"><span class="w-20 shrink-0 font-semibold text-zinc-300">${esc(i.symbol)}</span>
    <a ${link} class="flex-1 text-zinc-500">${esc(i.summary || i.subject)}</a>
    ${undo ? `<button data-act="undo" data-id="${esc(i.id)}" class="text-sky-400">Undo</button>` : ""}</div>`;
}

// ================= Alerts =================
async function renderAlerts() {
  const s = getSettings();
  view.innerHTML = loading("Checking your thresholds…");
  try {
    const q = new URLSearchParams({ price: s.price, vol: s.vol, types: s.types.join(",") });
    const d = await api(`/api/alerts?${q}`);
    if (current !== "alerts") return;
    const market = d.alerts.filter((a) => a.kind !== "filing");
    const filings = threads(d.alerts.filter((a) => a.kind === "filing").map((a) => a.item)
      .sort((a, b) => b.priority - a.priority || (b.time > a.time ? 1 : -1)));
    const total = market.length + filings.length;
    view.innerHTML = `
      <header class="mb-4">
        <p class="font-mono text-[11px] text-zinc-500">Data as of ${fmtTime(d.as_of)}</p>
        <h1 class="mt-1 text-3xl font-semibold tracking-tight">${total} alert${total === 1 ? "" : "s"}</h1>
        <p class="text-sm text-zinc-400">Price ±${s.price}% · volume ${s.vol}× · ${s.types.length} filing types
          <button data-act="go" data-tab="settings" class="ml-1 text-sky-400">Change</button></p>
      </header>
      ${section("Unusual moves", market.map(alertCard).join("") || empty("No stock crossed your thresholds."), count(market.length))}
      ${section("Filings you follow", filings.map((t) => compactCard(t, false)).join("") || empty("No new filings of the types you follow."), count(filings.length))}`;
  } catch (e) { view.innerHTML = errorBox(e); }
}

function alertCard(a) {
  const up = a.pct_change >= 0;
  return `<article class="rounded-2xl bg-card p-4 ring-1 ring-line">
    <div class="mb-1 flex items-center gap-2 text-xs text-zinc-500">${chip(a.kind === "price" ? "Price" : "Volume", "bg-accent/15 text-accent")}
      <span>${esc(a.name)}</span>
      <span class="ml-auto font-mono ${up ? "text-emerald-400" : "text-rose-400"}">${signed(a.pct_change, 2)}% · ${a.vol_ratio}×</span></div>
    <p class="text-[15px] font-medium">${esc(a.title)}</p>
    <p class="text-xs text-zinc-500">${esc(a.detail)}</p>
    ${a.related ? `<div class="mt-3 border-t border-line pt-2 text-xs text-zinc-400"><span class="text-zinc-500">Possible reason:</span>
      ${esc(a.related.summary || a.related.subject)}</div>`
      : `<div class="mt-3 border-t border-line pt-2 text-xs text-zinc-500">No filing in the last 3 days explains this move.</div>`}
    <a href="#research/${esc(a.symbol)}" data-act="research" data-sym="${esc(a.symbol)}" class="mt-2 inline-block text-xs text-sky-400">Promise ledger →</a>
  </article>`;
}

async function refreshAlertBadge() {
  try {
    const s = getSettings();
    const d = await api(`/api/alerts?${new URLSearchParams({ price: s.price, vol: s.vol, types: s.types.join(",") })}`);
    document.getElementById("alertBadge").classList.toggle("hidden", !d.alerts.some((a) => a.kind !== "filing"));
  } catch (e) {}
}

// ================= Research (Promise Ledger) =================
let researchList = null, currentResearch = null, ledgerFilter = null;
const VERDICT = {
  delivered: ["Delivered", "bg-emerald-500/15 text-emerald-300", "bg-emerald-400"],
  partly: ["Partly", "bg-amber-500/15 text-amber-300", "bg-amber-400"],
  missed: ["Missed", "bg-rose-500/15 text-rose-300", "bg-rose-400"],
  too_early: ["Too early", "bg-zinc-800 text-zinc-400", "bg-zinc-600"],
  unclear: ["Unclear", "bg-zinc-800 text-zinc-500", "bg-zinc-700"],
};

async function renderResearch(sym) {
  view.innerHTML = `
    <header class="mb-4">
      <h1 class="text-3xl font-semibold tracking-tight">Promise ledger</h1>
      <p class="text-sm text-zinc-400">Did management deliver what they promised? Built only from the last six earnings calls and reported numbers. No news, no broker notes.</p>
    </header>
    <form id="rform" class="mb-3 flex gap-2">
      <input id="rsym" autocapitalize="characters" autocomplete="off" placeholder="Any NSE symbol, e.g. HAVELLS"
        class="flex-1 rounded-xl bg-card px-4 py-3 font-mono text-sm uppercase outline-none ring-1 ring-line placeholder:normal-case placeholder:text-zinc-600 focus:ring-accent">
      <button class="rounded-xl bg-accent px-4 text-sm font-semibold text-ink">Check</button>
    </form>
    <div id="rchips" class="mb-6 flex flex-wrap gap-2"></div>
    <div id="rout"></div>`;
  document.getElementById("rform").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = document.getElementById("rsym").value.trim().toUpperCase();
    if (v) go("research", v);
  });
  if (sym) loadResearch(sym);
  try {
    researchList = researchList || await api("/api/research");
    const chips = document.getElementById("rchips");
    if (chips) chips.innerHTML = researchList.map((r) =>
      `<button data-act="research" data-sym="${esc(r.symbol)}" class="flex items-center gap-1.5 rounded-full bg-card px-3 py-1 text-xs text-zinc-300 ring-1 ring-line">
        ${esc(r.symbol)}${r.score != null ? `<span class="font-mono ${scoreColor(r.score)}">${esc(r.score)}</span>` : ""}</button>`).join("");
  } catch (e) {}
}

async function loadResearch(sym) {
  const out = document.getElementById("rout");
  if (!out) return;
  out.innerHTML = loading(`Reading ${sym}'s last 6 earnings calls… this takes a few minutes the first time, and is instant after that.`);
  try {
    const r = await api(`/api/research/${encodeURIComponent(sym)}`);
    if (!document.getElementById("rout")) return;
    currentResearch = r; ledgerFilter = null;
    out.innerHTML = researchView(r);
    drawLedger();
    researchList = null;           // a new company may have been added
  } catch (e) { out.innerHTML = errorBox(e); }
}

function drawLedger() {
  const box = document.getElementById("ledger");
  if (!box || !currentResearch) return;
  const r = currentResearch, ledger = (r.analysis && r.analysis.ledger) || [];
  const callUrl = (date) => ((r.calls || []).find((c) => c.date === date) || {}).url;
  const shown = ledgerFilter ? ledger.filter((l) => l.verdict === ledgerFilter) : ledger;
  document.querySelectorAll("[data-act=filter]").forEach((b) =>
    b.classList.toggle("ring-1", b.dataset.v === ledgerFilter));
  box.innerHTML = shown.map((l) => {
    const [label, cls] = VERDICT[l.verdict] || [l.verdict, "bg-zinc-800 text-zinc-400"];
    const url = callUrl(l.call_date);
    return `<article class="rounded-2xl bg-card p-4 ring-1 ring-line">
      <div class="mb-1.5 flex items-center gap-2 text-xs text-zinc-500">${chip(label, cls)}
        <span>Said in ${esc(l.made_in || l.call_date)}</span><span class="ml-auto font-mono">${esc(l.timeframe || "")}</span></div>
      <p class="text-[15px] font-medium leading-snug">${esc(l.promise)}</p>
      <p class="mt-1 text-sm text-zinc-400">${esc(l.evidence)}</p>
      ${l.quote ? `<blockquote class="mt-2 border-l-2 border-accent/50 pl-3 text-xs italic text-zinc-500">“${esc(l.quote)}”
        ${url ? `<a href="${esc(url)}${l.page && l.page_checked !== false ? "#page=" + esc(l.page) : ""}" target="_blank" rel="noopener" class="not-italic text-sky-400">${l.page_checked === false ? "transcript" : "p." + esc(l.page)} ↗</a>` : ""}
        ${l.page_checked === false ? `<span class="not-italic text-zinc-600">· not found word for word</span>` : ""}</blockquote>` : ""}
    </article>`;
  }).join("") || empty(ledger.length ? "No promises with this verdict."
    : !(r.calls || []).length ? "This company doesn't publish earnings-call transcripts, so there are no promises to check. The numbers below are its reported financials."
    : "No measurable guidance found in the transcripts.");
}

function researchView(r) {
  const a = r.analysis || {};
  const ledger = a.ledger || [];
  const n = (v) => ledger.filter((l) => l.verdict === v).length;
  const q = (r.snapshot && r.snapshot.quarters) || [];
  const last = q[q.length - 1] || {};
  const ratios = Object.entries((r.snapshot && r.snapshot.ratios) || {}).slice(0, 6);
  const cred = a.credibility;
  const bar = ledger.length ? `<div class="mb-2 flex h-2 overflow-hidden rounded-full bg-zinc-800">${Object.entries(VERDICT).map(([k, v]) =>
    n(k) ? `<div class="${v[2]}" style="width:${(n(k) / ledger.length) * 100}%"></div>` : "").join("")}</div>
    <div class="mb-3 flex flex-wrap gap-2">${Object.entries(VERDICT).map(([k, v]) =>
      `<button data-act="filter" data-v="${k}" class="rounded-full px-2 py-0.5 text-[11px] font-medium ring-zinc-400 ${v[1]}">${n(k)} ${v[0].toLowerCase()}</button>`).join("")}</div>` : "";

  return `
    <section class="mb-6">
      <h2 class="text-xl font-semibold">${esc(r.name)} <span class="font-mono text-sm font-normal text-zinc-500">${esc(r.symbol)}</span></h2>
      ${r.business ? `<p class="mt-1 text-sm text-zinc-400">${esc(r.business)}</p>` : ""}
      ${cred ? `<div class="mt-4 flex items-center gap-4 rounded-2xl bg-card p-4 ring-1 ring-line">
        <div class="tabular font-mono text-4xl font-medium ${scoreColor(cred.score)}">${esc(cred.score)}<span class="text-base text-zinc-500">/10</span></div>
        <div><div class="text-[11px] uppercase tracking-wider text-zinc-500">Management credibility</div>
        <p class="text-sm text-zinc-300">${esc(cred.line)}</p></div></div>` : ""}
      ${r.tone ? `<p class="mt-2 text-xs text-zinc-500">Tone on the latest call: ${esc(r.tone)}</p>` : ""}
    </section>
    <section class="mb-6">${H("Promised vs delivered", count(ledger.length))}${bar}<div id="ledger" class="space-y-3"></div></section>
    <section class="mb-6">${H("The numbers")}
      <div class="grid grid-cols-3 gap-2">${ratios.map(([k, v]) => `<div class="rounded-xl bg-card p-3">
        <div class="text-[11px] text-zinc-500">${esc(k)}</div><div class="tabular font-mono text-sm">${esc(v)}</div></div>`).join("")}</div>
      <div class="mt-2 grid grid-cols-2 gap-2">
        <div class="rounded-xl bg-card p-3"><div class="text-[11px] text-zinc-500">Sales · last ${q.length} quarters</div>
          <div class="tabular font-mono text-sm">${fmtNum(last.sales)} cr ${chg(last.sales_yoy)}</div>${spark(q.map((x) => x.sales), 140, 36, "#f5b544")}</div>
        <div class="rounded-xl bg-card p-3"><div class="text-[11px] text-zinc-500">Operating margin</div>
          <div class="tabular font-mono text-sm">${last.opm != null ? last.opm + "%" : "–"}</div>${spark(q.map((x) => x.opm), 140, 36)}</div>
      </div>
      ${cashTable((r.snapshot && r.snapshot.cash) || [])}
    </section>
    ${(a.narrative_vs_numbers || []).length ? `<section class="mb-6">${H("Story vs numbers")}<div class="rounded-2xl bg-card p-4">${list(a.narrative_vs_numbers)}</div></section>` : ""}
    ${(a.bull || []).length ? `<section class="mb-6 grid gap-3">
      <div class="rounded-2xl bg-emerald-500/10 p-4"><h3 class="mb-2 text-xs font-semibold uppercase tracking-wider text-emerald-300">Bull case</h3>${list(a.bull)}</div>
      <div class="rounded-2xl bg-rose-500/10 p-4"><h3 class="mb-2 text-xs font-semibold uppercase tracking-wider text-rose-300">Bear case</h3>${list(a.bear)}</div>
    </section>` : ""}
    <p class="mb-6 text-[11px] leading-relaxed text-zinc-600">Sources: ${(r.calls || []).map((c) =>
      `<a href="${esc(c.url)}" target="_blank" rel="noopener" class="underline">${esc(c.date)} call</a>`).join(" · ")}
      · <a href="${esc(r.source_page)}" target="_blank" rel="noopener" class="underline">reported financials</a> · generated ${fmtTime(r.generated)}</p>`;
}

function cashTable(cash) {
  if (!cash.length) return "";
  const first = cash[0], lastY = cash[cash.length - 1];
  return `<div class="mt-2 rounded-xl bg-card p-3">
    <div class="mb-1 text-[11px] text-zinc-500">Do profits turn into cash? Operating cash flow ÷ net profit (Rs cr)</div>
    <div class="grid grid-cols-4 text-[11px] text-zinc-500"><span>Year</span>
      <span class="text-right">Op. cash</span><span class="text-right">Profit</span><span class="text-right">Ratio</span></div>
    ${cash.map((c) => `<div class="tabular grid grid-cols-4 border-t border-line py-1 font-mono text-xs">
      <span class="font-sans text-zinc-400">${esc(c.year)}</span><span class="text-right">${fmtNum(c.cfo)}</span>
      <span class="text-right">${fmtNum(c.net_profit)}</span>
      <span class="text-right ${c.conversion != null && c.conversion < 0.8 ? "text-accent" : ""}">${c.conversion ?? "–"}×</span></div>`).join("")}
    <p class="pt-1 text-[11px] text-zinc-500">Borrowings ${fmtNum(first.borrowings)} → ${fmtNum(lastY.borrowings)} cr</p>
  </div>`;
}

// ================= Watch (settings) =================
async function renderSettings() {
  const s = getSettings();
  view.innerHTML = `
    <header class="mb-6"><h1 class="text-3xl font-semibold tracking-tight">Watch</h1>
      <p class="text-sm text-zinc-400">You decide what counts as unusual. FINN watches for it.</p></header>
    <section class="mb-6 rounded-2xl bg-card p-4">
      <label class="flex justify-between text-sm"><span>Daily price move</span><span class="tabular font-mono" id="pv">±${s.price}%</span></label>
      <input id="price" type="range" min="1" max="10" step="0.5" value="${s.price}" class="mt-2 w-full">
      <label class="mt-5 flex justify-between text-sm"><span>Volume vs 20-day average</span><span class="tabular font-mono" id="vv">${s.vol}×</span></label>
      <input id="vol" type="range" min="1.2" max="5" step="0.1" value="${s.vol}" class="mt-2 w-full">
    </section>
    <section class="mb-6 rounded-2xl bg-card p-4">
      <p class="mb-3 text-sm">Alert me about these filings</p>
      <div class="flex flex-wrap gap-2">${ALL_TYPES.map((t) =>
        `<button data-act="type" data-t="${esc(t)}" class="rounded-full px-3 py-1 text-xs ${s.types.includes(t) ? "bg-accent text-ink" : "bg-zinc-800 text-zinc-400"}">${esc(LABELS[t] || t)}</button>`).join("")}</div>
    </section>
    <section class="mb-6 flex items-center justify-between rounded-2xl bg-card p-4 text-sm">
      <span>Handled items <span class="font-mono text-zinc-500">${getDone().size}</span></span>
      <button data-act="reset-done" class="text-xs text-sky-400">Bring them back</button>
    </section>
    <section id="cost" class="mb-6"></section>
    <p class="text-xs text-zinc-500">Saved on this phone automatically.</p>`;
  const price = document.getElementById("price"), vol = document.getElementById("vol");
  price.oninput = () => { s.price = Number(price.value); document.getElementById("pv").textContent = `±${s.price}%`; saveSettings(s); };
  vol.oninput = () => { s.vol = Number(vol.value); document.getElementById("vv").textContent = `${s.vol}×`; saveSettings(s); };
  try {
    const m = await api("/api/meta");
    const box = document.getElementById("cost");
    if (box && m.filings) box.innerHTML = `${H("How FINN spent AI on the last refresh")}
      <div class="grid grid-cols-3 gap-2 text-center">
        ${[["Filings", m.filings], ["Sorted by rules", m.by_rules], ["AI calls", m.ai_calls]].map(([k, v]) =>
          `<div class="rounded-xl bg-card p-3"><div class="tabular font-mono text-lg">${esc(v ?? "–")}</div><div class="text-[11px] text-zinc-500">${k}</div></div>`).join("")}
      </div>
      <p class="mt-2 text-[11px] leading-relaxed text-zinc-500">Keyword rules first, a cheap model in batches for the rest, a strong model only for the promise ledger. Every answer is cached, so a re-run costs nothing.</p>`;
  } catch (e) {}
}

function toggleType(t) {
  const s = getSettings();
  s.types = s.types.includes(t) ? s.types.filter((x) => x !== t) : [...s.types, t];
  saveSettings(s);
  renderSettings();
}

// ================= start =================
const [startTab, startArg] = location.hash.slice(1).split("/");
go(VIEWS[startTab] ? startTab : "today", startArg ? decodeURIComponent(startArg).toUpperCase() : undefined);
refreshAlertBadge();
