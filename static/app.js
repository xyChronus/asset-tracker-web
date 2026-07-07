/* Asset Tracker frontend - crypto | pse | global */
"use strict";

/* ---------------------------------------------------------- state */

const CUR = { crypto: "$", pse: "₱", global: "$" };
const MKT_LABEL = { crypto: "Crypto", pse: "PSE Stocks", global: "Global Stocks" };

const STYLES = [
  { v: "scalper", label: "Scalper", desc: "Very short holds. Acts on fast signals, takes small profits quickly (~4%), and barely weighs company fundamentals." },
  { v: "day", label: "Day Trader", desc: "Intraday moves. Quick to act, takes profit around +6%, light on fundamentals." },
  { v: "swing", label: "Swing Trader", desc: "Days to weeks. The balanced default — takes profit around +25% and blends technicals, news and fundamentals." },
  { v: "long", label: "Long-Term Investor", desc: "Months and up. Patient and fundamentals-led; rarely sells on short-term dips, takes profit much later." },
];
const styleLabel = (v) => (STYLES.find(s => s.v === v) || STYLES[2]).label;

const charts = {};
const state = {
  market: localStorage.getItem("mkt") || "crypto",
  tab: "dashboard",
  currency: localStorage.getItem("curmode") || "native",
  style: "swing",
  editingTx: null,
  pvHours: 168,
  chartHours: 168,
  chartAsset: {},        // per market
  txSide: "buy",
  watch: {},             // per-market watchlist cache
  filter: "",
};

const M = () => "/api/" + state.market;
const cur = () => CUR[state.market];

/* ---------------------------------------------------------- helpers */

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (r.status === 401) {
    location.href = "/login";
    throw new Error("signed out");
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.status + " " + r.statusText);
  return data;
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

let fxRate = null; // USD -> PHP, refreshed on every screen refresh

