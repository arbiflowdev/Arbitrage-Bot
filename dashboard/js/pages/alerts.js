import { api } from "../api.js";
import { sk, pageHero, ICONS } from "../ui.js";

const pill = (s) => `<span class="pill pill-${s}">${s}</span>`;

export async function renderAlerts(el) {
  async function load() {
    const status = el.querySelector("#status")?.value || "open";
    el.querySelector("#rows").innerHTML = sk.rows(7);
    const alerts = await api.get(`/alerts?status=${status}`);
    const body = el.querySelector("#rows");
    if (!alerts.length) {
      body.innerHTML = `<tr><td colspan="7" class="muted" style="text-align:center;padding:1.5rem">No ${status} alerts. 🎉</td></tr>`;
      return;
    }
    body.innerHTML = alerts
      .map(
        (a) => `
      <tr>
        <td>${a.id}</td>
        <td>${pill(a.severity)}</td>
        <td><span class="badge">${a.type}</span></td>
        <td>${a.title}</td>
        <td style="color:var(--muted)">${a.message}</td>
        <td>${pill(a.status)}</td>
        <td style="white-space:nowrap">
          <button class="btn btn-sm btn-ghost" data-ack="${a.id}">Ack</button>
          <button class="btn btn-sm btn-danger" data-res="${a.id}">Resolve</button>
        </td>
      </tr>`,
      )
      .join("");
    el.querySelectorAll("[data-ack]").forEach((b) => {
      b.onclick = async () => {
        await api.post(`/alerts/${b.dataset.ack}/acknowledge`);
        load();
      };
    });
    el.querySelectorAll("[data-res]").forEach((b) => {
      b.onclick = async () => {
        await api.post(`/alerts/${b.dataset.res}/resolve`);
        load();
      };
    });
  }

  el.innerHTML = `
    ${pageHero({ icon: ICONS.alerts, title: "Alerts", subtitle: "Operational alerts — acknowledge to silence, resolve when handled.", grad: "grad-rose" })}
    <div class="card" style="margin-bottom:1rem">
      <div class="field-row">
        <span class="field-label" style="margin:0">Showing</span>
        <select id="status" class="input">
          ${["open", "acknowledged", "resolved"].map((s) => `<option>${s}</option>`).join("")}
        </select>
      </div>
    </div>
    <div class="card">
      <table>
        <thead><tr><th>ID</th><th>Severity</th><th>Type</th>
          <th>Title</th><th>Message</th><th>Status</th><th></th></tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>`;
  el.querySelector("#status").onchange = load;
  await load();
}
