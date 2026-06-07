import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

// Attach the bearer token (if any) to every request. When auth is disabled
// there is no token, so requests go out exactly as before.
api.interceptors.request.use((config) => {
  const t = localStorage.getItem("nv_token");
  if (t) config.headers.Authorization = `Bearer ${t}`;
  return config;
});

// On 401 (expired/invalid token), drop the session and let App route to login.
// Guarded by window.__nvAuthEnabled so it stays inert when auth is off.
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401 && window.__nvAuthEnabled) {
      localStorage.removeItem("nv_token");
      localStorage.removeItem("nv_user");
      window.dispatchEvent(new Event("nv-unauthorized"));
    }
    return Promise.reject(err);
  }
);

export const fetchDevices = () => api.get("/devices").then((r) => r.data);
export const createDevice = (payload) => api.post("/devices", payload).then((r) => r.data);
export const updateDevice = (id, payload) => api.patch(`/devices/${id}`, payload).then((r) => r.data);
export const deleteDevice = (id) => api.delete(`/devices/${id}`).then((r) => r.data);

export const fetchAlerts = () => api.get("/alerts").then((r) => r.data);
export const acknowledgeAlert = (id) => api.post(`/alerts/${id}/acknowledge`).then((r) => r.data);
export const deleteAlert = (id) => api.delete(`/alerts/${id}`).then((r) => r.data);

export const fetchTopology = () => api.get("/topology").then((r) => r.data);

// Settings: user management (admin) + audit log
export const fetchUsers = () => api.get("/auth/users").then((r) => r.data);
export const createUser = (payload) => api.post("/auth/users", payload).then((r) => r.data);
export const updateUser = (username, payload) =>
  api.patch(`/auth/users/${username}`, payload).then((r) => r.data);
export const deleteUser = (username) =>
  api.delete(`/auth/users/${username}`).then((r) => r.data);
export const fetchAudit = (limit = 200) =>
  api.get(`/audit?limit=${limit}`).then((r) => r.data);
export const fetchSummary = () => api.get("/dashboard/summary").then((r) => r.data);

export const fetchDeviceMetrics = (id, hours = 24) =>
  api.get(`/devices/${id}/metrics`, { params: { hours } }).then((r) => r.data);
export const bulkAcknowledgeAlerts = (ids) =>
  api.post(`/alerts/bulk-acknowledge`, { ids }).then((r) => r.data);

// Generic / PLC metrics (UnifiedMetric): latest values + named-metric time-series.
export const fetchDeviceKv = (id) =>
  api.get(`/devices/${id}/kv`).then((r) => r.data);
export const fetchDeviceSeries = (id, metric, hours = 24) =>
  api.get(`/devices/${id}/series`, { params: { metric, hours } }).then((r) => r.data);

// Interfaces (IF-MIB snapshot with bps).
export const fetchDeviceInterfaces = (id) =>
  api.get(`/devices/${id}/interfaces`).then((r) => r.data);

export const generateMock = () => api.post("/mock/generate").then((r) => r.data);
export const resetAll = () => api.post("/mock/reset").then((r) => r.data);

// Discovery: subnet-sweep settings (collector reads these and registers found devices).
export const fetchDiscovery = () => api.get("/discovery").then((r) => r.data);
export const updateDiscovery = (patch) => api.put("/discovery", patch).then((r) => r.data);
