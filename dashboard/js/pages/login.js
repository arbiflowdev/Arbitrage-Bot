import { login } from "../auth.js";

export async function renderLogin(el) {
  el.innerHTML = `
    <div class="login-bg">
      <div class="login-orbs"></div>
      <form id="loginForm" class="glass">
        <div class="text-center mb-7">
          <div class="brand-mark">◆</div>
          <h1 class="text-2xl font-bold tracking-tight mt-3">Arbitrage Platform</h1>
          <p class="text-sm text-slate-400 mt-1">Admin control panel</p>
        </div>

        <label class="field-label" for="email">Email</label>
        <input class="input glass-input mb-4" id="email" type="email"
               placeholder="you@company.com" autocomplete="username" required />

        <label class="field-label" for="password">Password</label>
        <input class="input glass-input mb-6" id="password" type="password"
               placeholder="••••••••" autocomplete="current-password" required />

        <button class="btn-grad" type="submit">Sign in</button>

        <p id="err" class="text-rose-400 text-sm mt-3 text-center min-h-[1.25rem]"></p>
        <p class="text-center text-xs text-slate-500 mt-4">🔒 Secure admin access · accounts are provisioned by an administrator</p>
      </form>
    </div>`;

  const form = el.querySelector("#loginForm");
  const err = el.querySelector("#err");
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button");
    err.textContent = "";
    btn.disabled = true;
    btn.textContent = "Signing in…";
    try {
      await login(
        el.querySelector("#email").value.trim(),
        el.querySelector("#password").value,
      );
      location.hash = "#/";
    } catch (ex) {
      err.textContent =
        ex.message === "unauthorized"
          ? "Invalid email or password."
          : "Login failed: " + ex.message;
      btn.disabled = false;
      btn.textContent = "Sign in";
    }
  };
}
