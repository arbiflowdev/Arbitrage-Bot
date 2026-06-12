import { api } from "./api.js";
import { isAuthed } from "./auth.js";
import { sk } from "./ui.js";
import { renderLogin } from "./pages/login.js";
import { renderOverview } from "./pages/overview.js";
import { renderOrders } from "./pages/orders.js";
import { renderInventory } from "./pages/inventory.js";
import { renderPricing } from "./pages/pricing.js";
import { renderWallets } from "./pages/wallets.js";
import { renderLogs } from "./pages/logs.js";
import { renderAlerts } from "./pages/alerts.js";
import { renderUsers } from "./pages/users.js";
import { renderConnections } from "./pages/connections.js";

const ROUTES = {
  "/login": renderLogin,
  "/": renderOverview,
  "/orders": renderOrders,
  "/inventory": renderInventory,
  "/pricing": renderPricing,
  "/wallets": renderWallets,
  "/logs": renderLogs,
  "/alerts": renderAlerts,
  "/users": renderUsers,
  "/connections": renderConnections,
};

const NAV = [
  ["/", "Overview"], ["/orders", "Orders"], ["/inventory", "Inventory"],
  ["/pricing", "Pricing"], ["/wallets", "Wallets"], ["/logs", "Logs"],
  ["/alerts", "Alerts"], ["/users", "Users"], ["/connections", "Connections"],
];

const S = (p) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const ICONS = {
  "/": S(`<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/>`),
  "/orders": S(`<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1Z"/><path d="M8 7h8M8 11h8M8 15h5"/>`),
  "/inventory": S(`<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>`),
  "/pricing": S(`<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>`),
  "/wallets": S(`<path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/>`),
  "/logs": S(`<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3.5" y1="6" x2="3.51" y2="6"/><line x1="3.5" y1="12" x2="3.51" y2="12"/><line x1="3.5" y1="18" x2="3.51" y2="18"/>`),
  "/alerts": S(`<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>`),
  "/users": S(`<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>`),
  "/connections": S(`<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>`),
};

function titleFor(path) {
  const item = NAV.find(([h]) => h === path);
  return item ? item[1] : "Overview";
}

function shell(path, contentEl) {
  const app = document.getElementById("app");
  app.innerHTML = `
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand">
          <span class="brand-glyph">◆</span>
          <div><div class="brand-name">Arbitrage</div><div class="brand-sub">CONTROL CENTER</div></div>
        </div>
        <nav>
          ${NAV.map(([h, label]) =>
            `<a class="nav-link ${path === h ? "active" : ""}" href="#${h}">${ICONS[h] || ""}<span>${label}</span></a>`,
          ).join("")}
        </nav>
        <div class="sidebar-foot">
          <div class="user-chip">
            <div class="avatar" id="avatar">A</div>
            <div><div class="u-name" id="uname">Admin</div><div class="u-role" id="urole">administrator</div></div>
          </div>
          <button class="logout" id="logout">Log out</button>
        </div>
      </aside>
      <div class="main">
        <header class="topbar">
          <div>
            <div class="crumb">Control center</div>
            <div class="page-title">${titleFor(path)}</div>
          </div>
        </header>
        <main class="content" id="content"></main>
      </div>
    </div>`;
  document.getElementById("content").appendChild(contentEl);
  document.getElementById("logout").onclick = () =>
    import("./auth.js").then((m) => m.logout());
  enhanceChrome();
}

let cachedMe = null; // /auth/me doesn't change between tabs — fetch once, reuse

function fillUserChip(me) {
  const uname = document.getElementById("uname");
  const urole = document.getElementById("urole");
  const avatar = document.getElementById("avatar");
  if (uname) uname.textContent = me.email;
  if (urole) urole.textContent = me.role;
  if (avatar) avatar.textContent = (me.email?.[0] || "A").toUpperCase();
}

function enhanceChrome() {
  // Best-effort: fill the sidebar user chip with the signed-in account.
  if (cachedMe) { fillUserChip(cachedMe); return; }
  api.get("/auth/me")
    .then((me) => { cachedMe = me; fillUserChip(me); })
    .catch(() => {});
}

async function route() {
  const path = (location.hash || "#/").slice(1);
  if (!isAuthed() && path !== "/login") {
    location.hash = "#/login";
    return;
  }
  const render = ROUTES[path] || renderOverview;
  const el = document.createElement("div");
  if (path === "/login") {
    document.getElementById("app").innerHTML = "";
    document.getElementById("app").appendChild(el);
  } else {
    shell(path, el);
    el.innerHTML = sk.page(); // instant placeholder until the page renders
  }
  try {
    await render(el);
  } catch (e) {
    el.innerHTML = `<div class="card" style="color:var(--rose)">${e.message}</div>`;
  }
}

window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", route);
