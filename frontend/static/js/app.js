// app.js — dashboard logic. No build step: plain fetch + Chart.js.

const state = {
  fuel: "petrol",
  year: "all",
  activeDirection: "all",
  showBrent: false,
  prices: [],
  brent: [],
  summary: null,
  events: [],
  spikes: [],
};

const COLORS = { petrol: "#E8A33D", diesel: "#2FBF9F", brent: "#7C8CE8" };

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed: ${url}`);
  return res.json();
}

function yearRange(year) {
  if (year === "all") return {};
  return { start: `${year}-01-01`, end: `${year}-12-31` };
}

async function loadAll() {
  const { start, end } = yearRange(state.year);
  const qs = new URLSearchParams({ fuel: state.fuel, ...(start ? { start, end } : {}) });

  const [prices, summary, spikes, events] = await Promise.all([
    getJSON(`/api/prices?${qs}`),
    getJSON(`/api/summary`),
    getJSON(`/api/spikes?fuel=${state.fuel}&top=30`),
    getJSON(`/api/events`),
  ]);
  state.prices = prices;
  state.summary = summary;
  state.spikes = spikes;
  state.events = events;

  renderTicker();
  renderStats();
  renderChart();
  renderEvents();
  renderSummary();
}

// ---------------- Ticker ----------------
function renderTicker() {
  const s = state.summary[state.fuel];
  const items = [
    `<span class="ticker-item">LATEST <strong>${s.latest_price}p</strong> (${s.latest_date})</span>`,
    `<span class="ticker-item ${s.change_since_start_pct >= 0 ? "up" : "down"}">SINCE JAN 2018 <strong>${s.change_since_start_pct > 0 ? "+" : ""}${s.change_since_start_pct}%</strong></span>`,
    `<span class="ticker-item">ALL-TIME HIGH <strong>${s.all_time_high}p</strong> · ${s.all_time_high_date}</span>`,
    `<span class="ticker-item">ALL-TIME LOW <strong>${s.all_time_low}p</strong> · ${s.all_time_low_date}</span>`,
    `<span class="ticker-item">AVG TAX SHARE <strong>${s.avg_tax_pct_of_price}%</strong> of pump price</span>`,
  ];
  const track = document.getElementById("tickerTrack");
  track.innerHTML = items.join("") + items.join(""); // duplicate for seamless loop
}

// ---------------- Stat cards ----------------
function renderStats() {
  const s = state.summary[state.fuel];
  const cards = [
    { label: "Latest price", value: `${s.latest_price}p`, delta: `as of ${s.latest_date}` },
    { label: "Change since Jan 2018", value: `${s.change_since_start_pct > 0 ? "+" : ""}${s.change_since_start_pct}%`, cls: s.change_since_start_pct >= 0 ? "up" : "down" },
    { label: "All-time high", value: `${s.all_time_high}p`, delta: s.all_time_high_date },
    { label: "All-time low", value: `${s.all_time_low}p`, delta: s.all_time_low_date },
    { label: "Avg. tax share of price", value: `${s.avg_tax_pct_of_price}%`, delta: "duty + VAT" },
  ];
  document.getElementById("statRow").innerHTML = cards.map(c => `
    <div class="stat-card">
      <div class="stat-label">${c.label}</div>
      <div class="stat-value">${c.value}</div>
      ${c.delta ? `<div class="stat-delta ${c.cls || ""} mono">${c.delta}</div>` : ""}
    </div>
  `).join("");
  document.getElementById("rangeLabel").textContent = state.year === "all" ? "· 2018–2026" : `· ${state.year}`;
}

// ---------------- Chart ----------------
let chartInstance = null;
function renderChart() {
  const ctx = document.getElementById("priceChart").getContext("2d");
  const labels = state.prices.map(p => p.date);
  const fuelColor = COLORS[state.fuel];

  // Get high-importance event dates for annotations
  const highImportanceCategories = ["geopolitical", "pandemic"];
  const highImportanceSpikes = state.spikes.filter(r => {
    if (!r.events.length) return false;
    return r.events.some(e => highImportanceCategories.includes(e.category));
  });
  const eventDates = new Set(highImportanceSpikes.map(r => r.date));

  const datasets = [
    {
      label: state.fuel === "petrol" ? "Petrol (p/litre)" : "Diesel (p/litre)",
      data: state.prices.map(p => p.price),
      borderColor: fuelColor,
      backgroundColor: fuelColor + "22",
      pointRadius: state.prices.map(p => {
        if (eventDates.has(p.date)) return 6; // Larger points for key events
        if (p.is_spike) return 4;
        return 0;
      }),
      pointBackgroundColor: state.prices.map(p => {
        if (eventDates.has(p.date)) return "#FF6B6B"; // Bright red for key events
        if (p.is_spike) return "#E1574F";
        return fuelColor;
      }),
      borderWidth: 2,
      tension: 0.15,
      fill: true,
      yAxisID: "y",
    },
  ];

  if (state.showBrent) {
    datasets.push({
      label: "Brent crude (USD/bbl, monthly)",
      data: state.prices.map(p => p.brent_usd_per_barrel),
      borderColor: COLORS.brent,
      borderDash: [4, 3],
      borderWidth: 1.5,
      pointRadius: 0,
      spanGaps: true,
      yAxisID: "y1",
    });
  }

  const scales = {
    x: { ticks: { color: "#8A93A6", maxTicksLimit: 12 }, grid: { color: "#1B2740" } },
    y: { ticks: { color: "#8A93A6" }, grid: { color: "#1B2740" }, title: { display: true, text: "pence/litre", color: "#8A93A6" } },
  };
  if (state.showBrent) {
    scales.y1 = { position: "right", ticks: { color: "#7C8CE8" }, grid: { display: false }, title: { display: true, text: "USD/barrel", color: "#7C8CE8" } };
  }

  if (chartInstance) chartInstance.destroy();
  chartInstance = new Chart(ctx, {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: "#EDEFF4", font: { family: "Inter" } } },
        tooltip: { 
          backgroundColor: "#17223A", 
          titleColor: "#EDEFF4", 
          bodyColor: "#D6DAE5", 
          borderColor: "#253150", 
          borderWidth: 1,
          callbacks: {
            afterBody: function(context) {
              const date = context[0].label;
              const spike = state.spikes.find(s => s.date === date);
              if (spike && spike.events.length) {
                const eventTitles = spike.events.map(e => e.title).join(", ");
                return `\n📍 ${eventTitles}`;
              }
              return "";
            }
          }
        },
      },
      scales,
    },
  });
}

// ---------------- Events / spikes ----------------
function renderDirFilters() {
  document.querySelectorAll(".dir-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.dir === state.activeDirection);
    btn.setAttribute("aria-pressed", btn.dataset.dir === state.activeDirection);
  });
}

function renderEvents() {
  renderDirFilters();
  let rows = state.spikes;
  
  // Filter by direction (rise/fall)
  if (state.activeDirection !== "all") {
    rows = rows.filter(r => r.direction === state.activeDirection);
  }
  
  // Filter for high-importance events only (war, pandemic, record highs/lows, biggest moves)
  const highImportanceCategories = ["geopolitical", "pandemic"];
  rows = rows.filter(r => {
    if (!r.events.length) return false; // Skip unmatched moves
    return r.events.some(e => highImportanceCategories.includes(e.category));
  });
  
  const list = document.getElementById("eventsList");
  const expandBtn = document.getElementById("expandEventsBtn");
  
  if (!rows.length) {
    list.innerHTML = `<p class="no-events">No high-importance price moves match this filter for the selected range.</p>`;
    list.classList.remove("collapsed");
    expandBtn.style.display = "none";
    return;
  }
  
  list.innerHTML = rows.map(r => {
    const eventDetails = r.events.map(e => {
      const full = state.events.find(ev => ev.id === e.id);
      const sources = full ? full.sources.map(s => `<a href="${s.url}" target="_blank" rel="noopener">${s.label}</a>`).join("") : "";
      return `<div>
        <div class="event-title">${e.title}</div>
        <p class="event-desc">${full ? full.summary : ""}</p>
        <div class="event-sources">${sources}</div>
      </div>`;
    }).join("");
    return `
      <div class="event-row">
        <div class="event-date mono">${r.date}</div>
        <div class="event-main">
          <span class="event-pct ${r.direction === "rise" ? "up" : "down"}">${r.pct_change > 0 ? "+" : ""}${r.pct_change}%</span>
          ${r.events.length ? eventDetails : `<span class="event-title">Unmatched price move</span><p class="event-desc">No researched event on file for this date yet.</p>`}
        </div>
        <div class="event-tag">${r.direction}</div>
      </div>
    `;
  }).join("");
  
  // Show expand button if there are more than 3 items
  if (rows.length > 3) {
    expandBtn.style.display = "block";
    list.classList.add("collapsed");
    expandBtn.textContent = "Show all moves";
  } else {
    expandBtn.style.display = "none";
    list.classList.remove("collapsed");
  }
  
  // Set up expand/collapse functionality
  expandBtn.onclick = function() {
    if (list.classList.contains("collapsed")) {
      list.classList.remove("collapsed");
      expandBtn.textContent = "Show fewer moves";
    } else {
      list.classList.add("collapsed");
      expandBtn.textContent = "Show all moves";
    }
  };
}

// ---------------- Auto-generated summary ----------------
function renderSummary() {
  const s = state.summary[state.fuel];
  const fuelName = state.fuel === "petrol" ? "Petrol" : "Diesel";
  const rangeLabel = state.year === "all" ? "the full Jan 2018 – Aug 2026 period" : `${state.year}`;
  const direction = s.change_since_start_pct >= 0 ? "risen" : "fallen";

  const topSpikes = [...state.spikes].sort((a, b) => Math.abs(b.pct_change) - Math.abs(a.pct_change)).slice(0, 3);
  const spikeLines = topSpikes.map(sp => {
    const evNames = sp.events.map(e => e.title).join(", ");
    return `  • ${sp.date}: ${sp.pct_change > 0 ? "+" : ""}${sp.pct_change}% — ${evNames || "no matched event on file"}`;
  }).join("\n");

  const shortText =
`${fuelName} prices over ${rangeLabel}: from ${s.start_price}p (${s.start_date}) to ${s.latest_price}p (${s.latest_date}), a ${Math.abs(s.change_since_start_pct)}% ${direction === "risen" ? "rise" : "fall"}.
Range across the dataset: ${s.all_time_low}p (${s.all_time_low_date}) to ${s.all_time_high}p (${s.all_time_high_date}).
On average, duty and VAT together make up ${s.avg_tax_pct_of_price}% of the pump price.`;

  const fullText =
`This analysis draws from two primary data sources: the UK government's weekly road fuel price statistics (gov.uk) covering ULSP (unleaded petrol) and ULSD (diesel) pump prices from January 2018 to August 2026, and the Federal Reserve Economic Data (FRED) series for Brent crude spot prices in USD per barrel. The data was cleaned to handle missing values, merged across different frequencies using a backward-join to align monthly Brent readings with weekly fuel prices, and analyzed to detect statistically significant price movements. This system compares retail fuel prices at UK pumps against the global Brent crude benchmark, examining how major geopolitical and economic events correlate with price volatility. The two primary fuel types analyzed are petrol (ULSP) and diesel (ULSD), both used extensively in road transport.