function fmtMoney(v, compact) {
  if (v == null || isNaN(v)) return "—";
  let c = CUR[state.market];
  if (state.currency !== "native" && fxRate) {
    const want = state.currency === "USD" ? "$" : "₱";
    if (want !== c) v = (c === "$") ? v * fxRate : v / fxRate;
    c = want;
  }
  const a = Math.abs(v);
  if (compact) {
    if (a >= 1e12) return c + (v / 1e12).toFixed(2) + "T";
    if (a >= 1e9) return c + (v / 1e9).toFixed(2) + "B";
    if (a >= 1e6) return c + (v / 1e6).toFixed(2) + "M";
    if (a >= 1e3) return c + (v / 1e3).toFixed(1) + "K";
  }
  let dp = 2;
  if (a > 0 && a < 0.0001) dp = 8;
  else if (a > 0 && a < 0.01) dp = 6;
  else if (a > 0 && a < 1) dp = 4;
  return (v < 0 ? "-" + c : c) + Math.abs(v).toLocaleString("en-US",
    { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

function fmtNum(v, dp) {
  if (v == null || isNaN(v)) return "—";
  return v.toLocaleString("en-US", { maximumFractionDigits: dp == null ? 2 : dp });
}

function fmtQty(v) {
  if (v == null || isNaN(v)) return "—";
  const a = Math.abs(v);
  const dp = a >= 100 ? 2 : a >= 1 ? 4 : 8;
  return v.toLocaleString("en-US", { maximumFractionDigits: dp });
}

function pctSpan(v, dp) {
  if (v == null || isNaN(v)) return '<span class="muted">—</span>';
  const cls = v >= 0 ? "pos" : "neg";
  const arrow = v >= 0 ? "▲" : "▼";
  return `<span class="${cls}">${arrow} ${Math.abs(v).toFixed(dp == null ? 2 : dp)}%</span>`;
}

function moneySpan(v) {
  if (v == null || isNaN(v)) return '<span class="muted">—</span>';
  const cls = v >= 0 ? "pos" : "neg";
  return `<span class="${cls}">${v >= 0 ? "+" : ""}${fmtMoney(v)}</span>`;
}

function timeAgo(ms) {
  if (!ms) return "";
  const s = Math.floor((Date.now() - ms) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
}

function linkHtml(url, text) {
  const u = String(url || "");
  return /^https?:\/\//i.test(u)
    ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(text)}</a>`
    : `<span>${esc(text)}</span>`;
}

function fngSpan(fng) {
  if (!fng || fng.value == null) return "";
  const v = fng.value;
  const cls = v < 45 ? "neg" : v <= 55 ? "muted" : "pos";
  return `<span class="${cls}"><b>${v}</b> — ${esc(fng.label)}</span>`;
}

function sigBadge(sig) {
  if (!sig) return '<span class="badge wait">…</span>';
  const cls = sig.action.toLowerCase().replace(/ /g, "-");
  return `<span class="badge ${cls}">${sig.action}</span>`;
}

// Numbered buy/sell score: positive = buy-leaning, negative = sell-leaning.
function scorePill(v, dp) {
  if (v == null || isNaN(v)) return "";
  const n = dp ? (+v).toFixed(dp) : Math.round(v);
  const cls = v > 0 ? "pos" : v < 0 ? "neg" : "muted";
  return `<span class="score-pill ${cls}" title="Buy/sell score — higher is more bullish, lower more bearish">${v > 0 ? "+" : ""}${n}</span>`;
}

let toastTimer;
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.style.display = "none"), 5000);
}

function drawSpark(canvas, points) {
  const dpr = window.devicePixelRatio || 1;
  const w = 110, h = 30;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  if (!points || points.length < 2) return;
  const min = Math.min(...points), max = Math.max(...points);
  const span = max - min || 1;
  const up = points[points.length - 1] >= points[0];
  ctx.strokeStyle = up ? "#22c55e" : "#ef4444";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = (i / (points.length - 1)) * (w - 2) + 1;
    const y = h - 3 - ((p - min) / span) * (h - 6);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
}

function makeChart(id, cfg) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), cfg);
}

/* ------------------------------------------- searchable asset picker */

function setupCombo(baseId, onPick) {
  const box = document.getElementById(baseId + "-combo");
  const input = document.getElementById(baseId + "-input");
  const hidden = document.getElementById(baseId);
  const list = document.getElementById(baseId + "-list");
  let options = [];
  let shown = [];
  let hi = -1;

  const label = o => `${o.name} (${o.symbol})`;

  function render(filterText) {
    const f = (filterText || "").trim().toUpperCase();
    shown = !f ? options.slice() : options.filter(o =>
      (o.symbol || "").toUpperCase().includes(f) ||
      (o.name || "").toUpperCase().includes(f));
    if (f) {
      const rank = o => {
        const s = (o.symbol || "").toUpperCase(), n = (o.name || "").toUpperCase();
        if (s === f) return 0;
        if (s.startsWith(f)) return 1;
        if (n.startsWith(f)) return 2;
        return 3;
      };
      shown.sort((a, b) => rank(a) - rank(b) || (a.name || "").localeCompare(b.name || ""));
    }
    hi = -1;
    list.innerHTML = shown.length
      ? shown.slice(0, 250).map((o, i) =>
          `<div class="combo-item" data-i="${i}"><b>${esc(o.symbol)}</b><span>${esc(o.name)}</span></div>`).join("")
      : '<div class="combo-empty">No match — check the spelling or ticker</div>';
    list.querySelectorAll(".combo-item").forEach(el => {
      // mousedown (not click) so it fires before the input's blur
      el.onmousedown = (e) => { e.preventDefault(); pick(shown[+el.dataset.i]); };
    });
  }

  function highlight() {
    list.querySelectorAll(".combo-item").forEach((el, i) => {
      el.classList.toggle("hi", i === hi);
      if (i === hi) el.scrollIntoView({ block: "nearest" });
    });
  }

  function open() { box.classList.add("open"); }
  function close() { box.classList.remove("open"); }

  function pick(o, silent) {
    if (!o) return;
    hidden.value = o.value;
    input.value = label(o);
    close();
    if (!silent && onPick) onPick(o.value);
  }

  input.onfocus = () => { input.select(); render(""); open(); };
  input.oninput = () => { render(input.value); open(); };
  input.onblur = () => setTimeout(() => {
    close();
    const o = options.find(x => x.value === hidden.value);
    input.value = o ? label(o) : "";
  }, 150);
  input.onkeydown = (e) => {
    const max = Math.min(shown.length, 250) - 1;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!box.classList.contains("open")) { render(input.value); open(); }
      hi = Math.min(hi + 1, max); highlight();
    } else if (e.key === "ArrowUp") {
      e.preventDefault(); hi = Math.max(hi - 1, 0); highlight();
    } else if (e.key === "Enter") {
      e.preventDefault(); pick(shown[hi >= 0 ? hi : 0]); input.blur();
    } else if (e.key === "Escape") {
      close(); input.blur();
    }
  };

  return {
    setOptions(opts) {
      options = opts || [];
      const cur = options.find(o => o.value === hidden.value);
      if (cur) input.value = label(cur);
      else if (options.length) pick(options[0], true);
      else { hidden.value = ""; input.value = ""; }
    },
    set(value) {
      const o = options.find(x => x.value === value);
      if (o) pick(o, true);
    },
    get value() { return hidden.value; },
  };
}

if (window.Chart) {
  Chart.defaults.color = "#8b93a7";
  Chart.defaults.borderColor = "#252d3f";
  Chart.defaults.font.family = '"Segoe UI", system-ui, sans-serif';
}

/* ---------------------------------------------------------- header/status */

async function loadHeader() {
  try {
    const p = await api(M() + "/portfolio");
    const s = p.summary;
    document.getElementById("header-stats").innerHTML = s.total_worth != null
      ? `<span class="hv">${fmtMoney(s.total_worth)}</span>` +
        `<span class="muted">= ${fmtMoney(s.value)} invested + ${fmtMoney(s.cash)} cash</span>` +
        `<span>${pctSpan(s.change_24h_pct)} 24h</span>`
      : `<span class="hv">${fmtMoney(s.value)}</span>` +
        `<span>${pctSpan(s.change_24h_pct)} 24h</span>` +
        `<span class="muted">P/L ${moneySpan(s.unrealized + s.realized)}</span>`;
  } catch (e) { /* cosmetic */ }
  try {
    const st = await api(M() + "/status");
    const dot = document.getElementById("status-dot");
    const txt = document.getElementById("status-text");
    const age = st.quotes_updated ? Date.now() - st.quotes_updated : null;
    const staleMs = state.market === "crypto" ? 3 * 60000 : 40 * 60000;
    if (age != null && age < staleMs) {
      dot.className = "status-dot ok";
      txt.textContent = "live · " + timeAgo(st.quotes_updated);
    } else if (age != null) {
      dot.className = "status-dot warn";
      txt.textContent = "stale · " + timeAgo(st.quotes_updated);
    } else {
      dot.className = "status-dot warn";
      txt.textContent = "waiting for first price update…";
    }
    if (st.source_error) {
      dot.className = "status-dot err";
      txt.textContent = "data source issue — showing cached data";
    }
  } catch (e) {
    document.getElementById("status-dot").className = "status-dot err";
    document.getElementById("status-text").textContent = "server unreachable";
  }
}

/* ---------------------------------------------------------- dashboard */

async function loadDashboard() {
  const [p, hist] = await Promise.all([
    api(M() + "/portfolio"),
    api(M() + "/portfolio_history?hours=" + state.pvHours),
  ]);
  const s = p.summary;

  const cards = [];
  if (s.total_worth != null) {
    cards.push({ label: "Total Wallet Worth", val: fmtMoney(s.total_worth),
      sub: s.budget_return_pct != null
        ? pctSpan(s.budget_return_pct) + ` <span class="muted">vs your ${fmtMoney(s.budget)} budget</span>`
        : '<span class="muted">positions + cash</span>' });
    cards.push({ label: "Cash Available", val: s.cash >= 0 ? fmtMoney(s.cash) : `<span class="neg">${fmtMoney(s.cash)}</span>`,
      sub: `<span class="muted">of a ${fmtMoney(s.budget)} budget</span>` });
  }
  cards.push(
    { label: "Portfolio Value", val: fmtMoney(s.value), sub: pctSpan(s.change_24h_pct) + ` <span class="muted">(${moneySpan(s.change_24h_usd)} 24h)</span>` },
    { label: "Cost Basis (open)", val: fmtMoney(s.cost), sub: '<span class="muted">what your current positions cost you</span>' },
    { label: "Unrealized P/L", val: moneySpan(s.unrealized), sub: pctSpan(s.unrealized_pct) },
    { label: "Realized P/L", val: moneySpan(s.realized), sub: '<span class="muted">locked in from sells</span>' },
    { label: "Total P/L", val: moneySpan(s.unrealized + s.realized), sub: '<span class="muted">realized + unrealized</span>' },
  );
  document.getElementById("dash-cards").innerHTML = cards
    .map(c => `<div class="card"><div class="label">${c.label}</div><div class="val">${c.val}</div><div class="sub">${c.sub}</div></div>`).join("");

  const pts = hist.points || [];
  makeChart("pv-chart", {
    type: "line",
    data: {
      labels: pts.map(x => new Date(x[0]).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit" })),
      datasets: [
        { label: "Value", data: pts.map(x => x[1]), borderColor: "#f7931a",
          backgroundColor: "rgba(247,147,26,.08)", fill: true, pointRadius: 0, borderWidth: 2, tension: .25 },
        { label: "Net invested", data: pts.map(x => x[2]), borderColor: "#8b93a7",
          borderDash: [5, 4], pointRadius: 0, borderWidth: 1.5, tension: 0 },
      ],
    },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { boxWidth: 12 } },
        tooltip: { callbacks: { label: c => c.dataset.label + ": " + fmtMoney(c.parsed.y) } } },
      scales: { x: { ticks: { maxTicksLimit: 7, maxRotation: 0 } },
                y: { ticks: { callback: v => fmtMoney(v, true) } } },
    },
  });

  const held = p.holdings.filter(h => h.value != null);
  makeChart("alloc-chart", {
    type: "doughnut",
    data: {
      labels: held.map(h => h.symbol || h.name),
      datasets: [{ data: held.map(h => h.value),
        backgroundColor: ["#f7931a", "#60a5fa", "#22c55e", "#a78bfa", "#f472b6", "#facc15", "#34d399", "#fb923c", "#38bdf8", "#f87171"],
        borderColor: "#151a24", borderWidth: 2 }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { position: "right" },
        tooltip: { callbacks: { label: c => " " + c.label + ": " + fmtMoney(c.parsed) +
          (s.value ? " (" + (c.parsed / s.value * 100).toFixed(1) + "%)" : "") } } },
    },
  });

  const ht = document.getElementById("holdings-table");
  if (!p.holdings.length) {
    ht.innerHTML = `<tr><td class="empty-note">No open positions in ${MKT_LABEL[state.market]} yet. Add a buy on the Portfolio tab.</td></tr>`;
  } else {
    ht.innerHTML = `<thead><tr><th>Asset</th><th>Quantity</th><th>Avg Buy</th><th>Price</th>
      <th>Day</th><th>Value</th><th>Unrealized P/L</th><th>P/L %</th></tr></thead><tbody>` +
      p.holdings.map(h => `<tr>
        <td><div class="coin-cell">${h.image ? `<img src="${esc(h.image)}">` : ""}<span class="nm">${esc(h.name)}</span><span class="sym">${esc(h.symbol)}</span></div></td>
        <td>${fmtQty(h.qty)}</td>
        <td>${fmtMoney(h.avg_buy)}</td>
        <td>${fmtMoney(h.price)}</td>
        <td>${pctSpan(h.chg_24h)}</td>
        <td><b>${fmtMoney(h.value)}</b></td>
        <td>${moneySpan(h.unrealized)}</td>
        <td>${pctSpan(h.unrealized_pct)}</td>
      </tr>`).join("") + "</tbody>";
  }

  loadMarketPanels("dash");
  loadDashNews();
  loadTodayPlan();
}

async function loadTodayPlan() {
  const a = await api(M() + "/advisor").catch(() => null);
  const el = document.getElementById("today-plan");
  if (!a || !a.recommendations) {
    el.innerHTML = '<span class="empty-note">Analyzing… first results appear a few minutes after startup.</span>';
    return;
  }
  const actionable = a.recommendations.filter(r => !["HOLD", "WATCH"].includes(r.action));
  const actions = actionable.filter(r => !r.dismissed).slice(0, 3);
  const doneCount = actionable.filter(r => r.dismissed).length;
  if (a.market_open === false) {
    el.innerHTML = `<div class="plan-item"><span class="badge wait">MARKET CLOSED</span>
      <span>Buy/sell suggestions pause while the market is closed — they resume
      ${esc(a.next_open || "when it reopens")}.</span></div>`;
    return;
  }
  if (!actions.length) {
    el.innerHTML = `<div class="plan-item"><span class="badge hold">ALL CLEAR</span>
      <span>${doneCount ? `All ${doneCount} suggestion(s) done for today — nice work.`
        : `No strong buy or sell setups in ${MKT_LABEL[state.market]} right now — sitting tight is the play.`}</span></div>`;
    return;
  }
  el.innerHTML = actions.map(r => `<div class="plan-item">
    ${sigBadge(r)}
    <span><b>${esc(r.name)}</b>${r.usd ? " — about " + fmtMoney(r.usd) : ""}
      <span class="muted">· ${esc((r.reasons && r.reasons[0]) || "")}</span></span>
    <span class="plan-btns">
      ${r.usd ? `<button class="accept-btn" data-accept="${esc(r.asset_id)}" data-action="${esc(r.action)}"
        data-usd="${r.usd}" data-name="${esc(r.name)}" title="Log this trade at the current live price">Accept</button>` : ""}
      <button class="done-btn" data-done="${esc(r.asset_id)}" data-action="${esc(r.action)}"
        title="Hide this suggestion for today without logging anything">✓</button>
    </span>
  </div>`).join("");
  bindDoneButtons("today-plan", loadTodayPlan);
}

function glList(list, priceKey, chgKey) {
  return (list || []).map(x => `<div class="gl-item">
      <div class="gl-coin">${x.image ? `<img src="${esc(x.image)}">` : ""}<b>${esc((x.symbol || "").toUpperCase())}</b>
      <span class="muted">${fmtMoney(x[priceKey])}</span></div>${pctSpan(x[chgKey])}</div>`).join("")
    || '<div class="empty-note">waiting for market data…</div>';
}

async function loadMarketPanels(prefix) {
  const m = await api(M() + "/market");
  const sumEl = document.getElementById(prefix === "dash" ? "market-summary" : "market-summary-2");
  if (m.summary) sumEl.textContent = m.summary;

  const gEl = document.getElementById(prefix + "-gainers");
  const lEl = document.getElementById(prefix + "-losers");
  if (m.kind === "crypto") {
    gEl.innerHTML = glList(m.gainers, "current_price", "chg_24h");
    lEl.innerHTML = glList(m.losers, "current_price", "chg_24h");
  } else if (m.kind === "pse") {
    gEl.innerHTML = glList(m.gainers, "price", "chg_pct");
    lEl.innerHTML = glList(m.losers, "price", "chg_pct");
  } else {
    gEl.innerHTML = glList(m.gainers, "price", "chg_24h");
    lEl.innerHTML = glList(m.losers, "price", "chg_24h");
  }

  if (prefix === "dash") {
    const gs = document.getElementById("global-stats");
    if (m.kind === "crypto") {
      const g = m.global || {};
      const mcap = (g.total_market_cap || {}).usd;
      const stats = mcap ? [
        ["Market Cap", fmtMoney(mcap, true)],
        ["24h Change", (g.market_cap_change_percentage_24h_usd || 0).toFixed(2) + "%"],
        ["BTC Dom.", ((g.market_cap_percentage || {}).btc || 0).toFixed(1) + "%"],
        ["ETH Dom.", ((g.market_cap_percentage || {}).eth || 0).toFixed(1) + "%"],
      ] : [];
      if (m.fng) stats.push(["Fear & Greed", fngSpan(m.fng)]);
      gs.innerHTML = stats.map(x => `<div class="mini-stat"><span>${x[0]}</span><b>${x[1]}</b></div>`).join("");
    } else if (m.kind === "pse") {
      gs.innerHTML = [
        ["Advancers", m.advancers], ["Decliners", m.decliners],
        ["Unchanged", m.unchanged], ["Listed Companies", m.companies],
      ].map(x => `<div class="mini-stat"><span>${x[0]}</span><b>${x[1] == null ? "—" : x[1]}</b></div>`).join("");
    } else {
      const idx = m.indices || {};
      gs.innerHTML = Object.keys(idx).map(k =>
        `<div class="mini-stat"><span>${esc(k)}</span><b>${fmtNum(idx[k].price)} ${pctSpan(idx[k].chg_pct, 1)}</b></div>`).join("");
    }
  }
  return m;
}

async function loadDashNews() {
  const n = await api(M() + "/news?limit=6");
  document.getElementById("dash-news").innerHTML = n.items.length
    ? n.items.map(newsItemHtml).join("")
    : '<div class="empty-note">Fetching news… check back in a minute.</div>';
}

/* ---------------------------------------------------------- advisor */

function recCard(r) {
  const conv = Math.max(-10, Math.min(10, r.conviction || 0));
  const pos = ((conv + 10) / 20 * 100).toFixed(0);
  const h = r.holding;
  const amount = r.usd
    ? `<div class="rec-amount">${r.action.includes("BUY") ? "Buy" : "Sell"} about <b>${fmtMoney(r.usd)}</b>${r.qty ? ` <span class="muted">(≈ ${fmtQty(r.qty)} ${esc(r.symbol)})</span>` : ""}</div>`
    : "";
  const holdLine = h
    ? `<div class="rec-holding muted">You hold ${fmtMoney(h.value)} (${h.alloc_pct}% of portfolio${h.unrealized_pct != null ? ", " + (h.unrealized_pct >= 0 ? "up " : "down ") + Math.abs(h.unrealized_pct).toFixed(0) + "%" : ""})</div>`
    : "";
  const f = r.fundamentals || {};
  const chips = [];
  if (f.pe != null) chips.push("P/E " + fmtNum(f.pe, 1));
  if (f.div_yield != null) chips.push("Yield " + fmtNum(f.div_yield, 2) + "%");
  if (f.div_ex_date) chips.push("Ex-div " + esc(f.div_ex_date));
  const arts = (r.articles || []).map(a =>
    `<div class="rec-art"><span class="${a.sentiment > 0 ? "pos" : a.sentiment < 0 ? "neg" : "muted"}">${a.sentiment > 0 ? "▲" : a.sentiment < 0 ? "▼" : "•"}</span>
     ${linkHtml(a.link, a.title)}
     <span class="muted">· ${esc(a.source)}</span></div>`).join("");
  const actionable = !["HOLD", "WATCH"].includes(r.action);
  const acceptBtn = actionable && r.usd
    ? `<button class="accept-btn" data-accept="${esc(r.asset_id)}" data-action="${esc(r.action)}"
         data-usd="${r.usd}" data-name="${esc(r.name)}"
         title="Log this trade in your portfolio at the current live price">Accept</button>`
    : "";
  const doneBtn = actionable
    ? `<button class="done-btn" data-done="${esc(r.asset_id)}" data-action="${esc(r.action)}"
         title="Hide this suggestion for today without logging anything">✓ Done</button>`
    : "";
  return `<div class="rec-card">
    <div class="sig-head">
      <div class="sig-coin">${r.image ? `<img src="${esc(r.image)}">` : ""}${esc(r.name)}
        <span class="muted">${fmtMoney(r.price)}</span></div>
      <div class="head-right">${sigBadge(r)}${scorePill(r.conviction, 1)}${acceptBtn}${doneBtn}</div>
    </div>
    ${amount}${holdLine}
    <div class="conv-bar" title="Conviction: ${conv}">
      <div class="conv-marker" style="left:${pos}%"></div>
    </div>
    <div class="conv-labels"><span>strong sell</span><span class="muted">confidence: ${esc(r.confidence || "")}</span><span>strong buy</span></div>
    ${chips.length ? `<div class="sig-chips">${chips.map(x => `<div class="mini-stat">${x}</div>`).join("")}</div>` : ""}
    <ul>${(r.reasons || []).map(x => `<li>${esc(x)}</li>`).join("")}</ul>
    ${arts ? `<div class="rec-arts">${arts}</div>` : ""}
  </div>`;
}

async function loadAdvisor() {
  const a = await api(M() + "/advisor");
  if (!a || !a.recommendations) {
    document.getElementById("advisor-briefing").textContent =
      "Still analyzing — results appear a few minutes after startup, once prices, history and news are in.";
    return;
  }
  document.getElementById("advisor-briefing").textContent = a.briefing || "";
  document.getElementById("advisor-updated").textContent =
    a.updated ? "updated " + timeAgo(a.updated) : "";
  const ms = a.market_sentiment || {};
  const actionable = a.recommendations.filter(r => !["HOLD", "WATCH"].includes(r.action));
  const actions = actionable.filter(r => !r.dismissed);
  const doneCount = actionable.length - actions.length;
  document.getElementById("advisor-stats").innerHTML = [
    ["Market", a.market_open === false ? '<span class="neg">CLOSED</span>' : '<span class="pos">OPEN</span>'],
    ["Trading Style", esc(a.style_label || styleLabel(state.style))],
    ["News Sentiment", esc(ms.label || "—") + (ms.score != null ? ` (${ms.score > 0 ? "+" : ""}${ms.score})` : "")],
    ["Suggestions", actions.length + " action(s)"],
    ["Done Today", doneCount + " ✓"],
  ].map(x => `<div class="mini-stat"><span>${x[0]}</span><b>${x[1]}</b></div>`).join("");

  const rest = a.recommendations.filter(r => ["HOLD", "WATCH"].includes(r.action));
  document.getElementById("advisor-actions").innerHTML = actions.length
    ? actions.map(recCard).join("")
    : (a.market_open === false
      ? `<div class="empty-note">The market is closed — buy/sell suggestions resume ${esc(a.next_open || "when it reopens")}. (Crypto never sleeps; stocks do.)</div>`
      : doneCount
      ? `<div class="empty-note">All ${doneCount} suggestion(s) marked done for today — nice work. New ones appear when the situation changes.</div>`
      : '<div class="empty-note">No buy or sell suggestions right now — the advisor only speaks up when several signals line up. That caution is a feature.</div>');
  document.getElementById("advisor-holds").innerHTML = rest.map(recCard).join("");
  bindDoneButtons("advisor-actions", loadAdvisor);
}

function bindDoneButtons(containerId, reload) {
  document.querySelectorAll(`#${containerId} .done-btn`).forEach(b => b.onclick = async () => {
    b.disabled = true;
    try {
      await api(M() + "/advisor/dismiss", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset_id: b.dataset.done, action: b.dataset.action }),
      });
      toast("Marked done — it'll stay hidden today unless the situation changes.");
      reload();
    } catch (e) { toast(e.message); b.disabled = false; }
  });
  document.querySelectorAll(`#${containerId} .accept-btn`).forEach(b => b.onclick = async () => {
    const side = ["BUY", "BUY MORE"].includes(b.dataset.action) ? "buy" : "sell";
    const usd = parseFloat(b.dataset.usd);
    const assets = await ensureWatch();
    const a = assets.find(x => x.asset_id === b.dataset.accept);
    const price = a && a.price != null ? a.price : null;
    if (!price || !usd) {
      toast("No live price right now — log it manually in the Portfolio tab.");
      return;
    }
    if (!confirm(`Log this ${side.toUpperCase()}: ${fmtMoney(usd)} of ${b.dataset.name} `
        + `at the current price of ${fmtMoney(price)}?\n\nTip: if your real fill price `
        + `differs on your exchange/broker, fix it afterwards with the ✎ button in the Portfolio tab.`)) return;
    b.disabled = true;
    try {
      await api(M() + "/transactions", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset_id: b.dataset.accept, side, price, value: usd }),
      });
      toast(`${side === "buy" ? "Buy" : "Sell"} logged ✓ — edit it in the Portfolio tab if your real fill differed.`);
      reload(); loadHeader();
    } catch (e) { toast(e.message); b.disabled = false; }
  });
}

