import { api } from "../api.js";
import { sk, pageHero, ICONS } from "../ui.js";

const LVL = { INFO: "pill-info", WARNING: "pill-warning", ERROR: "pill-failed", CRITICAL: "pill-critical" };

export async function renderLogs(el) {
  async function load() {
    const level = el.querySelector("#level")?.value || "";
    el.querySelector("#rows").innerHTML = sk.rows(4);
    const logs = await api.get(`/logs${level ? `?level=${level}` : ""}`);
    el.querySelector("#rows").innerHTML = logs.length
      ? logs
          .map(
            (l) => `<tr><td class="mono" style="white-space:nowrap">${new Date(l.created_at).toLocaleString()}</td>
        <td><span class="pill ${LVL[l.level] || ""}">${l.level}</span></td><td>${l.source}</td>
        <td style="color:var(--muted)">${l.message}</td></tr>`,
          )
          .join("")
      : `<tr><td colspan="4" class="muted" style="text-align:center;padding:1.5rem">No log events recorded.</td></tr>`;
  }
  el.innerHTML = `
    ${pageHero({ icon: ICONS.logs, title: "Logs & errors", subtitle: "Recorded operational events and errors.", grad: "grad-slate" })}
    <div class="card" style="margin-bottom:1rem"><div class="field-row">
      <span class="field-label" style="margin:0">Level</span>
      <select id="level" class="input"><option value="">All levels</option>
        ${["INFO", "WARNING", "ERROR", "CRITICAL"].map((l) => `<option>${l}</option>`).join("")}
      </select>
    </div></div>
    <div class="card"><table><thead><tr><th>Time</th><th>Level</th><th>Source</th><th>Message</th></tr></thead>
      <tbody id="rows"></tbody></table></div>`;
  el.querySelector("#level").onchange = load;
  await load();
}