Brent crude serves as the international reference price for oil traded globally. The most dramatic price movements in this dataset were driven by major geopolitical conflicts. The largest weekly rise occurred on 14 March 2022 (+6.89%), coinciding with Russia's invasion of Ukraine. This triggered fears of sanctions on one of the world's largest oil exporters, causing Brent crude to spike toward $130/bbl as markets anticipated supply disruptions. The second-largest rise on 16 March 2026 (+6.56%) and the third-largest on 6 April 2026 (+5.8%) both occurred during the US-Israel-Iran war, when Iran effectively closed the Strait of Hormuz—a chokepoint handling roughly one-fifth of global oil flow. These events demonstrate how conflicts affecting key oil infrastructure or major producing nations can cause rapid price increases through supply fears and actual physical disruptions. Conversely, the most significant price falls typically occurred during demand collapses, such as the COVID-19 pandemic in 2020 when global lockdowns evaporated road fuel demand, causing prices to plummet to their lowest levels in the dataset.

This analysis is not financial advice but rather an examination of how real-world scenarios influence commodity pricing. The project was developed to analyze the global effects on commodities, specifically demonstrating how geopolitical instability, pandemics, and policy decisions can cascade through supply chains to affect retail prices. The findings underscore that fuel prices sit at the intersection of global commodity markets, currency movements, tax policy, and geopolitics—multiple factors that often move simultaneously, making attribution complex. While the dashboard flags correlations between events and price movements, it does not claim causation, as crude benchmarks, exchange rates, OPEC+ policies, and domestic tax changes frequently interact in ways that make simple cause-and-effect relationships difficult to isolate.

