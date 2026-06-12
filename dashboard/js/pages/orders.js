import { api } from "../api.js";
import { sk, pageHero, ICONS } from "../ui.js";

const pill = (s) => `<span class="pill pill-${s}">${(s || "").replace(/_/g, " ")}</span>`;

export async function renderOrders(el) {
  async function load() {
    const status = el.querySelector("#statusFilter")?.value || "";
    const q = status ? `?status=${status}` : "";
    el.querySelector("#rows").innerHTML = sk.rows(9);
    const orders = await api.get(`/orders${q}`);
    const body = el.querySelector("#rows");
    if (!orders.length) {
      body.innerHTML = `<tr><td colspan="9" class="muted" style="text-align:center;padding:1.5rem">No orders yet.</td></tr>`;
      return;
    }
    body.innerHTML = orders
      .map(
        (o) => `
      <tr>
        <td>${o.id}</td>
        <td><span class="badge">${o.provider}</span></td>
        <td class="mono">${o.external_order_id}</td>
        <td>${o.marketplace_sku}</td>
        <td>${pill(o.status)}</td>
        <td>${o.fulfillment_source ?? "—"}</td>
        <td class="mono">${o.attempts}</td>
        <td style="max-width:220px;color:var(--muted)">${o.last_error ?? ""}</td>
        <td><button class="btn btn-sm" data-retry="${o.id}">Retry</button></td>
      </tr>`,
      )
      .join("");
    el.querySelectorAll("[data-retry]").forEach((b) => {
      b.onclick = async () => {
        b.disabled = true;
        await api.post(`/orders/${b.dataset.retry}/retry`);
        load();
      };
    });
  }

  el.innerHTML = `
    ${pageHero({ icon: ICONS.orders, title: "Orders", subtitle: "Live order pipeline — filter, inspect, and retry fulfillment.", grad: "grad-blue" })}
    <div class="card" style="margin-bottom:1rem">
      <div class="field-row">
        <span class="field-label" style="margin:0">Status</span>
        <select id="statusFilter" class="input">
          <option value="">All statuses</option>
          ${["received", "processing", "awaiting_stock", "delivered", "failed", "cancelled"]
            .map((s) => `<option value="${s}">${s.replace(/_/g, " ")}</option>`)
            .join("")}
        </select>
      </div>
    </div>
    <div class="card">
      <table>
        <thead><tr><th>ID</th><th>Provider</th><th>Ext ID</th><th>SKU</th>
          <th>Status</th><th>Source</th><th>Tries</th><th>Error</th><th></th></tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>`;
  el.querySelector("#statusFilter").onchange = load;
  await load();
}
