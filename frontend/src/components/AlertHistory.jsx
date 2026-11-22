import React, { useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { fetchAlertHistory } from "../lib/api";
import { useI18n } from "../lib/i18n";

import { DeviceIcon } from "./DeviceIcon";

const PERIODS = [24, 24 * 7, 24 * 30];

/** Paged alert history over the retention period (issue #24). */
export function AlertHistory({ devicesById }) {
  const { t } = useI18n();
  const [state, setState] = useState("");
  const [hours, setHours] = useState(24 * 7);
  const [page, setPage] = useState(1);
  const pageSize = 100;
  const { data, isFetching } = useQuery({
    queryKey: ["alertHistory", state, hours, page],
    queryFn: () => fetchAlertHistory({ state: state || undefined, hours, page, page_size: pageSize }),
    placeholderData: keepPreviousData,
  });
  const items = data?.items || [];
  const pages = data?.pages || 1;
  const stateLabel = (a) =>
    a.state === "resolved" ? t("al.stateResolved") : a.acknowledged ? t("al.stateAck") : t("al.stateOpen");

  return (
    <div data-testid="alerts-history">
      <div className="flex gap-2 mb-3 items-center flex-wrap">
        {["", "active", "acknowledged", "resolved"].map((s) => (
          <button key={s || "all"} className={`nv-btn ${state === s ? "nv-btn-primary" : ""}`}
            onClick={() => { setState(s); setPage(1); }} data-testid={`alerts-history-state-${s || "all"}`}>
            {s === "" ? t("al.filterAll") : s === "active" ? t("al.filterOpen")
              : s === "acknowledged" ? t("al.filterAck") : t("al.stateResolved")}
          </button>
        ))}
        <select className="nv-input px-3 py-1.5 text-[12px] rounded-sm w-auto" value={hours} data-testid="alerts-history-period"
          onChange={(e) => { setHours(Number(e.target.value)); setPage(1); }}>
          {PERIODS.map((h) => (
            <option key={h} value={h}>{h === 24 ? t("al.period24h") : h === 168 ? t("al.period7d") : t("al.period30d")}</option>
          ))}
        </select>
        <span className="text-[12px] text-nv-muted font-mono">
          {t("al.historyTotal")}: {data?.total ?? "…"}{isFetching ? " …" : ""}
        </span>
      </div>
      <div className="nv-panel overflow-x-auto">
        <table className="nv-table" data-testid="alerts-history-table">
          <thead>
            <tr>
              <th>{t("al.colTimestamp")}</th><th>{t("al.colSeverity")}</th><th>{t("al.colDevice")}</th>
              <th>{t("al.colMessage")}</th><th>{t("al.colState")}</th><th>{t("al.closedAt")}</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr><td colSpan={6} className="text-center text-nv-muted py-6">{t("al.noAlerts")}</td></tr>
            )}
            {items.map((a) => (
              <tr key={a.id}>
                <td className="font-mono text-[11px] text-nv-muted">{new Date(a.timestamp).toLocaleString()}</td>
                <td><span className={`nv-sev nv-sev-${a.severity}`}>{a.severity}</span></td>
                <td><DeviceIcon type={devicesById[a.device_id]?.device_type}/>{devicesById[a.device_id]?.name || a.device_name}</td>
                <td>{a.message}</td>
                <td className="font-mono text-[11px] uppercase">{stateLabel(a)}</td>
                <td className="font-mono text-[11px] text-nv-muted">
                  {a.resolved_at ? new Date(a.resolved_at).toLocaleString()
                    : a.acknowledged_at ? new Date(a.acknowledged_at).toLocaleString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex gap-2 mt-3 items-center justify-end">
        <button className="nv-btn" disabled={page <= 1} onClick={() => setPage(page - 1)}
          data-testid="alerts-history-prev">‹</button>
        <span className="font-mono text-[12px] text-nv-muted">{page} / {pages}</span>
        <button className="nv-btn" disabled={page >= pages} onClick={() => setPage(page + 1)}
          data-testid="alerts-history-next">›</button>
      </div>
    </div>
  );
}

export default AlertHistory;