/* ---------------------------------------------------------- portfolio */

async function loadPortfolio() {
  const [txs, p] = await Promise.all([api(M() + "/transactions"), api(M() + "/portfolio")]);

  const tt = document.getElementById("tx-table");
  tt.innerHTML = `<thead><tr><th>Date</th><th>Type</th><th>Asset</th><th>Quantity</th>
    <th>Price</th><th>Value</th><th>Fee</th><th></th></tr></thead><tbody>` +
    (txs.length ? txs.map(t => `<tr>
      <td>${esc(t.ts)}</td>
      <td><span class="${t.quantity >= 0 ? "pos" : "neg"}"><b>${esc(t.type)}</b></span></td>
      <td><div class="coin-cell"><span class="nm">${esc(t.name || t.asset_id)}</span></div></td>
      <td>${fmtQty(Math.abs(t.quantity))}</td>
      <td>${fmtMoney(t.price)}</td>
      <td>${fmtMoney(Math.abs(t.value))}</td>
      <td class="muted">${t.fee ? fmtMoney(t.fee) : "—"}</td>
      <td><button class="mini-btn" data-edit="${t.id}" title="Fix this entry">✎</button>
          <button class="del-btn" data-del="${t.id}">✕</button></td>
    </tr>`).join("") : '<tr><td class="empty-note">No transactions yet.</td></tr>') + "</tbody>";
  tt.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => {
    if (!confirm("Delete this transaction?")) return;
    await api(M() + "/transactions/" + b.dataset.del, { method: "DELETE" });
    if (state.editingTx === +b.dataset.del) endEditTx();
    loadPortfolio(); loadHeader();
  });
  tt.querySelectorAll("[data-edit]").forEach(b => b.onclick = () => {
    const t = txs.find(x => x.id === +b.dataset.edit);
    if (t) beginEditTx(t);
  });

  const ct = document.getElementById("closed-table");
  const rows = [...p.holdings.filter(h => Math.abs(h.realized) > 0.005), ...p.closed];
  ct.innerHTML = rows.length
    ? `<thead><tr><th>Asset</th><th>Bought</th><th>Sold</th><th>Realized P/L</th><th>Status</th></tr></thead><tbody>` +
      rows.map(h => `<tr>
        <td><div class="coin-cell"><span class="nm">${esc(h.name)}</span></div></td>
        <td>${fmtMoney(h.bought_usd)}</td><td>${fmtMoney(h.sold_usd)}</td>
        <td><b>${moneySpan(h.realized)}</b></td>
        <td class="muted">${h.qty > 1e-9 ? "still holding " + fmtQty(h.qty) : "closed"}</td>
      </tr>`).join("") + "</tbody>"
    : '<tr><td class="empty-note">Sell something to see realized profit/loss here.</td></tr>';

  fillAssetCombo(txCombo);
  const budgetEl = document.getElementById("wallet-budget");
  if (document.activeElement !== budgetEl) {
    budgetEl.value = p.summary.budget != null ? p.summary.budget : "";
  }
  budgetEl.placeholder = `e.g. ${state.market === "pse" ? "20000" : "5000"}`;
  document.getElementById("tx-price-label").textContent =
    `Price per ${state.market === "crypto" ? "coin" : "share"} (${cur()})`;
  const tsEl = document.getElementById("tx-ts");
  if (!tsEl.value) {
    const d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    tsEl.value = d.toISOString().slice(0, 16);
  }
}

