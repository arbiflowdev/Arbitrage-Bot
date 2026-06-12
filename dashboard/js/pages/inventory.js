import { api } from "../api.js";
import { sk, pageHero, ICONS } from "../ui.js";

const INV_PILL = {
  available: "pill-delivered",
  reserved: "pill-awaiting_stock",
  sold: "pill-processing",
  invalid: "pill-failed",
};
const pill = (s) => `<span class="pill ${INV_PILL[s] || ""}">${s}</span>`;

export async function renderInventory(el) {
  const products = await api.get("/products");
  let fileContent = null;

  if (!products.length) {
    el.innerHTML = `<div class="card">No products in the catalogue yet — add a product before stocking inventory.</div>`;
    return;
  }

  async function load(pid) {
    if (!pid) return;
    el.querySelector("#rows").innerHTML = sk.rows(6);
    const [summary, items] = await Promise.all([
      api.get(`/inventory/summary?product_id=${pid}`),
      api.get(`/inventory?product_id=${pid}`),
    ]);
    el.querySelector("#summary").innerHTML = `
      <span class="pill pill-delivered">${summary.available} available</span>
      <span class="pill pill-awaiting_stock">${summary.reserved} reserved</span>
      <span class="pill pill-processing">${summary.sold} sold</span>
      <span class="pill pill-failed">${summary.invalid} invalid</span>`;
    const body = el.querySelector("#rows");
    body.innerHTML = items.length
      ? items
          .map(
            (i) => `
        <tr><td>${i.id}</td><td class="mono">${i.code_masked}</td><td>${pill(i.status)}</td>
        <td>${i.region ?? "—"}</td><td class="mono">${i.source_cost ?? "—"}</td>
        <td><button class="btn btn-sm btn-danger" data-inv="${i.id}">Invalidate</button></td></tr>`,
          )
          .join("")
      : `<tr><td colspan="6" class="muted" style="text-align:center;padding:1.5rem">No inventory for this product yet.</td></tr>`;
    el.querySelectorAll("[data-inv]").forEach((b) => {
      b.onclick = async () => {
        await api.post(`/inventory/${b.dataset.inv}/invalidate`);
        load(pid);
      };
    });
  }

  el.innerHTML = `
    ${pageHero({ icon: ICONS.inventory, title: "Inventory", subtitle: "Stock deliverable codes per product — upload a TXT/CSV file or paste them.", grad: "grad-violet" })}
    <div class="card" style="margin-bottom:1rem">
      <div class="field-row" style="justify-content:space-between">
        <div class="field-row">
          <span class="field-label" style="margin:0">Product</span>
          <select id="product" class="input">
            ${products.map((p) => `<option value="${p.id}">${p.name} (${p.internal_sku})</option>`).join("")}
          </select>
        </div>
        <div id="summary" class="field-row"></div>
      </div>
    </div>

    <div class="card" style="margin-bottom:1rem">
      <div class="card-head">Upload codes</div>
      <div class="grid-2">
        <div>
          <input type="file" id="file" accept=".txt,.csv" hidden />
          <div class="dropzone" id="drop">
            <div style="font-size:1.5rem;margin-bottom:.3rem">⬆</div>
            <div><strong>Choose a file</strong> or drag &amp; drop</div>
            <div class="muted" style="font-size:.78rem;margin-top:.25rem">.txt (one code per line) or .csv (with a <code>code</code> column)</div>
            <div id="fileInfo" style="font-size:.8rem;margin-top:.55rem;color:var(--green)"></div>
          </div>
        </div>
        <div>
          <span class="field-label">Or paste codes</span>
          <textarea id="content" class="input" rows="5" style="width:100%"
            placeholder="CODE-1&#10;CODE-2&#10;CODE-3"></textarea>
        </div>
      </div>
      <div class="field-row" style="margin-top:.9rem">
        <span class="field-label" style="margin:0">Format</span>
        <select id="fmt" class="input"><option value="txt">TXT</option><option value="csv">CSV</option></select>
        <button class="btn" id="uploadBtn">Upload</button>
        <span id="uploadMsg" style="font-size:.85rem"></span>
      </div>
    </div>

    <div class="card">
      <table>
        <thead><tr><th>ID</th><th>Code</th><th>Status</th><th>Region</th><th>Cost</th><th></th></tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>`;

  const sel = el.querySelector("#product");
  const fileInput = el.querySelector("#file");
  const drop = el.querySelector("#drop");
  const fmt = el.querySelector("#fmt");
  const fileInfo = el.querySelector("#fileInfo");
  const msg = el.querySelector("#uploadMsg");

  sel.onchange = () => load(sel.value);
  drop.onclick = () => fileInput.click();

  function handleFile(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      fileContent = String(reader.result);
      fmt.value = /\.csv$/i.test(file.name) ? "csv" : "txt";
      const lines = fileContent.split(/\r?\n/).filter((l) => l.trim()).length;
      fileInfo.innerHTML = `📄 <strong>${file.name}</strong> · ${lines} line(s) loaded`;
    };
    reader.readAsText(file);
  }
  fileInput.onchange = () => handleFile(fileInput.files[0]);
  ["dragover", "dragenter"].forEach((ev) =>
    drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.add("drag");
    }),
  );
  ["dragleave", "drop"].forEach((ev) =>
    drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.remove("drag");
    }),
  );
  drop.addEventListener("drop", (e) => handleFile(e.dataTransfer.files[0]));

  el.querySelector("#uploadBtn").onclick = async () => {
    const pasted = el.querySelector("#content").value.trim();
    const content = fileContent && fileContent.trim() ? fileContent : pasted;
    if (!content) {
      msg.innerHTML = `<span style="color:var(--amber)">Choose a file or paste some codes first.</span>`;
      return;
    }
    try {
      const r = await api.post("/inventory/upload", {
        product_id: Number(sel.value),
        format: fmt.value,
        content,
      });
      msg.innerHTML = `<span style="color:var(--green)">✓ Added ${r.added}, duplicates ${r.duplicates}, skipped ${r.skipped}.</span>`;
      fileContent = null;
      fileInfo.textContent = "";
      el.querySelector("#content").value = "";
      fileInput.value = "";
      load(sel.value);
    } catch (e) {
      msg.innerHTML = `<span style="color:var(--rose)">Error: ${e.message}</span>`;
    }
  };

  await load(sel.value);
}
