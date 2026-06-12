import { api } from "../api.js";
import { sk, pageHero, ICONS } from "../ui.js";

const amtColor = (a) => (parseFloat(a) < 0 ? "color:var(--rose)" : "color:var(--green)");

export async function renderWallets(el) {
  async function load() {
    el.querySelector("#wallets").innerHTML = sk.rows(3);
    el.querySelector("#tx").innerHTML = sk.rows(6);
    const [wallets, tx] = await Promise.all([
      api.get("/wallet"),
      api.get("/transactions?limit=30"),
    ]);
    el.querySelector("#wallets").innerHTML = wallets.length
      ? wallets
          .map(
            (w) => `<tr><td><span class="badge">${w.provider}</span></td><td>${w.currency}</td><td class="mono">${w.balance}</td></tr>`,
          )
          .join("")
      : `<tr><td colspan="3" class="muted" style="text-align:center;padding:1.2rem">No wallets yet.</td></tr>`;
    el.querySelector("#tx").innerHTML = tx.length
      ? tx
          .map(
            (t) => `<tr><td>${t.id}</td><td><span class="badge">${t.type}</span></td><td>${t.provider ?? "—"}</td>
        <td class="mono" style="${amtColor(t.amount)}">${t.amount}</td><td>${t.currency}</td><td class="mono">${t.balance_after ?? "—"}</td></tr>`,
          )
          .join("")
      : `<tr><td colspan="6" class="muted" style="text-align:center;padding:1.2rem">No transactions yet.</td></tr>`;
  }
  el.innerHTML = `
    ${pageHero({ icon: ICONS.wallets, title: "Wallets", subtitle: "Marketplace wallets fund just-in-time purchasing — top up and audit the ledger.", grad: "grad-amber" })}
    <div class="card" style="margin-bottom:1rem">
      <div class="card-head">Top up a wallet</div>
      <div class="field-row">
        <input id="prov" class="input" placeholder="provider (e.g. g2g)" />
        <input id="ccy" class="input" placeholder="currency" value="EUR" style="max-width:120px" />
        <input id="amt" class="input" placeholder="amount" style="max-width:140px" />
        <button class="btn" id="topup">Add funds</button>
        <span id="msg" style="font-size:.85rem"></span>
      </div>
    </div>
    <div class="grid-2">
      <div class="card"><div class="card-head">Balances</div>
        <table><thead><tr><th>Provider</th><th>Currency</th><th>Balance</th></tr></thead><tbody id="wallets"></tbody></table></div>
      <div class="card"><div class="card-head">Ledger</div>
        <table><thead><tr><th>ID</th><th>Type</th><th>Provider</th><th>Amount</th><th>Ccy</th><th>After</th></tr></thead><tbody id="tx"></tbody></table></div>
    </div>`;
  el.querySelector("#topup").onclick = async () => {
    const msg = el.querySelector("#msg");
    try {
      await api.post("/wallet/top-up", {
        provider: el.querySelector("#prov").value.trim(),
        currency: el.querySelector("#ccy").value.trim(),
        amount: el.querySelector("#amt").value,
      });
      msg.innerHTML = `<span style="color:var(--green)">✓ Funds added.</span>`;
      load();
    } catch (e) {
      msg.innerHTML = `<span style="color:var(--rose)">Error: ${e.message}</span>`;
    }
  };
  await load();
}