async function ensureWatch() {
  if (!state.watch[state.market]) {
    try {
      state.watch[state.market] = (await api(M() + "/watchlist")).assets;
    } catch (e) { return []; }
  }
  return state.watch[state.market] || [];
}

async function fillAssetCombo(combo) {
  const assets = await ensureWatch();
  combo.setOptions(assets.map(a =>
    ({ value: a.asset_id, symbol: a.symbol, name: a.name })));
}

function beginEditTx(t) {
  state.editingTx = t.id;
  const isBuy = t.quantity >= 0;
  state.txSide = isBuy ? "buy" : "sell";
  document.querySelectorAll(".side-toggle button").forEach(b => {
    b.classList.toggle("active", b.dataset.side === state.txSide);
    b.disabled = true;
  });
  txCombo.set(t.asset_id);
  document.getElementById("tx-coin-input").disabled = true;
  document.getElementById("tx-ts").value = t.ts.replace(" ", "T");
  document.getElementById("tx-price").value = t.price;
  document.getElementById("tx-qty").value = Math.abs(t.quantity);
  document.getElementById("tx-value").value = Math.abs(t.value).toFixed(2);
  document.getElementById("tx-fee").value = t.fee || "";
  document.getElementById("tx-submit").textContent =
    `Save Changes (${isBuy ? "Buy" : "Sell"} · ${t.name || t.asset_id})`;
  document.getElementById("tx-cancel").style.display = "block";
  document.getElementById("tx-msg").innerHTML =
    '<span class="muted">Editing a logged trade — adjust the numbers and save.</span>';
  document.getElementById("tx-form").scrollIntoView({ behavior: "smooth", block: "center" });
}

