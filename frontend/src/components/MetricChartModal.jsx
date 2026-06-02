import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Brush, Legend,
} from "recharts";
import { fetchDeviceMetrics } from "../lib/api";
import { X } from "lucide-react";

const HOURS = [1, 6, 12, 24];

export const MetricChartModal = ({ device, onClose }) => {
  const [hours, setHours] = useState(24);
  const [metric, setMetric] = useState("latency_ms");
  const { data, isLoading } = useQuery({
    queryKey: ["metrics", device?.id, hours],
    queryFn: () => fetchDeviceMetrics(device.id, hours),
    enabled: !!device,
    refetchInterval: 30000,
  });

  if (!device) return null;
  const points = (data?.points || []).map((p) => ({
    t: new Date(p.ts).getTime(),
    label: new Date(p.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    latency_ms: p.latency_ms,
    packet_loss: p.packet_loss,
    cpu_pct: p.cpu_pct,
  }));

  const metricMeta = {
    latency_ms: { color: "#16c79a", label: "Latency (ms)", suffix: "ms" },
    packet_loss: { color: "#f4d03f", label: "Packet Loss (%)", suffix: "%" },
    cpu_pct: { color: "#a78bfa", label: "CPU (%)", suffix: "%" },
  }[metric];

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
      data-testid="metric-chart-modal"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="nv-panel w-[920px] max-w-full">
        <div className="px-4 py-3 border-b border-nv-border flex items-center justify-between">
          <div>
            <div className="nv-section-title">Device History</div>
            <div className="font-mono text-[14px] text-nv-text mt-0.5">
              {device.name} <span className="text-nv-muted">/ {device.ip}</span>
            </div>
          </div>
          <button onClick={onClose} className="text-nv-muted hover:text-white" data-testid="metric-chart-close">
            <X size={16} />
          </button>
        </div>

        <div className="px-4 py-2 border-b border-nv-border flex items-center gap-2 flex-wrap">
          <span className="nv-label mr-1">Range:</span>
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
          <span className="nv-label ml-4 mr-1">Metric:</span>
          {Object.entries({
            latency_ms: "Latency",
            packet_loss: "Pkt Loss",
            cpu_pct: "CPU",
          }).map(([k, l]) => (
            <button
              key={k}
              onClick={() => setMetric(k)}
              className={`nv-btn ${metric === k ? "nv-btn-primary" : ""}`}
              data-testid={`metric-key-${k}`}
            >
              {l}
            </button>
          ))}
          <span className="ml-auto font-mono text-[11px] text-nv-muted">
            {points.length} pts {isLoading ? "· loading" : ""}
          </span>
        </div>

        <div className="p-4 h-[380px]" data-testid="metric-chart-container">
          {points.length === 0 ? (
            <div className="h-full flex items-center justify-center text-nv-muted font-mono text-[12px]">
              NO DATA YET — metrics sample every 60 seconds
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
                  formatter={(v) => [`${v}${metricMeta.suffix}`, metricMeta.label]}
                />
                <Legend wrapperStyle={{ fontSize: 11, fontFamily: "Inter", color: "#94a3b8" }} />
                <Line
                  type="monotone"
                  dataKey={metric}
                  stroke={metricMeta.color}
                  strokeWidth={1.6}
                  dot={false}
                  isAnimationActive={false}
                  name={metricMeta.label}
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
