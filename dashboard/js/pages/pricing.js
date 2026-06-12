import { api } from "../api.js";
import { pageHero, ICONS } from "../ui.js";

export async function renderPricing(el) {
  const status = await api.get("/pricing/status");
  const history = await api.get("/repricing-history?limit=25");
  el.innerHTML = `
    ${pageHero({ icon: ICONS.pricing, title: "Pricing engine", subtitle: "Automated repricing — run scans, preview decisions, control the kill-switch.", grad: "grad-emerald" })}
    <div class="card" style="margin-bottom:1rem">
      <div class="field-row" style="justify-content:space-between">
        <div class="field-row">
          <span class="pill ${status.enabled ? "pill-delivered" : "pill-failed"}">${status.enabled ? "enabled" : "disabled"}</span>
          <span class="badge">mode · ${status.mode}</span>
          <span class="badge">dry-run · ${status.dry_run}</span>
        </div>
        <div class="field-row">
          <button class="btn btn-ghost" id="preview">Preview</button>
          <button class="btn" id="scan">Run scan</button>
          <button class="btn ${status.enabled ? "btn-danger" : ""}" id="toggle">${status.enabled ? "Disable engine" : "Enable engine"}</button>
        </div>
      </div>
      <div class="field-row" style="margin-top:.85rem;gap:1.4rem;color:var(--muted);font-size:.85rem">
        <span>Min profit <b class="mono" style="color:var(--text)">${status.min_profit_absolute}</b> / ${status.min_profit_margin_percent}%</span>
        <span>Undercut <b class="mono" style="color:var(--text)">${status.undercut_amount}</b></span>
        <span>Scan interval ${status.scan_interval_seconds}s</span>
      </div>
      <p id="msg" class="mono" style="font-size:.8rem;margin-top:.6rem;color:var(--muted)"></p>
    </div>
    <div class="card">
      <div class="card-head">Recent repricing decisions</div>
      <table><thead><tr><th>ID</th><th>Provider</th><th>SKU</th><th>Old</th><th>New</th><th>Decision</th></tr></thead>
      <tbody>${
        history.length
          ? history
              .map(
                (h) => `<tr><td>${h.id}</td><td><span class="badge">${h.provider ?? "—"}</span></td>
            <td>${h.marketplace_sku ?? "—"}</td><td class="mono">${h.old_price ?? "—"}</td>
            <td class="mono">${h.new_price ?? "—"}</td><td>${h.decision ?? h.reason ?? "—"}</td></tr>`,
              )
              .join("")
          : `<tr><td colspan="6" class="muted" style="text-align:center;padding:1.5rem">No repricing runs yet.</td></tr>`
      }</tbody></table>
    </div>`;
  const msg = el.querySelector("#msg");
  el.querySelector("#scan").onclick = async () => {
    msg.textContent = "Scanning…";
    const r = await api.post("/pricing/scan");
    msg.textContent = "Scan result · " + JSON.stringify(r);
  };
  el.querySelector("#preview").onclick = async () => {
    msg.textContent = "Previewing…";
    const r = await api.post("/pricing/preview");
    msg.textContent = "Preview · " + JSON.stringify(r);
  };
  el.querySelector("#toggle").onclick = async () => {
    await api.post("/pricing/kill-switch", { enabled: !status.enabled });
    renderPricing(el);
  };
}