function endEditTx() {
  state.editingTx = null;
  document.querySelectorAll(".side-toggle button").forEach(b => { b.disabled = false; });
  document.getElementById("tx-coin-input").disabled = false;
  document.getElementById("tx-qty").value = "";
  document.getElementById("tx-value").value = "";
  document.getElementById("tx-price").value = "";
  document.getElementById("tx-fee").value = "";
  document.getElementById("tx-submit").textContent =
    state.txSide === "buy" ? "Add Buy" : "Add Sell";
  document.getElementById("tx-cancel").style.display = "none";
  document.getElementById("tx-msg").textContent = "";
}

function setupTxForm() {
  const form = document.getElementById("tx-form");
  const qty = document.getElementById("tx-qty");
  const val = document.getElementById("tx-value");
  const price = document.getElementById("tx-price");

  document.querySelectorAll(".side-toggle button").forEach(b => b.onclick = () => {
    state.txSide = b.dataset.side;
    document.querySelectorAll(".side-toggle button").forEach(x => x.classList.toggle("active", x === b));
    document.getElementById("tx-submit").textContent = state.txSide === "buy" ? "Add Buy" : "Add Sell";
  });

  document.getElementById("tx-live").onclick = async () => {
    const assets = await ensureWatch();
    const a = assets.find(x => x.asset_id === document.getElementById("tx-coin").value);
    if (a && a.price != null) { price.value = a.price; sync("price"); }
    else toast("No live price yet for that asset — try again in a minute.");
  };

  const sync = (changed) => {
    const p = parseFloat(price.value);
    if (!p) return;
    if (changed === "qty" && qty.value) val.value = (parseFloat(qty.value) * p).toFixed(2);
    else if (changed === "value" && val.value) qty.value = (parseFloat(val.value) / p).toPrecision(8);
    else if (changed === "price" && qty.value) val.value = (parseFloat(qty.value) * p).toFixed(2);
  };
  qty.oninput = () => sync("qty");
  val.oninput = () => sync("value");
  price.oninput = () => sync("price");

  form.onsubmit = async (e) => {
    e.preventDefault();
    const msg = document.getElementById("tx-msg");
    msg.textContent = "";
    const editing = state.editingTx;
    try {
      const payload = {
        ts: document.getElementById("tx-ts").value,
        price: parseFloat(price.value || 0),
        quantity: parseFloat(qty.value || 0),
        value: parseFloat(val.value || 0),
        fee: parseFloat(document.getElementById("tx-fee").value || 0),
      };
      if (editing) {
        await api(M() + "/transactions/" + editing, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        endEditTx();
      } else {
        payload.asset_id = document.getElementById("tx-coin").value;
        payload.side = state.txSide;
        await api(M() + "/transactions", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        qty.value = ""; val.value = ""; document.getElementById("tx-fee").value = "";
      }
      msg.innerHTML = '<span class="pos">Saved ✓</span>';
      loadPortfolio(); loadHeader();
    } catch (err) {
      msg.innerHTML = `<span class="neg">${esc(err.message)}</span>`;
    }
  };
  document.getElementById("tx-cancel").onclick = endEditTx;
}

/* ---------------------------------------------------------- market tab */

async function loadMarket() {
  const m = await loadMarketPanels("market");
  const cardsEl = document.getElementById("market-cards");
  const title = document.getElementById("market-table-title");
  const table = document.getElementById("market-table");

  if (m.kind === "crypto") {
    const g = m.global || {};
    const mcap = (g.total_market_cap || {}).usd;
    const cryptoCards = mcap ? [
      { label: "Total Market Cap", val: fmtMoney(mcap, true), sub: pctSpan(g.market_cap_change_percentage_24h_usd) + ' <span class="muted">24h</span>' },
      { label: "24h Volume", val: fmtMoney((g.total_volume || {}).usd, true), sub: "" },
      { label: "BTC Dominance", val: ((g.market_cap_percentage || {}).btc || 0).toFixed(1) + "%", sub: "" },
      { label: "ETH Dominance", val: ((g.market_cap_percentage || {}).eth || 0).toFixed(1) + "%", sub: "" },
    ] : [];
    if (m.fng) {
      cryptoCards.push({
        label: "Fear & Greed", val: fngSpan(m.fng),
        sub: m.fng.yesterday != null
          ? `<span class="muted">yesterday: ${m.fng.yesterday}</span>` : "",
      });
    }
    cardsEl.innerHTML = cryptoCards.map(cardHtml).join("");
    title.textContent = "Top 100 by Market Cap";
    table.innerHTML =
      `<thead><tr><th>#</th><th>Coin</th><th>Price</th><th>1h</th><th>24h</th><th>7d</th>
       <th>24h Volume</th><th>Market Cap</th></tr></thead><tbody>` +
      (m.top100 || []).map(c => `<tr>
        <td class="muted">${c.market_cap_rank || ""}</td>
        <td><div class="coin-cell">${c.image ? `<img src="${esc(c.image)}">` : ""}<span class="nm">${esc(c.name)}</span><span class="sym">${esc((c.symbol || "").toUpperCase())}</span></div></td>
        <td>${fmtMoney(c.current_price)}</td>
        <td>${pctSpan(c.chg_1h, 1)}</td><td>${pctSpan(c.chg_24h, 1)}</td><td>${pctSpan(c.chg_7d, 1)}</td>
        <td class="muted">${fmtMoney(c.total_volume, true)}</td>
        <td>${fmtMoney(c.market_cap, true)}</td>
      </tr>`).join("") + "</tbody>";
  } else if (m.kind === "pse") {
    cardsEl.innerHTML = [
      { label: "Advancers", val: `<span class="pos">${m.advancers ?? "—"}</span>`, sub: "" },
      { label: "Decliners", val: `<span class="neg">${m.decliners ?? "—"}</span>`, sub: "" },
      { label: "Unchanged", val: m.unchanged ?? "—", sub: "" },
      { label: "Listed Companies", val: m.companies ?? "—", sub: m.as_of ? `<span class="muted">as of ${esc(String(m.as_of).slice(0, 16).replace("T", " "))}</span>` : "" },
    ].map(cardHtml).join("");
    title.textContent = "Most Active by Value Traded";
    table.innerHTML =
      `<thead><tr><th>Company</th><th>Price</th><th>Day</th><th>Volume</th><th>Value Traded</th></tr></thead><tbody>` +
      (m.most_active || []).map(t => `<tr>
        <td><div class="coin-cell"><span class="nm">${esc(t.name)}</span><span class="sym">${esc(t.symbol)}</span></div></td>
        <td>${fmtMoney(t.price)}</td>
        <td>${pctSpan(t.chg_pct, 2)}</td>
        <td class="muted">${fmtNum(t.volume, 0)}</td>
        <td>${fmtMoney(t.value, true)}</td>
      </tr>`).join("") + "</tbody>";
  } else {
    const idx = m.indices || {};
    cardsEl.innerHTML = Object.keys(idx).map(k => (
      { label: k, val: fmtNum(idx[k].price), sub: pctSpan(idx[k].chg_pct, 2) + ' <span class="muted">today</span>' }
    )).map(cardHtml).join("");
    title.textContent = "Your Global Watchlist — Day Moves";
    const assets = await ensureWatch();
    table.innerHTML =
      `<thead><tr><th>Stock</th><th>Price</th><th>Day</th><th>EPS</th><th>P/E</th><th>Div Yield</th></tr></thead><tbody>` +
      assets.map(a => `<tr>
        <td><div class="coin-cell">${a.image ? `<img src="${esc(a.image)}">` : ""}<span class="nm">${esc(a.name)}</span><span class="sym">${esc(a.symbol)}</span></div></td>
        <td>${fmtMoney(a.price)}</td>
        <td>${pctSpan(a.chg_24h, 2)}</td>
        <td>${fmtNum(a.eps)}</td>
        <td>${fmtNum(a.pe, 1)}</td>
        <td>${a.div_yield != null ? fmtNum(a.div_yield, 2) + "%" : "—"}</td>
      </tr>`).join("") + "</tbody>";
  }
}

function cardHtml(c) {
  return `<div class="card"><div class="label">${c.label}</div><div class="val">${c.val}</div><div class="sub">${c.sub}</div></div>`;
}

/* ---------------------------------------------------------- watchlist */

async function loadWatchlist() {
  state.watch[state.market] = null;
  const assets = await ensureWatch();
  const isPse = state.market === "pse";
  const isCrypto = state.market === "crypto";

  document.getElementById("watch-title").textContent =
    isPse ? `All PSE Companies (${assets.length})` : `${MKT_LABEL[state.market]} Watchlist`;
  document.getElementById("watch-add").style.display = isPse ? "none" : "flex";
  const filterEl = document.getElementById("watch-filter");
  filterEl.style.display = "block";
  document.getElementById("watch-note").textContent = isPse
    ? "Synced from the PSE Edge directory. EPS & P/E fill in gradually (a couple of hours on first run); dividend columns only show declared dividends whose ex-date hasn't passed — buy before that date to receive them."
    : "";

  const wt = document.getElementById("watch-table");
  const filter = (state.filter || "").toUpperCase();
  const rows = assets.filter(a => !filter ||
    a.symbol.toUpperCase().includes(filter) || (a.name || "").toUpperCase().includes(filter));

  if (isCrypto) {
    wt.innerHTML = `<thead><tr><th>Coin</th><th>Price</th><th>1h</th><th>24h</th><th>7d</th><th>30d</th>
      <th>Market Cap</th><th>7d Trend</th><th>Signal</th><th></th></tr></thead><tbody>` +
      rows.map((a, i) => `<tr>
        <td><div class="coin-cell">${a.image ? `<img src="${esc(a.image)}">` : ""}<span class="nm">${esc(a.name)}</span><span class="sym">${esc(a.symbol)}</span></div></td>
        <td><b>${fmtMoney(a.price)}</b></td>
        <td>${pctSpan(a.chg_1h, 1)}</td><td>${pctSpan(a.chg_24h, 1)}</td>
        <td>${pctSpan(a.chg_7d, 1)}</td><td>${pctSpan(a.chg_30d, 1)}</td>
        <td class="muted">${fmtMoney(a.market_cap, true)}</td>
        <td><canvas class="spark" id="spark-${i}"></canvas></td>
        <td>${sigBadge(a.signal)}${a.signal && a.signal.action !== "WAIT" ? " " + scorePill(a.signal.score) : ""}</td>
        <td><button class="del-btn" data-rm="${esc(a.asset_id)}">✕</button></td>
      </tr>`).join("") + "</tbody>";
  } else {
    const rm = isPse ? "" : "<th></th>";
    wt.innerHTML = `<thead><tr><th>${isPse ? "Company" : "Stock"}</th><th>Price</th><th>Day</th>
      ${isPse ? "<th>Value Traded</th>" : ""}<th>EPS</th><th>P/E</th><th>Div/Share</th><th>Div Yield</th><th>Ex-Date</th>
      <th>Trend</th><th>Signal</th>${rm}</tr></thead><tbody>` +
      rows.map((a, i) => `<tr>
        <td><div class="coin-cell">${a.image ? `<img src="${esc(a.image)}">` : ""}<span class="nm">${esc(a.name)}</span><span class="sym">${esc(a.symbol)}</span></div></td>
        <td><b>${fmtMoney(a.price)}</b></td>
        <td>${pctSpan(a.chg_24h, 2)}</td>
        ${isPse ? `<td class="muted">${a.value_traded ? fmtMoney(a.value_traded, true) : "—"}</td>` : ""}
        <td>${fmtNum(a.eps)}</td>
        <td>${fmtNum(a.pe, 1)}</td>
        <td>${a.div_ps != null ? fmtMoney(a.div_ps) : (a.div_rate ? esc(a.div_rate).slice(0, 24) : "—")}</td>
        <td>${a.div_yield != null ? fmtNum(a.div_yield, 2) + "%" : "—"}</td>
        <td class="muted">${esc(a.div_ex_date || "—")}</td>
        <td><canvas class="spark" id="spark-${i}"></canvas></td>
        <td>${sigBadge(a.signal)}${a.signal && a.signal.action !== "WAIT" ? " " + scorePill(a.signal.score) : ""}</td>
        ${isPse ? "" : `<td><button class="del-btn" data-rm="${esc(a.asset_id)}">✕</button></td>`}
      </tr>`).join("") + "</tbody>";
  }
  rows.forEach((a, i) => {
    const cnv = document.getElementById("spark-" + i);
    if (cnv) drawSpark(cnv, a.sparkline);
  });
  wt.querySelectorAll("[data-rm]").forEach(b => b.onclick = async () => {
    if (!confirm("Remove " + b.dataset.rm + " from the watchlist?")) return;
    await api(M() + "/watchlist/" + encodeURIComponent(b.dataset.rm), { method: "DELETE" });
    loadWatchlist();
  });

  // signal cards: holdings + anything with a non-HOLD signal (capped)
  const withSig = assets.filter(a => a.signal && a.signal.action !== "WAIT");
  const interesting = withSig.filter(a => a.signal.action !== "HOLD");
  const shown = (interesting.length ? interesting : withSig).slice(0, 24);
  document.getElementById("signal-grid").innerHTML = shown.map(a => {
    const s = a.signal;
    const ind = (s && s.indicators) || {};
    const chips = [];
    if (ind.rsi != null) chips.push(`RSI ${ind.rsi}`);
    if (ind.chg_24h != null) chips.push(`Day ${ind.chg_24h > 0 ? "+" : ""}${ind.chg_24h}%`);
    if (ind.macd_hist != null) chips.push(`MACD ${ind.macd_hist >= 0 ? "▲" : "▼"}`);
    return `<div class="signal-card">
      <div class="sig-head">
        <div class="sig-coin">${a.image ? `<img src="${esc(a.image)}">` : ""}${esc(a.name)}
          <span class="muted">${fmtMoney(a.price)}</span></div>
        <div class="head-right">${sigBadge(s)}${s && s.action !== "WAIT" ? scorePill(s.score) : ""}</div>
      </div>
      <ul>${((s && s.reasons) || ["Waiting for data…"]).map(r => `<li>${esc(r)}</li>`).join("")}</ul>
      ${chips.length ? `<div class="sig-chips">${chips.map(x => `<div class="mini-stat">${esc(x)}</div>`).join("")}</div>` : ""}
    </div>`;
  }).join("") || '<div class="empty-note">Signals appear once enough price history is stored for each asset.</div>';
}

function setupWatchTools() {
  document.getElementById("watch-add").onsubmit = async (e) => {
    e.preventDefault();
    const inp = document.getElementById("watch-query");
    if (!inp.value.trim()) return;
    try {
      const r = await api(M() + "/watchlist", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: inp.value.trim() }),
      });
      toast("Added " + r.added.name + " — prices & history will appear within a minute or two.");
      inp.value = "";
      loadWatchlist();
    } catch (err) { toast(err.message); }
  };
  document.getElementById("watch-filter").oninput = (e) => {
    state.filter = e.target.value;
    loadWatchlist();
  };
}

