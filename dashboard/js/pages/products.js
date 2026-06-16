import { api } from "../api.js";
import { sk, pageHero, ICONS } from "../ui.js";

const MARKETPLACES = ["kinguin", "g2g", "eneba"];

export async function renderProducts(el) {
  async function loadMappings(pid) {
    const box = el.querySelector("#mapBox");
    if (!pid) {
      box.innerHTML = `<p class="muted">Select a product to manage its marketplace SKUs.</p>`;
      return;
    }
    box.innerHTML = sk.rows(2);
    const maps = await api.get(`/products/${pid}/mappings`);
    box.innerHTML = `
      <table><thead><tr><th>Marketplace</th><th>Marketplace SKU</th><th>URL</th><th></th></tr></thead>
        <tbody>${
          maps.length
            ? maps
                .map(
                  (m) => `<tr>
            <td><span class="badge">${m.marketplace}</span></td>
            <td class="mono">${m.marketplace_sku}</td>
            <td class="muted" style="max-width:240px;overflow:hidden;text-overflow:ellipsis">${m.marketplace_url ?? "—"}</td>
            <td><button class="btn btn-sm btn-danger" data-del="${m.id}">Remove</button></td></tr>`,
                )
                .join("")
            : `<tr><td colspan="4" class="muted" style="text-align:center;padding:1rem">No marketplace SKUs linked yet.</td></tr>`
        }</tbody></table>
      <div class="field-row" style="margin-top:.8rem;flex-wrap:wrap;gap:.5rem">
        <select id="mMarket" class="input">${MARKETPLACES.map((m) => `<option value="${m}">${m}</option>`).join("")}</select>
        <input id="mSku" class="input" placeholder="marketplace SKU / product id" />
        <input id="mUrl" class="input" placeholder="listing URL (optional)" style="min-width:220px" />
        <button class="btn" id="addMap">Link SKU</button>
        <span id="mMsg" style="font-size:.85rem"></span>
      </div>`;

    box.querySelectorAll("[data-del]").forEach((b) => {
      b.onclick = async () => {
        await api.del(`/products/${pid}/mappings/${b.dataset.del}`);
        loadMappings(pid);
      };
    });
    box.querySelector("#addMap").onclick = async () => {
      const msg = box.querySelector("#mMsg");
      try {
        await api.post(`/products/${pid}/mappings`, {
          marketplace: box.querySelector("#mMarket").value,
          marketplace_sku: box.querySelector("#mSku").value.trim(),
          marketplace_url: box.querySelector("#mUrl").value.trim() || null,
        });
        loadMappings(pid);
      } catch (e) {
        msg.innerHTML = `<span style="color:var(--rose)">${e.message}</span>`;
      }
    };
  }

  async function load() {
    el.querySelector("#rows").innerHTML = sk.rows(5);
    const products = await api.get("/products");
    const sel = el.querySelector("#mapProduct");
    sel.innerHTML =
      `<option value="">— select —</option>` +
      products.map((p) => `<option value="${p.id}">${p.name} (${p.internal_sku})</option>`).join("");
    const body = el.querySelector("#rows");
    body.innerHTML = products.length
      ? products
          .map(
            (p) => `<tr>
        <td>${p.id}</td><td class="mono">${p.internal_sku}</td><td>${p.name}</td>
        <td>${p.platform ?? "—"}</td><td>${p.region ?? "—"}</td>
        <td>${p.is_active ? "✅" : "⛔"}</td></tr>`,
          )
          .join("")
      : `<tr><td colspan="6" class="muted" style="text-align:center;padding:1.5rem">No products yet — add one below.</td></tr>`;
  }

  el.innerHTML = `
    ${pageHero({ icon: ICONS.products, title: "Products", subtitle: "Your internal catalogue. Add a product, then link its marketplace SKUs — Inventory & Pricing use these.", grad: "grad-violet" })}
    <div class="card mb-4">
      <div class="card-head">Add product</div>
      <div class="grid md:grid-cols-5 gap-2">
        <input id="internal_sku" class="input" placeholder="internal SKU (unique)" />
        <input id="name" class="input" placeholder="name" />
        <input id="platform" class="input" placeholder="platform (e.g. Steam)" />
        <input id="region" class="input" placeholder="region (e.g. EU)" />
        <button class="btn" id="create">Create</button>
      </div>
      <p id="msg" class="text-sm mt-2"></p>
    </div>
    <div class="card mb-4">
      <table>
        <thead><tr><th>ID</th><th>Internal SKU</th><th>Name</th><th>Platform</th><th>Region</th><th>Active</th></tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
    <div class="card">
      <div class="card-head">Marketplace SKU mappings</div>
      <div class="field-row" style="margin-bottom:.8rem">
        <span class="field-label" style="margin:0">Product</span>
        <select id="mapProduct" class="input"><option value="">— select —</option></select>
      </div>
      <div id="mapBox"><p class="muted">Select a product to manage its marketplace SKUs.</p></div>
    </div>`;

  el.querySelector("#create").onclick = async () => {
    const msg = el.querySelector("#msg");
    try {
      await api.post("/products", {
        internal_sku: el.querySelector("#internal_sku").value.trim(),
        name: el.querySelector("#name").value.trim(),
        platform: el.querySelector("#platform").value.trim() || null,
        region: el.querySelector("#region").value.trim() || null,
      });
      msg.innerHTML = `<span style="color:var(--green)">✓ Product created.</span>`;
      ["internal_sku", "name", "platform", "region"].forEach((id) => (el.querySelector(`#${id}`).value = ""));
      load();
    } catch (e) {
      msg.innerHTML = `<span style="color:var(--rose)">Error: ${e.message}</span>`;
    }
  };

  el.querySelector("#mapProduct").onchange = (e) => loadMappings(e.target.value);
  await load();
}
