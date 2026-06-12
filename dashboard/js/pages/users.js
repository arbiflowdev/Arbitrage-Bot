import { api } from "../api.js";
import { sk, pageHero, ICONS } from "../ui.js";

export async function renderUsers(el) {
  async function load() {
    el.querySelector("#rows").innerHTML = sk.rows(7);
    const users = await api.get("/users");
    el.querySelector("#rows").innerHTML = users
      .map(
        (u) => `
      <tr>
        <td>${u.id}</td>
        <td>${u.email}</td>
        <td>${u.full_name ?? "-"}</td>
        <td><span class="badge ${u.role === "admin" ? "badge-admin" : ""}">${u.role}</span></td>
        <td>${u.is_active ? "✅ active" : "⛔ disabled"}</td>
        <td>${new Date(u.created_at).toLocaleDateString()}</td>
        <td class="whitespace-nowrap">
          <button class="btn" data-role="${u.id}" data-next="${u.role === "admin" ? "user" : "admin"}">
            ${u.role === "admin" ? "Make user" : "Make admin"}</button>
          <button class="btn ${u.is_active ? "btn-danger" : ""}" data-active="${u.id}" data-next="${u.is_active ? "false" : "true"}">
            ${u.is_active ? "Deactivate" : "Activate"}</button>
        </td>
      </tr>`,
      )
      .join("");
    el.querySelectorAll("[data-role]").forEach((b) => {
      b.onclick = async () => {
        try {
          await api.patch(`/users/${b.dataset.role}`, { role: b.dataset.next });
          load();
        } catch (e) {
          alert(e.message);
        }
      };
    });
    el.querySelectorAll("[data-active]").forEach((b) => {
      b.onclick = async () => {
        try {
          await api.patch(`/users/${b.dataset.active}`, {
            is_active: b.dataset.next === "true",
          });
          load();
        } catch (e) {
          alert(e.message);
        }
      };
    });
  }

  el.innerHTML = `
    ${pageHero({ icon: ICONS.users, title: "Users", subtitle: "Admins manage operator accounts here — there is no public sign-up.", grad: "grad-indigo" })}
    <div class="card mb-4">
      <h2 class="font-semibold mb-2">Add user</h2>
      <div class="grid md:grid-cols-5 gap-2">
        <input id="email" class="input" placeholder="email" />
        <input id="full_name" class="input" placeholder="full name (optional)" />
        <input id="password" class="input" type="password" placeholder="password (min 8)" />
        <select id="role" class="input">
          <option value="admin">admin</option>
          <option value="user">user</option>
        </select>
        <button class="btn" id="create">Create</button>
      </div>
      <p id="msg" class="text-sm mt-2"></p>
    </div>
    <div class="card"><table>
      <thead><tr><th>ID</th><th>Email</th><th>Name</th><th>Role</th>
        <th>Status</th><th>Created</th><th></th></tr></thead>
      <tbody id="rows"></tbody></table></div>`;

  el.querySelector("#create").onclick = async () => {
    const msg = el.querySelector("#msg");
    try {
      await api.post("/users", {
        email: el.querySelector("#email").value.trim(),
        full_name: el.querySelector("#full_name").value.trim() || null,
        password: el.querySelector("#password").value,
        role: el.querySelector("#role").value,
      });
      msg.textContent = "User created.";
      el.querySelector("#email").value = "";
      el.querySelector("#full_name").value = "";
      el.querySelector("#password").value = "";
      load();
    } catch (e) {
      msg.textContent = "Error: " + e.message;
    }
  };

  await load();
}
