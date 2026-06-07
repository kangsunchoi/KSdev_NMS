import React, { useState, useMemo, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Brush, Legend,
} from "recharts";
import { fetchDeviceMetrics, fetchDeviceKv, fetchDeviceSeries } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { X } from "lucide-react";

const HOURS = [1, 6, 12, 24];

// Fixed network metrics (served by /devices/{id}/metrics).
const NETWORK_KEYS = ["latency_ms", "packet_loss", "cpu_pct"];
const NETWORK_META = {
  latency_ms: { color: "#16c79a", label: "Latency (ms)", suffix: "ms", short: "Latency" },
  packet_loss: { color: "#f4d03f", label: "Packet Loss (%)", suffix: "%", short: "Pkt Loss" },
  cpu_pct: { color: "#a78bfa", label: "CPU (%)", suffix: "%", short: "CPU" },
};
// Palette reused for arbitrary named (generic/PLC) metrics.
const GENERIC_COLORS = ["#16c79a", "#60a5fa", "#f472b6", "#fbbf24", "#34d399", "#c084fc", "#fb923c"];

const fmtTime = (ts) =>
  new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export const MetricChartModal = ({ device, onClose }) => {
  const { t } = useI18n();
  const [hours, setHours] = useState(24);
  const [metric, setMetric] = useState("latency_ms");

  // Latest generic-metric values (PLC registers, OPC UA nodes, etc.).
  const { data: kvRows = [] } = useQuery({
    queryKey: ["devkv", device?.id],
    queryFn: () => fetchDeviceKv(device.id),
    enabled: !!device,
    refetchInterval: 30000,
  });

  const genericKeys = useMemo(
    () => kvRows.map((r) => r.metric_name).sort(),
    [kvRows]
  );
  const isNetwork = NETWORK_KEYS.includes(metric);

  // If the selected metric disappears (e.g. device change), fall back safely.
  useEffect(() => {
    if (!isNetwork && !genericKeys.includes(metric)) {
      setMetric("latency_ms");
    }
  }, [genericKeys, metric, isNetwork]);

  // Chart series: network metrics from /metrics, generic from /series.
  const { data: chartData, isLoading } = useQuery({
    queryKey: ["devhist", device?.id, metric, hours, isNetwork],
    queryFn: () =>
      isNetwork
        ? fetchDeviceMetrics(device.id, hours)
        : fetchDeviceSeries(device.id, metric, hours),
    enabled: !!device && !!metric,
    refetchInterval: 30000,
  });

  if (!device) return null;

  // Normalize both shapes to { label, <valueKey> }.
  const valueKey = isNetwork ? metric : "value";
  const points = (chartData?.points || []).map((p) => ({
    label: fmtTime(p.ts),
    [valueKey]: isNetwork ? p[metric] : p.value,
  }));

  // Display metadata for the active metric.
  let meta;
  if (isNetwork) {
    meta = NETWORK_META[metric];
  } else {
    const idx = genericKeys.indexOf(metric);
    const unit = (kvRows.find((r) => r.metric_name === metric) || {}).unit || "";
    meta = {
      color: GENERIC_COLORS[(idx < 0 ? 0 : idx) % GENERIC_COLORS.length],
      label: unit ? `${metric} (${unit})` : metric,
      suffix: unit ? ` ${unit}` : "",
      short: metric,
    };
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
      data-testid="metric-chart-modal"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="nv-panel w-[920px] max-w-full">
        <div className="px-4 py-3 border-b border-nv-border flex items-center justify-between">
          <div>
            <div className="nv-section-title">{t("modal.deviceHistory")}</div>
            <div className="font-mono text-[14px] text-nv-text mt-0.5">
              {device.name} <span className="text-nv-muted">/ {device.ip}</span>
            </div>
          </div>
          <button onClick={onClose} className="text-nv-muted hover:text-white" data-testid="metric-chart-close">
            <X size={16} />
          </button>
        </div>

        {/* Latest generic (PLC) values */}
        {kvRows.length > 0 && (
          <div className="px-4 py-3 border-b border-nv-border" data-testid="metric-kv-panel">
            <div className="nv-label mb-2">{t("modal.plcLatest")}</div>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
              {kvRows.map((r) => {
                const active = metric === r.metric_name;
                return (
                  <button
                    key={r.metric_name}
                    onClick={() => setMetric(r.metric_name)}
                    title={`${r.metric_name} — updated ${fmtTime(r.ts)}`}
                    data-testid={`metric-kv-${r.metric_name}`}
                    className={`text-left rounded border px-2.5 py-2 transition-colors ${
                      active
                        ? "border-nv-accent bg-nv-accent/10"
                        : "border-nv-border hover:border-nv-accent/60"
                    }`}
                  >
                    <div className="nv-label truncate">{r.metric_name}</div>
                    <div className="font-mono text-[15px] text-nv-text mt-0.5">
                      {r.value}
                      {r.unit ? <span className="text-nv-muted text-[11px] ml-1">{r.unit}</span> : null}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Controls: time range + metric selector (network + generic) */}
        <div className="px-4 py-2 border-b border-nv-border flex items-center gap-2 flex-wrap">
          <span className="nv-label mr-1">{t("modal.range")}:</span>
          {HOURS.map((h) => (
            <button
              key={h}
              onClick={() => setHours(h)}
              className={`nv-btn ${hours === h ? "nv-btn-primary" : ""}`}
              data-testid={`metric-range-${h}h`}
            >
              {h}H
            </button>
          ))}
          <span className="nv-label ml-4 mr-1">{t("modal.metric")}:</span>
          {NETWORK_KEYS.map((k) => (
            <button
              key={k}
              onClick={() => setMetric(k)}
              className={`nv-btn ${metric === k ? "nv-btn-primary" : ""}`}
              data-testid={`metric-key-${k}`}
            >
              {NETWORK_META[k].short}
            </button>
          ))}
          {genericKeys.map((k) => (
            <button
              key={k}
              onClick={() => setMetric(k)}
              className={`nv-btn ${metric === k ? "nv-btn-primary" : ""}`}
              data-testid={`metric-key-${k}`}
            >
              {k}
            </button>
          ))}
          <span className="ml-auto font-mono text-[11px] text-nv-muted">
            {points.length} pts {isLoading ? `· ${t("modal.loading")}` : ""}
          </span>
        </div>

        {/* Chart */}
        <div className="p-4 h-[380px]" data-testid="metric-chart-container">
          {points.length === 0 ? (
            <div className="h-full flex items-center justify-center text-nv-muted font-mono text-[12px]">
              {isNetwork
                ? t("modal.noDataNet")
                : t("modal.noDataGeneric")}
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points} margin={{ top: 8, right: 20, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="#2a3b55" strokeDasharray="2 4" />
                <XAxis
                  dataKey="label"
                  tick={{ fill: "#94a3b8", fontSize: 10, fontFamily: "JetBrains Mono" }}
                  axisLine={{ stroke: "#2a3b55" }}
                  tickLine={false}
                  minTickGap={32}
                />
                <YAxis
                  tick={{ fill: "#94a3b8", fontSize: 10, fontFamily: "JetBrains Mono" }}
                  axisLine={{ stroke: "#2a3b55" }}
                  tickLine={false}
                  width={40}
                />
                <Tooltip
                  contentStyle={{
                    background: "#16213e",
                    border: "1px solid #2a3b55",
                    borderRadius: 3,
                    fontFamily: "JetBrains Mono, monospace",
                    fontSize: 11,
                  }}
                  labelStyle={{ color: "#94a3b8" }}
                  formatter={(v) => [`${v}${meta.suffix}`, meta.label]}
                />
                <Legend wrapperStyle={{ fontSize: 11, fontFamily: "Inter", color: "#94a3b8" }} />
                <Line
                  type="monotone"
                  dataKey={valueKey}
                  stroke={meta.color}
                  strokeWidth={1.6}
                  dot={false}
                  isAnimationActive={false}
                  name={meta.label}
                />
                <Brush
                  dataKey="label"
                  height={22}
                  stroke="#2a3b55"
                  fill="#1a1a2e"
                  travellerWidth={8}
                  tickFormatter={() => ""}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  );
};

export default MetricChartModal;