/* ---------------------------------------------------------- charts */

async function loadCharts() {
  await fillAssetCombo(chartCombo);
  const saved = state.chartAsset[state.market];
  if (saved) chartCombo.set(saved);
  state.chartAsset[state.market] = chartCombo.value;
  await drawHistory();
}

async function drawHistory() {
  const aid = state.chartAsset[state.market] || document.getElementById("chart-coin").value;
  if (!aid) return;
  const h = await api(`${M()}/history/${encodeURIComponent(aid)}?hours=${state.chartHours}`);
  const pts = h.points || [];
  const assets = await ensureWatch();
  const asset = assets.find(a => a.asset_id === aid) || {};

  makeChart("history-chart", {
    type: "line",
    data: {
      labels: pts.map(p => new Date(p[0]).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit" })),
      datasets: [{
        label: (asset.symbol || aid) + " price",
        data: pts.map(p => p[1]),
        borderColor: "#60a5fa", backgroundColor: "rgba(96,165,250,.08)",
        fill: true, pointRadius: 0, borderWidth: 2, tension: .2,
      }],
    },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: c => fmtMoney(c.parsed.y) } } },
      scales: { x: { ticks: { maxTicksLimit: 8, maxRotation: 0 } },
                y: { ticks: { callback: v => fmtMoney(v, true) } } },
    },
  });

  const indEl = document.getElementById("chart-indicators");
  if (!pts.length) {
    indEl.innerHTML = '<div class="empty-note">No stored history yet for this asset — it downloads/accumulates automatically. Crypto & global stocks fill within minutes; PSE builds during trading hours.</div>';
    return;
  }
  const s = asset.signal || {};
  const ind = s.indicators || {};
  const stats = [
    ["Current", fmtMoney(asset.price)],
    ["RSI", ind.rsi != null ? ind.rsi : "—"],
    ["Signal", s.action || "—"],
    ["Data points", pts.length],
  ];
  if (asset.pe != null) stats.push(["P/E", fmtNum(asset.pe, 1)]);
  if (asset.div_yield != null) stats.push(["Div Yield", fmtNum(asset.div_yield, 2) + "%"]);
  indEl.innerHTML = stats.map(x => `<div class="mini-stat"><span>${x[0]}</span><b>${x[1]}</b></div>`).join("");
}

