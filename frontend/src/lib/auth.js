import { api } from "./api";

// LocalStorage keys (also referenced by the axios interceptor in api.js).
const TOKEN_KEY = "nv_token";
const USER_KEY = "nv_user";

export const getToken = () => localStorage.getItem(TOKEN_KEY);

export const getUser = () => {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || "null");
  } catch {
    return null;
  }
};

export const setSession = (token, user) => {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
};

export const clearSession = () => {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
};

// Public endpoint — tells the UI whether a login screen is needed.
// Uses a short timeout so an unreachable/older backend never hangs the app.
export const fetchAuthConfig = () =>
  api.get("/auth/config", { timeout: 3000 }).then((r) => r.data);

export const login = (username, password) =>
  api.post("/auth/login", { username, password }).then((r) => r.data);
