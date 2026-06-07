import React, { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchAlerts, acknowledgeAlert, deleteAlert, bulkAcknowledgeAlerts, fetchDevices,
} from "../lib/api";
import { exportCsv } from "../lib/csv";
import { useI18n } from "../lib/i18n";
import { Check, Trash2, Download, CheckCheck, Search, Link2 } from "lucide-react";
import { toast } from "sonner";

const SEV_ORDER = { critical: 0, warning: 1, info: 2 };

export default function Alerts() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const { data: alerts = [] } = useQuery({
    queryKey: ["alerts"],
    queryFn: fetchAlerts,
  });
  const { data: devices = [] } = useQuery({
    queryKey: ["devices"],
    queryFn: fetchDevices,
  });
  const deviceName = useMemo(() => {
    const m = {};
    devices.forEach((d) => { m[d.id] = d.name; });
    return m;
  }, [devices]);
  const [filter, setFilter] = useState("all"); // all | open | acknowledged
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(new Set());

  const mAck = useMutation({
    mutationFn: acknowledgeAlert,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["alerts"] }); toast.success(t("al.acked")); },
  });
  const mDel = useMutation({
    mutationFn: deleteAlert,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["alerts"] }); toast.success(t("al.removed")); },
  });
  const mBulkAck = useMutation({
    mutationFn: bulkAcknowledgeAlerts,
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["alerts"] }); toast.success(`${t("al.bulkAcked")} ${r.acknowledged}`); setSelected(new Set()); },
  });

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return alerts
      .filter((a) =>
        filter === "all" ? true : filter === "open" ? !a.acknowledged : a.acknowledged
      )
      .filter((a) =>
        !q ||
        a.device_name.toLowerCase().includes(q) ||
        a.message.toLowerCase().includes(q) ||
        a.severity.toLowerCase().includes(q)
      )
      .sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity]);
  }, [alerts, filter, search]);

  const counts = {
    all: alerts.length,
    open: alerts.filter((a) => !a.acknowledged).length,
    acknowledged: alerts.filter((a) => a.acknowledged).length,
  };
  const FILTER_LABEL = { all: t("al.filterAll"), open: t("al.filterOpen"), acknowledged: t("al.filterAck") };

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const visibleOpen = filtered.filter((a) => !a.acknowledged);
  const allOpenSelected = visibleOpen.length > 0 && visibleOpen.every((a) => selected.has(a.id));
  const toggleAllVisible = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allOpenSelected) {
        visibleOpen.forEach((a) => next.delete(a.id));
      } else {
        visibleOpen.forEach((a) => next.add(a.id));
      }
      return next;
    });
  };

  const handleBulkAck = () => {
    if (selected.size === 0) {
      if (!window.confirm(t("al.confirmAckAll"))) return;
      mBulkAck.mutate(null);
    } else {
      mBulkAck.mutate([...selected]);
    }
  };

  const handleExport = () => {
    const rows = filtered.map((a) => ({
      timestamp: a.timestamp,
      severity: a.severity,
      device: a.device_name,
      device_id: a.device_id,
      message: a.message,
      acknowledged: a.acknowledged,
    }));
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    exportCsv(`netvision-alerts-${ts}.csv`, rows);
    toast.success(`${rows.length} ${t("al.exportedSuffix")}`);
  };

  return (
    <div className="p-6" data-testid="alerts-page">
      <div className="flex items-center justify-between mb-5">
        <div>
          <div className="text-[11px] tracking-[0.2em] text-nv-muted uppercase font-mono">{t("al.eventLog")}</div>
          <h1 className="text-[22px] font-semibold tracking-tight">{t("nav.alerts")}</h1>
        </div>
        <div className="flex gap-2">
          <button
            className="nv-btn"
            onClick={handleExport}
            disabled={filtered.length === 0}
            data-testid="alerts-export-csv-btn"
          >
            <Download size={14} /> {t("common.exportCsv")}
          </button>
          <button
            className="nv-btn nv-btn-primary"
            onClick={handleBulkAck}
            disabled={counts.open === 0}
            data-testid="alerts-bulk-ack-btn"
            title={selected.size > 0 ? `${t("al.ackSelected")} (${selected.size})` : t("al.ackAllOpen")}
          >
            <CheckCheck size={14} />
            {selected.size > 0 ? `${t("al.ackSelected")} (${selected.size})` : `${t("al.ackAllOpen")} (${counts.open})`}
          </button>
        </div>
      </div>

      <div className="flex gap-2 mb-3 items-center flex-wrap">
        {["all", "open", "acknowledged"].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`nv-btn ${filter === f ? "nv-btn-primary" : ""}`}
            data-testid={`alerts-filter-${f}`}
          >
            {FILTER_LABEL[f]} <span className="font-mono opacity-70">{counts[f]}</span>
          </button>
        ))}
        <div className="ml-2 flex items-center gap-2 flex-1 min-w-[200px]">
          <Search size={14} className="text-nv-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("al.searchPlaceholder")}
            className="nv-input flex-1 px-3 py-1.5 text-[12px] rounded-sm max-w-[420px]"
            data-testid="alerts-search-input"
          />
        </div>
      </div>

      <div className="nv-panel overflow-hidden">
        <table className="nv-table" data-testid="alerts-table">
          <thead>
            <tr>
              <th style={{ width: 32 }}>
                <input
                  type="checkbox"
                  checked={allOpenSelected}
                  onChange={toggleAllVisible}
                  disabled={visibleOpen.length === 0}
                  className="accent-[#16c79a]"
                  data-testid="alerts-select-all"
                />
              </th>
              <th style={{ width: 110 }}>{t("al.colSeverity")}</th>
              <th style={{ width: 140 }}>{t("al.colDevice")}</th>
              <th>{t("al.colMessage")}</th>
              <th style={{ width: 160 }}>{t("al.colTimestamp")}</th>
              <th style={{ width: 100 }}>{t("al.colState")}</th>
              <th style={{ width: 110 }}>{t("al.colActions")}</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((a) => (
              <tr key={a.id} data-testid={`alert-row-${a.id}`}>
                <td>
                  <input
                    type="checkbox"
                    checked={selected.has(a.id)}
                    onChange={() => toggle(a.id)}
                    disabled={a.acknowledged}
                    className="accent-[#16c79a]"
                    data-testid={`alert-checkbox-${a.id}`}
                  />
                </td>
                <td>
                  <div className="flex items-center gap-2">
                    <span
                      className="inline-block w-1 h-4"
                      style={{
                        background:
                          a.severity === "critical" ? "#e74c3c" :
                          a.severity === "warning" ? "#f4d03f" : "#16c79a",
                      }}
                    />
                    <span className={`nv-sev nv-sev-${a.severity}`}>{a.severity}</span>
                  </div>
                </td>
                <td className="font-mono text-nv-text">{a.device_name}</td>
                <td className="text-[12px] text-nv-text">
                  {a.message}
                  {a.correlated_to && (
                    <span
                      className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-[10px] font-mono text-[#94a3b8] border border-[#3a4a63] align-middle"
                      title={`${t("al.correlatedTo")}: ${deviceName[a.correlated_to] || a.correlated_to}`}
                    >
                      <Link2 size={10} /> {deviceName[a.correlated_to] || "upstream"}
                    </span>
                  )}
                </td>
                <td className="font-mono text-[11px] text-nv-muted">
                  {new Date(a.timestamp).toLocaleString()}
                </td>
                <td>
                  <span className={`font-mono text-[11px] uppercase ${a.acknowledged ? "text-[#16c79a]" : "text-[#f4d03f]"}`}>
                    {a.acknowledged ? t("al.stateAck") : t("al.stateOpen")}
                  </span>
                </td>
                <td>
                  <div className="flex gap-2">
                    <button
                      className="nv-btn"
                      onClick={() => mAck.mutate(a.id)}
                      disabled={a.acknowledged}
                      data-testid={`alert-ack-${a.id}`}
                      title={t("al.ackTip")}
                    >
                      <Check size={12} /> ACK
                    </button>
                    <button
                      className="text-nv-muted hover:text-[#e74c3c] px-1"
                      onClick={() => mDel.mutate(a.id)}
                      data-testid={`alert-delete-${a.id}`}
                      title={t("common.delete")}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="text-center py-10 text-nv-muted font-mono text-[12px]">{t("al.noAlerts")}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