/* ---------------------------------------------------------- news */

function newsItemHtml(it) {
  return `<div class="news-item">
    <div class="news-meta"><span class="badge src">${esc(it.source)}</span>
      <span>${timeAgo(it.published)}</span></div>
    <div class="news-title">${linkHtml(it.link, it.title)}</div>
    <div class="news-summary">${esc(it.summary)}</div>
  </div>`;
}

async function loadNews() {
  const sel = document.getElementById("news-source");
  const src = sel.value;
  const n = await api(M() + "/news?limit=120" + (src ? "&source=" + encodeURIComponent(src) : ""));
  const have = new Set([...sel.options].map(o => o.value));
  (n.sources || []).forEach(s => {
    if (!have.has(s)) {
      const o = document.createElement("option");
      o.value = s; o.textContent = s;
      sel.appendChild(o);
    }
  });
  document.getElementById("news-list").innerHTML = n.items.length
    ? n.items.map(newsItemHtml).join("")
    : '<div class="empty-note">Fetching news… the first load takes a minute or two.</div>';
}

/* ---------------------------------------------------------- tabs & boot */

// minimal markdown renderer for the changelog (headers, bullets, bold, code)
function renderMarkdown(md) {
  const inline = (s) => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  let html = "", inList = false;
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  (md || "").replace(/\r/g, "").split("\n").forEach(raw => {
    const line = raw.replace(/\s+$/, "");
    const m = line.match(/^(\s*)-\s+(.*)$/);
    if (!line.trim()) { closeList(); return; }
    if (/^#\s+/.test(line)) { closeList(); html += `<h2 class="cl-title">${inline(line.slice(2))}</h2>`; }
    else if (/^##\s+/.test(line)) { closeList(); html += `<h3 class="cl-ver">${inline(line.slice(3))}</h3>`; }
    else if (/^###\s+/.test(line)) { closeList(); html += `<h4 class="cl-sub">${inline(line.slice(4))}</h4>`; }
    else if (/^-{3,}\s*$/.test(line)) { closeList(); }
    else if (m) {
      if (!inList) { html += '<ul class="cl-list">'; inList = true; }
      html += `<li${m[1].length >= 2 ? ' class="cl-nested"' : ""}>${inline(m[2])}</li>`;
    } else { closeList(); html += `<p>${inline(line)}</p>`; }
  });
  closeList();
  return html;
}

async function loadChangelog() {
  const el = document.getElementById("changelog-body");
  try {
    const d = await api("/api/changelog");
    const parts = (d.markdown || "").split(/\n(?=## )/);   // split on version headers
    const head = parts.shift();                             // title + intro
    el.innerHTML = renderMarkdown([head, ...parts.reverse()].join("\n"));  // newest first
  } catch (e) {
    el.innerHTML = '<div class="empty-note">Could not load the changelog.</div>';
  }
}

const loaders = {
  dashboard: loadDashboard,
  advisor: loadAdvisor,
  portfolio: loadPortfolio,
  market: loadMarket,
  watchlist: loadWatchlist,
  charts: loadCharts,
  news: loadNews,
  changelog: loadChangelog,
};

function switchTab(name) {
  state.tab = name;
  document.querySelectorAll("nav#tabs button").forEach(b =>
    b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach(s =>
    s.classList.toggle("active", s.id === "tab-" + name));
  refresh();
}

function switchMarket(mkt) {
  if (state.editingTx) endEditTx();
  state.market = mkt;
  localStorage.setItem("mkt", mkt);
  state.watch[mkt] = null;
  state.filter = "";
  document.getElementById("watch-filter").value = "";
  // reset news source dropdown (sources differ per market)
  const sel = document.getElementById("news-source");
  sel.innerHTML = '<option value="">All sources</option>';
  document.querySelectorAll("#mkt-switch button").forEach(b =>
    b.classList.toggle("active", b.dataset.market === mkt));
  refresh();
}

async function refresh() {
  try { const fx = await api("/api/fx"); fxRate = fx.rate || null; } catch (e) { }
  try { await loaders[state.tab](); }
  catch (e) { console.error(e); toast("Couldn't refresh: " + e.message); }
  loadHeader();
}

document.querySelectorAll("nav#tabs button").forEach(b =>
  b.onclick = () => switchTab(b.dataset.tab));
document.querySelectorAll("#mkt-switch button").forEach(b =>
  b.onclick = () => switchMarket(b.dataset.market));
document.querySelectorAll("[data-goto]").forEach(b =>
  b.onclick = () => switchTab(b.dataset.goto));

document.querySelectorAll("#pv-range button").forEach(b => b.onclick = () => {
  state.pvHours = +b.dataset.hours;
  document.querySelectorAll("#pv-range button").forEach(x => x.classList.toggle("active", x === b));
  loadDashboard();
});
document.querySelectorAll("#chart-range button").forEach(b => b.onclick = () => {
  state.chartHours = +b.dataset.hours;
  document.querySelectorAll("#chart-range button").forEach(x => x.classList.toggle("active", x === b));
  drawHistory();
});
document.getElementById("news-source").onchange = loadNews;

const curSel = document.getElementById("cur-select");
curSel.value = state.currency;
curSel.onchange = () => {
  state.currency = curSel.value;
  localStorage.setItem("curmode", state.currency);
  refresh();
};

const txCombo = setupCombo("tx-coin");
const chartCombo = setupCombo("chart-coin", (v) => {
  state.chartAsset[state.market] = v;
  drawHistory();
});

document.getElementById("wallet-save").onclick = async () => {
  const msg = document.getElementById("wallet-msg");
  msg.textContent = "";
  try {
    await api(M() + "/wallet", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ budget: document.getElementById("wallet-budget").value }),
    });
    msg.innerHTML = '<span class="pos">Saved ✓</span>';
    loadPortfolio(); loadHeader();
  } catch (e) {
    msg.innerHTML = `<span class="neg">${esc(e.message)}</span>`;
  }
};

async function loadUser() {
  try {
    const me = await api("/api/me");
    state.style = me.trading_style || "swing";
    const el = document.getElementById("user-menu");
    el.innerHTML =
      `<span class="muted">${esc(me.name || me.email)}</span>` +
      (me.admin ? ' <button class="mini-btn" id="invite-btn" title="Create an invite code for a friend">+ Invite</button>'
                + ' <button class="mini-btn" id="members-btn" title="See who has joined and which invite codes are used">Members</button>' : "") +
      ' <button class="mini-btn" id="account-btn" title="Trading style and password">Account</button>' +
      ' <a class="mini-btn" href="/logout" title="Sign out">Logout</a>';
    const inv = document.getElementById("invite-btn");
    if (inv) inv.onclick = async () => {
      const r = await api("/api/invites", { method: "POST" });
      prompt("Invite code created — copy it and send it to your friend. "
        + "They'll enter it when registering:", r.code);
    };
    const mem = document.getElementById("members-btn");
    if (mem) mem.onclick = showMembers;
    document.getElementById("account-btn").onclick = showAccount;
  } catch (e) { /* the 401 handler redirects to /login */ }
}

async function showAccount() {
  const old = document.getElementById("account-overlay");
  if (old) old.remove();
  const overlay = document.createElement("div");
  overlay.id = "account-overlay";
  overlay.className = "app-overlay";
  overlay.innerHTML = `<div class="overlay-box">
    <div class="panel-head"><h3>Account</h3><button class="mini-btn" id="account-close">Close</button></div>

    <h4 class="acct-h">Trading style</h4>
    <p class="muted small-note">This tells the advisor how you like to trade — it adjusts
      how eager it is to buy, how fast it takes profit, and how much it weighs fundamentals.</p>
    <div class="style-list">
      ${STYLES.map(s => `<label class="style-opt">
        <input type="radio" name="style" value="${s.v}" ${s.v === state.style ? "checked" : ""}>
        <span><b>${esc(s.label)}</b><br><span class="muted">${esc(s.desc)}</span></span>
      </label>`).join("")}
    </div>
    <div class="form-msg" id="style-msg"></div>

    <h4 class="acct-h">Change password</h4>
    <label class="acct-field">Current password
      <input type="password" id="pw-current" autocomplete="current-password"></label>
    <label class="acct-field">New password (8+ characters)
      <input type="password" id="pw-new" autocomplete="new-password"></label>
    <button class="primary-btn small" id="pw-save">Update password</button>
    <div class="form-msg" id="pw-msg"></div>
  </div>`;
  document.body.appendChild(overlay);
  document.getElementById("account-close").onclick = () => overlay.remove();
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

  overlay.querySelectorAll('input[name="style"]').forEach(radio => radio.onchange = async () => {
    const msg = document.getElementById("style-msg");
    msg.textContent = "";
    try {
      await api("/api/settings", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trading_style: radio.value }),
      });
      state.style = radio.value;
      msg.innerHTML = `<span class="pos">Saved — advice now tuned for ${esc(styleLabel(radio.value))}.</span>`;
      state.watch[state.market] = null;
      if (state.tab === "advisor" || state.tab === "dashboard") refresh();
    } catch (e) { msg.innerHTML = `<span class="neg">${esc(e.message)}</span>`; }
  });

  document.getElementById("pw-save").onclick = async () => {
    const msg = document.getElementById("pw-msg");
    msg.textContent = "";
    try {
      await api("/api/change_password", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current: document.getElementById("pw-current").value,
          new: document.getElementById("pw-new").value,
        }),
      });
      msg.innerHTML = '<span class="pos">Password updated ✓</span>';
      document.getElementById("pw-current").value = "";
      document.getElementById("pw-new").value = "";
    } catch (e) { msg.innerHTML = `<span class="neg">${esc(e.message)}</span>`; }
  };
}

