import React from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchSummary, fetchAlerts, fetchDevices, generateMock } from "../lib/api";
import { StatusDot } from "../components/StatusDot";
import { Activity, Cpu, AlertOctagon, Gauge, Server, RefreshCw, Database } from "lucide-react";
import { toast } from "sonner";

const KpiTile = ({ label, value, suffix, icon: Icon, accent = "#16c79a", testId, sub }) => (
  <div className="nv-panel p-4" data-testid={testId}>
    <div className="flex items-center justify-between mb-3">
      <span className="nv-label">{label}</span>
      <Icon size={16} strokeWidth={1.6} style={{ color: accent }} />
    </div>
    <div className="flex items-baseline gap-2">
      <span className="nv-kpi-num" style={{ color: accent }}>{value}</span>
      {suffix && <span className="text-[12px] text-nv-muted font-mono">{suffix}</span>}
    </div>
    {sub && <div className="mt-2 text-[11px] text-nv-muted font-mono">{sub}</div>}
  </div>
);

const SeverityText = ({ s }) => (
  <span className={`nv-sev nv-sev-${s}`}>{s}</span>
);

export default function Dashboard() {
  const summary = useQuery({ queryKey: ["summary"], queryFn: fetchSummary });
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: fetchAlerts });
  const devices = useQuery({ queryKey: ["devices"], queryFn: fetchDevices });

  const handleGenerate = async () => {
    try {
      const r = await generateMock();
      toast.success(`Seeded ${r.devices_created} devices`);
      summary.refetch(); alerts.refetch(); devices.refetch();
    } catch (e) {
      toast.error("Failed to generate mock data");
    }
  };

  const s = summary.data || { total: 0, online: 0, critical: 0, open_alerts: 0, health_score: 0, avg_latency_ms: 0, avg_packet_loss: 0, warning: 0 };
  const recentAlerts = (alerts.data || []).slice(0, 8);
  const recentDevices = (devices.data || []).slice(0, 6);

  return (
    <div className="p-6" data-testid="dashboard-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <div className="text-[11px] tracking-[0.2em] text-nv-muted uppercase font-mono">Control Room</div>
          <h1 className="text-[22px] font-semibold tracking-tight">Operations Overview</h1>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-nv-muted font-mono tracking-wider">LIVE</span>
          <span className="nv-led nv-led-online animate-led-pulse" />
          <button className="nv-btn" onClick={handleGenerate} data-testid="dashboard-generate-mock-btn">
            <Database size={14} /> Seed Mock 20
          </button>
        </div>
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <KpiTile label="Total Devices" value={s.total} icon={Server} testId="kpi-total-devices" sub={`${s.online} online · ${s.warning} warn`} />
        <KpiTile label="Online" value={s.online} suffix={`/ ${s.total}`} icon={Activity} testId="kpi-online" accent="#16c79a" sub={s.total ? `${Math.round((s.online / s.total) * 100)}% reachable` : "—"} />
        <KpiTile label="Critical Alerts" value={s.critical_alerts ?? 0} icon={AlertOctagon} accent="#e74c3c" testId="kpi-critical-alerts" sub={`${s.open_alerts ?? 0} open total`} />
        <KpiTile label="Health Score" value={s.health_score} suffix="/ 100" icon={Gauge} accent="#16c79a" testId="kpi-health-score" sub={`avg latency ${s.avg_latency_ms}ms`} />
      </div>

      {/* Health bar */}
      <div className="nv-panel p-4 mb-4" data-testid="network-health-panel">
        <div className="flex items-center justify-between mb-2">
          <span className="nv-label">Network Health</span>
          <span className="font-mono text-[12px] text-nv-text">{s.health_score}/100</span>
        </div>
        <div className="nv-health-track">
          <div
            className="nv-health-fill"
            style={{
              width: `${s.health_score}%`,
              background:
                s.health_score >= 80 ? "#16c79a" : s.health_score >= 50 ? "#f4d03f" : "#e74c3c",
            }}
          />
        </div>
        <div className="grid grid-cols-3 gap-4 mt-3 text-[11px] font-mono">
          <div><span className="text-nv-muted uppercase">Latency:</span> <span className="text-nv-text">{s.avg_latency_ms}ms</span></div>
          <div><span className="text-nv-muted uppercase">Packet Loss:</span> <span className="text-nv-text">{s.avg_packet_loss}%</span></div>
          <div><span className="text-nv-muted uppercase">Open Alerts:</span> <span className="text-[#e74c3c]">{s.open_alerts}</span></div>
        </div>
      </div>

      {/* Alerts + Devices */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="nv-panel lg:col-span-2" data-testid="alert-feed-panel">
          <div className="flex items-center justify-between px-4 py-3 border-b border-nv-border">
            <span className="nv-section-title">Live Alert Feed</span>
            <RefreshCw size={12} className="text-nv-muted" />
          </div>
          <div className="divide-y divide-[#1f2a44]">
            {recentAlerts.length === 0 ? (
              <div className="px-4 py-10 text-center text-[12px] text-nv-muted font-mono">NO ACTIVE ALERTS</div>
            ) : (
              recentAlerts.map((a) => (
                <div key={a.id} className="px-4 py-2 flex items-center gap-3" data-testid={`alert-feed-item-${a.id}`}>
                  <SeverityText s={a.severity} />
                  <span className="font-mono text-[12px] text-nv-text min-w-[80px]">{a.device_name}</span>
                  <span className="text-[12px] text-nv-muted flex-1 truncate">{a.message}</span>
                  <span className="font-mono text-[10px] text-nv-muted">
                    {new Date(a.timestamp).toLocaleTimeString()}
                  </span>
                  {a.acknowledged && <span className="font-mono text-[10px] text-[#16c79a]">ACK</span>}
                </div>
              ))
            )}
          </div>
        </div>

        <div className="nv-panel" data-testid="recent-devices-panel">
          <div className="px-4 py-3 border-b border-nv-border">
            <span className="nv-section-title">Device Pulse</span>
          </div>
          <div>
            {recentDevices.map((d) => (
              <div key={d.id} className="px-4 py-2 flex items-center gap-3 border-b border-[#1f2a44] last:border-0">
                <StatusDot status={d.status} pulse={d.status !== "online"} />
                <span className="font-mono text-[12px] text-nv-text flex-1">{d.name}</span>
                <span className="font-mono text-[11px] text-nv-muted">{d.latency_ms}ms</span>
                <Cpu size={12} className="text-nv-muted" />
                <span className="font-mono text-[11px] text-nv-text">{d.cpu_pct}%</span>
              </div>
            ))}
            {recentDevices.length === 0 && (
              <div className="px-4 py-10 text-center text-[12px] text-nv-muted font-mono">NO DEVICES</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