Largest flagged weekly moves in this selection:
${spikeLines || "  • none flagged in this range"}

Read with care: a shared date range is a correlation, not proof of causation — several factors often move together (crude benchmark, exchange rate, OPEC+ policy, UK duty changes). Where sources are linked above, exact wording and figures should be checked against the original reporting.`;

  document.getElementById("summaryText").innerHTML = `
    <div class="summary-short">${shortText}</div>
    <button class="read-more-btn" id="readMoreBtn">Read more</button>
    <div class="summary-full" id="summaryFull" style="display: none;">${fullText.replace(/\n/g, '<br>')}</div>
  `;

  document.getElementById("readMoreBtn").addEventListener("click", function() {
    const fullText = document.getElementById("summaryFull");
    const btn = this;
    if (fullText.style.display === "none") {
      fullText.style.display = "block";
      btn.textContent = "Show less";
    } else {
      fullText.style.display = "none";
      btn.textContent = "Read more";
    }
  });
}

// ---------------- Controls ----------------
function bindControls() {
  document.querySelectorAll(".fuel-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".fuel-btn").forEach(b => { b.classList.remove("active"); b.setAttribute("aria-selected", "false"); });
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      state.fuel = btn.dataset.fuel;
      loadAll();
    });
  });

  document.querySelectorAll(".year-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".year-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.year = btn.dataset.year;
      loadAll();
    });
  });

  document.getElementById("brentToggle").addEventListener("change", (e) => {
    state.showBrent = e.target.checked;
    loadAll();
  });

  document.querySelectorAll(".dir-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      state.activeDirection = btn.dataset.dir;
      renderEvents();
    });
  });
}

bindControls();
loadAll().catch(err => {
  console.error(err);
  document.getElementById("summaryText").textContent = "Could not load data — is the Flask server running?";
});
