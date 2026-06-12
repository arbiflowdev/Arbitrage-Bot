import { api } from "../api.js";

const I = (p) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const ICON = {
  revenue: I(`<line x1="12" y1="2" x2="12" y2="22"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>`),
  delivered: I(`<path d="M21.8 10A10 10 0 1 1 17 3.3"/><polyline points="22 4 12 14.01 9 11.01"/>`),
  stock: I(`<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>`),
  wallet: I(`<path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/>`),
};

const STATUS_COLORS = {
  received: "#94a3b8", processing: "#60a5fa", awaiting_stock: "#f59e0b",
  delivered: "#22c55e", failed: "#f43f5e", cancelled: "#cbd5e1",
};

function statCard(icon, label, value) {
  return `
    <div class="stat">
      <div class="stat-icon">${icon}</div>
      <div><div class="stat-label">${label}</div><div class="stat-value">${value}</div></div>
    </div>`;
}

export async function renderOverview(el) {
  const s = await api.get("/dashboard/summary");
  const engChip = (on) =>
    `<span class="pill ${on ? "pill-delivered" : "pill-failed"}">${on ? "online" : "halted"}</span>`;

  el.innerHTML = `
    <div class="globe-hero">
      <div class="globe-hero-copy">
        <span class="hero-badge"><span class="live-dot"></span> Live network</span>
        <h2>Global marketplace network</h2>
        <p>Automated arbitrage across Kinguin, G2G &amp; Eneba — priced, sourced, and delivered in real time.</p>
        <div class="hero-stats">
          <div><div class="hs-num">${s.revenue_today}</div><div class="hs-lbl">Revenue today</div></div>
          <div><div class="hs-num">${s.delivered_today}</div><div class="hs-lbl">Delivered</div></div>
          <div><div class="hs-num">${s.inventory_available}</div><div class="hs-lbl">In stock</div></div>
        </div>
      </div>
      <div class="hero-rings"><span></span><span></span><span></span><span></span><span></span></div>
    </div>

    <div class="stat-grid">
      ${statCard(ICON.revenue, "Revenue today", s.revenue_today)}
      ${statCard(ICON.delivered, "Delivered today", s.delivered_today)}
      ${statCard(ICON.stock, "Available stock", s.inventory_available)}
      ${statCard(ICON.wallet, "Wallet total", s.wallet_total)}
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-head">Orders by status</div>
        <canvas id="ordersChart" height="200"></canvas>
      </div>
      <div class="card">
        <div class="card-head">System &amp; alerts</div>
        <div class="field-row" style="margin-bottom:1rem">
          <span class="pill pill-critical">${s.alerts.critical} critical</span>
          <span class="pill pill-warning">${s.alerts.warning} warning</span>
          <span class="pill pill-info">${s.alerts.info} info</span>
        </div>
        <table><tbody>
          <tr><td style="color:var(--muted)">Pricing engine</td><td>${engChip(s.engine.pricing_enabled)}</td></tr>
          <tr><td style="color:var(--muted)">Fulfillment</td><td>${engChip(s.engine.fulfillment_enabled)}</td></tr>
          <tr><td style="color:var(--muted)">Dry run</td><td><span class="badge">${s.engine.dry_run}</span></td></tr>
        </tbody></table>
      </div>
    </div>`;

  const labels = Object.keys(s.orders);
  new Chart(el.querySelector("#ordersChart"), {
    type: "doughnut",
    data: {
      labels,
      datasets: [
        {
          data: labels.map((k) => s.orders[k]),
          backgroundColor: labels.map((k) => STATUS_COLORS[k] || "#94a3b8"),
          borderColor: "#ffffff",
          borderWidth: 2,
          hoverOffset: 6,
        },
      ],
    },
    options: {
      cutout: "62%",
      plugins: {
        legend: {
          position: "right",
          labels: { color: "#475569", boxWidth: 12, font: { family: "Geist" } },
        },
      },
    },
  });
}