async function showMembers() {
  const d = await api("/api/members");
  const old = document.getElementById("members-overlay");
  if (old) old.remove();
  const overlay = document.createElement("div");
  overlay.id = "members-overlay";
  overlay.innerHTML = `<div class="members-box">
    <div class="panel-head"><h3>Members (${d.users.length})</h3>
      <button class="mini-btn" id="members-close">Close</button></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Name</th><th>Email</th><th>Joined</th><th></th></tr></thead>
      <tbody>${d.users.map(u => `<tr><td>${esc(u.name || "")}</td><td>${esc(u.email)}</td>
        <td class="muted">${esc(u.created || "")}</td>
        <td>${u.is_admin ? '<span class="badge hold">ADMIN</span>' : ""}</td></tr>`).join("")}</tbody>
    </table></div>
    <div class="panel-head" style="margin-top:14px"><h3>Invite codes</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Code</th><th>Created</th><th>Status</th></tr></thead>
      <tbody>${d.invites.map(i => `<tr><td><b>${esc(i.code)}</b></td>
        <td class="muted">${esc(i.created || "")}</td>
        <td>${i.used_by_email
          ? '<span class="muted">used by ' + esc(i.used_by_email) + " · " + esc(i.used_at || "") + "</span>"
          : '<span class="pos">available</span>'}</td></tr>`).join("")
        || '<tr><td class="empty-note" colspan="3">No invite codes yet.</td></tr>'}</tbody>
    </table></div>
  </div>`;
  document.body.appendChild(overlay);
  document.getElementById("members-close").onclick = () => overlay.remove();
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
}

setupTxForm();
setupWatchTools();
document.querySelectorAll("#mkt-switch button").forEach(b =>
  b.classList.toggle("active", b.dataset.market === state.market));
loadUser();
refresh();
setInterval(() => { state.watch[state.market] = null; refresh(); }, 60000);
