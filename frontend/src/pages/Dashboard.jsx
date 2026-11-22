import React from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchSummary, fetchAlerts, fetchDevices } from "../lib/api";
import { StatusDot } from "../components/StatusDot";
import { useI18n } from "../lib/i18n";
import { Activity, Cpu, AlertOctagon, Gauge, Server, RefreshCw } from "lucide-react";

const KpiTile = ({ label, value, suffix, icon: Icon, accent = "var(--nv-text)", testId, sub }) => (
  <div className="nv-panel nv-kpi-card p-4" data-testid={testId}>
    <div className="flex items-center justify-between mb-3">
      <span className="nv-label">{label}</span>
      <Icon size={16} strokeWidth={1.6} style={{ color: accent }} />
    </div>
    <div className="flex items-baseline gap-2">
      <span className="nv-kpi-num" >{value}</span>
      {suffix && <span className="text-[12px] text-nv-muted font-mono">{suffix}</span>}
    </div>
    {sub && <div className="mt-2 text-[11px] text-nv-muted font-mono">{sub}</div>}
  </div>
);

const SeverityText = ({ s }) => (
  <span className={`nv-sev nv-sev-${s}`}>{s}</span>
);

export default function Dashboard() {
  const { t } = useI18n();
  const summary = useQuery({ queryKey: ["summary"], queryFn: fetchSummary });
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: fetchAlerts });
  const devices = useQuery({ queryKey: ["devices"], queryFn: fetchDevices });

  const s = summary.data || { total: 0, online: 0, critical: 0, open_alerts: 0, health_score: 0, avg_packet_loss: 0, warning: 0 };
  const latency = s.avg_latency_ms == null ? t("dash.notMeasured") : `${s.avg_latency_ms} ms`;
  const recentAlerts = (alerts.data || []).slice(0, 8);
  const recentDevices = (devices.data || []).slice(0, 6);

  return (
    <div className="nv-page" data-testid="dashboard-page">
      {s.collector_stale && (
        <div
          className="mb-4 px-3 py-2 border border-[#ae2832] text-[#ae2832] bg-[#ae2832]/10 text-[12px] font-mono"
          role="alert"
          data-testid="dashboard-collector-stale"
        >
          {t("dash.collectorStale")}: {s.last_ingest_ts ? new Date(s.last_ingest_ts).toLocaleString() : t("dash.never")}
        </div>
      )}
      {/* Header */}
      <div className="nv-page-header">
        <div>
          <div className="text-[11px] tracking-[0.2em] text-nv-muted uppercase font-mono">{t("dash.controlRoom")}</div>
          <h1 className="nv-page-title">{t("dash.title")}</h1>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-nv-muted font-mono tracking-wider">{t("dash.live")}</span>
          <span className="nv-led nv-led-online animate-led-pulse" />
        </div>
      </div>

      {/* KPI grid */}
      <div className="nv-kpi-grid">
        <KpiTile label={t("dash.totalDevices")} value={s.total} icon={Server} testId="kpi-total-devices" sub={`${s.online} online · ${s.warning} warn`} />
        <KpiTile label={t("dash.online")} value={s.online} suffix={`/ ${s.total}`} icon={Activity} testId="kpi-online" accent="#09654b" sub={s.total ? `${Math.round((s.online / s.total) * 100)}% reachable` : "—"} />
        <KpiTile label={t("dash.criticalAlerts")} value={s.critical_alerts ?? 0} icon={AlertOctagon} accent="#ae2832" testId="kpi-critical-alerts" sub={`${t("dash.openAlerts")} ${s.open_alerts ?? 0}`} />
        <KpiTile label={t("dash.healthScore")} value={s.health_score} suffix="/ 100" icon={Gauge} accent="#09654b" testId="kpi-health-score" sub={`${t("dash.latency")} ${latency}`} />
      </div>

      {/* Health bar */}
      <div className="nv-panel p-4 mb-4" data-testid="network-health-panel">
        <div className="flex items-center justify-between mb-2">
          <span className="nv-label">{t("dash.networkHealth")}</span>
          <span className="font-mono text-[12px] text-nv-text">{s.health_score}/100</span>
        </div>
        <div className="nv-health-track">
          <div
            className="nv-health-fill"
            style={{
              width: `${s.health_score}%`,
              background:
                s.health_score >= 80 ? "#09654b" : s.health_score >= 50 ? "#875100" : "#ae2832",
            }}
          />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-3 text-[11px] font-mono">
          <div><span className="text-nv-muted uppercase">{t("dash.latency")}:</span> <span className="text-nv-text">{latency}</span>{s.latency_sample_count != null && ` (${t("dash.samples")} ${s.latency_sample_count})`}</div>
          <div><span className="text-nv-muted uppercase">{t("dash.packetLoss")}:</span> <span className="text-nv-text">{s.avg_packet_loss}%</span></div>
          <div><span className="text-nv-muted uppercase">{t("dash.openAlerts")}:</span> <span className="text-[#ae2832]">{s.open_alerts}</span></div>
        </div>
      </div>

      {/* Alerts + Devices */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="nv-panel lg:col-span-2" data-testid="alert-feed-panel">
          <div className="flex items-center justify-between px-4 py-3 border-b border-nv-border">
            <span className="nv-section-title">{t("dash.alertFeed")}</span>
            <RefreshCw size={12} className="text-nv-muted" />
          </div>
          <div className="divide-y divide-[#e0e4e7]">
            {recentAlerts.length === 0 ? (
              <div className="px-4 py-10 text-center text-[12px] text-nv-muted font-mono">{t("dash.noAlerts")}</div>
            ) : (
              recentAlerts.map((a) => (
                <div key={a.id} className="px-4 py-2 flex items-center gap-3" data-testid={`alert-feed-item-${a.id}`}>
                  <SeverityText s={a.severity} />
                  <span className="font-mono text-[12px] text-nv-text min-w-[80px]">{a.device_name}</span>
                  <span className="text-[12px] text-nv-muted flex-1 truncate">{a.message}</span>
                  <span className="font-mono text-[10px] text-nv-muted">
                    {new Date(a.timestamp).toLocaleTimeString()}
                  </span>
                  {a.acknowledged && <span className="font-mono text-[10px] text-[#09654b]">ACK</span>}
                </div>
              ))
            )}
          </div>
        </div>

        <div className="nv-panel" data-testid="recent-devices-panel">
          <div className="px-4 py-3 border-b border-nv-border">
            <span className="nv-section-title">{t("dash.devicePulse")}</span>
          </div>
          <div>
            {recentDevices.map((d) => (
              <div key={d.id} className="px-4 py-2 flex items-center gap-3 border-b border-[#e0e4e7] last:border-0">
                <StatusDot status={d.status} pulse={d.status !== "online"} />
                <span className="font-mono text-[12px] text-nv-text flex-1">{d.name}</span>
                <span className="font-mono text-[11px] text-nv-muted">{d.latency_ms == null ? t("dash.notMeasured") : `${d.latency_ms} ms`}</span>
                <Cpu size={12} className="text-nv-muted" />
                <span className="font-mono text-[11px] text-nv-text">{d.cpu_pct}%</span>
              </div>
            ))}
            {recentDevices.length === 0 && (
              <div className="px-4 py-10 text-center text-[12px] text-nv-muted font-mono">{t("dash.noDevices")}</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
