import { api, setToken, clearToken, getToken } from "./api.js";

export async function login(email, password) {
  const res = await api.post("/auth/login", { email, password });
  setToken(res.access_token);
  return res;
}
export function logout() {
  clearToken();
  location.hash = "#/login";
}
export const isAuthed = () => !!getToken();
