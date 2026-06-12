// Shared UI helpers — skeleton placeholders + gradient page headers.

const blk = (w, h, extra = "") =>
  `<div class="skeleton" style="width:${w};height:${h};${extra}"></div>`;

const I = (p) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;

export const ICONS = {
  orders: I(`<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1Z"/><path d="M8 7h8M8 11h8M8 15h5"/>`),
  inventory: I(`<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>`),
  pricing: I(`<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>`),
  wallets: I(`<path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/>`),
  logs: I(`<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3.5" y1="6" x2="3.51" y2="6"/><line x1="3.5" y1="12" x2="3.51" y2="12"/><line x1="3.5" y1="18" x2="3.51" y2="18"/>`),
  alerts: I(`<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>`),
  users: I(`<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>`),
  connections: I(`<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>`),
};

// Gradient page header banner (one per tab, à la the template's section heroes)
export function pageHero({ icon, title, subtitle, grad = "grad-indigo", action = "" }) {
  return `
    <div class="page-hero ${grad}">
      <div class="page-hero-icon">${icon}</div>
      <div class="page-hero-text"><h2>${title}</h2><p>${subtitle}</p></div>
      ${action ? `<div class="page-hero-action">${action}</div>` : ""}
    </div>`;
}

export const sk = {
  // table body rows (cols × n) — drop into a <tbody> before fetching
  rows(cols, n = 6) {
    return Array.from({ length: n })
      .map(() => `<tr>${Array.from({ length: cols }).map(() => `<td>${blk("80%", "12px")}</td>`).join("")}</tr>`)
      .join("");
  },
  stats(n = 4) {
    return `<div class="stat-grid">${Array.from({ length: n })
      .map(() =>
        `<div class="stat">${blk("50px", "50px", "border-radius:16px;flex:0 0 auto")}<div style="flex:1">${blk("55%", "10px", "margin-bottom:10px")}${blk("40%", "22px")}</div></div>`,
      )
      .join("")}</div>`;
  },
  card(lines = 4) {
    return `<div class="card">${blk("35%", "14px", "margin-bottom:16px")}${Array.from({ length: lines })
      .map((_, i) => blk(`${92 - i * 10}%`, "12px", "margin:10px 0"))
      .join("")}</div>`;
  },
  // generic full-page placeholder used on every navigation until content renders
  page() {
    return `<div class="skeleton" style="height:170px;border-radius:var(--radius);margin-bottom:1.4rem"></div>${this.stats()}<div class="grid-2">${this.card(5)}${this.card(5)}</div>`;
  },
};
