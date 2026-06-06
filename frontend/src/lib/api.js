import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

export const fetchDevices = () => api.get("/devices").then((r) => r.data);
export const createDevice = (payload) => api.post("/devices", payload).then((r) => r.data);
export const updateDevice = (id, payload) => api.patch(`/devices/${id}`, payload).then((r) => r.data);
export const deleteDevice = (id) => api.delete(`/devices/${id}`).then((r) => r.data);

export const fetchAlerts = () => api.get("/alerts").then((r) => r.data);
export const acknowledgeAlert = (id) => api.post(`/alerts/${id}/acknowledge`).then((r) => r.data);
export const deleteAlert = (id) => api.delete(`/alerts/${id}`).then((r) => r.data);

export const fetchTopology = () => api.get("/topology").then((r) => r.data);
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

export const generateMock = () => api.post("/mock/generate").then((r) => r.data);
export const resetAll = () => api.post("/mock/reset").then((r) => r.data);
