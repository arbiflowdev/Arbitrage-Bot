import { api } from "../api.js";
import { pageHero, ICONS } from "../ui.js";

export async function renderConnections(el) {
  const [marketplaces, sys] = await Promise.all([
    api.get("/marketplaces"),
    api.get("/system/status"),
  ]);
  const dot = (on) => `<span class="pill ${on ? "pill-delivered" : "pill-failed"}">${on ? "online" : "halted"}</span>`;

  el.innerHTML = `
    ${pageHero({ icon: ICONS.connections, title: "Connections", subtitle: "System controls and marketplace connection status.", grad: "grad-fuchsia" })}
    <div class="card" style="margin-bottom:1rem">
      <div class="card-head">Global kill-switch</div>
      <p class="muted" style="font-size:.88rem;margin:0 0 .85rem">Instantly halts BOTH the pricing engine and the fulfillment pipeline.</p>
      <div class="field-row" style="justify-content:space-between">
        <div class="field-row">
          <span>Pricing ${dot(sys.pricing_enabled)}</span>
          <span>Fulfillment ${dot(sys.fulfillment_enabled)}</span>
          <span class="badge">mode · ${sys.mode}</span>
        </div>
        <div class="field-row">
          <button class="btn btn-danger" id="stopAll">⏻ Stop everything</button>
          <button class="btn btn-ghost" id="startAll">Resume</button>
        </div>
      </div>
    </div>
    <div class="card" style="margin-bottom:1rem">
      <div class="card-head">Marketplace connections</div>
      <table><thead><tr><th>Provider</th><th>Mode</th><th>Status</th></tr></thead>
        <tbody>${marketplaces
          .map((m) => {
            const name = m.provider ?? m.name ?? "—";
            const mode = m.mode ?? sys.mode;
            const configured = m.configured ?? m.connected ?? m.has_credentials;
            const status =
              configured === undefined
                ? `<span class="badge">${sys.mode}</span>`
                : `<span class="pill ${configured ? "pill-delivered" : "pill-warning"}">${configured ? "configured" : "not set"}</span>`;
            return `<tr><td><span class="badge">${name}</span></td><td>${mode}</td><td>${status}</td></tr>`;
          })
          .join("")}</tbody></table>
    </div>`;

  el.querySelector("#stopAll").onclick = async () => {
    await api.post("/system/kill-switch", { enabled: false });
    renderConnections(el);
  };
  el.querySelector("#startAll").onclick = async () => {
    await api.post("/system/kill-switch", { enabled: true });
    renderConnections(el);
  };
}
