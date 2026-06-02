import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchAlerts, acknowledgeAlert, deleteAlert } from "../lib/api";
import { Check, Trash2 } from "lucide-react";
import { toast } from "sonner";

const SEV_ORDER = { critical: 0, warning: 1, info: 2 };

export default function Alerts() {
  const qc = useQueryClient();
  const { data: alerts = [] } = useQuery({
    queryKey: ["alerts"],
    queryFn: fetchAlerts,
    refetchInterval: 4000,
  });
  const [filter, setFilter] = useState("all"); // all | open | acknowledged

  const mAck = useMutation({
    mutationFn: acknowledgeAlert,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["alerts"] }); toast.success("Alert acknowledged"); },
  });
  const mDel = useMutation({
    mutationFn: deleteAlert,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["alerts"] }); toast.success("Alert removed"); },
  });

  const filtered = alerts
    .filter((a) =>
      filter === "all" ? true : filter === "open" ? !a.acknowledged : a.acknowledged
    )
    .sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity]);

  const counts = {
    all: alerts.length,
    open: alerts.filter((a) => !a.acknowledged).length,
    acknowledged: alerts.filter((a) => a.acknowledged).length,
  };

  return (
    <div className="p-6" data-testid="alerts-page">
      <div className="flex items-center justify-between mb-5">
        <div>
          <div className="text-[11px] tracking-[0.2em] text-nv-muted uppercase font-mono">Event Log</div>
          <h1 className="text-[22px] font-semibold tracking-tight">Alerts</h1>
        </div>
        <div className="flex gap-2">
          {["all", "open", "acknowledged"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`nv-btn ${filter === f ? "nv-btn-primary" : ""}`}
              data-testid={`alerts-filter-${f}`}
            >
              {f.toUpperCase()} <span className="font-mono opacity-70">{counts[f]}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="nv-panel overflow-hidden">
        <table className="nv-table" data-testid="alerts-table">
          <thead>
            <tr>
              <th style={{ width: 110 }}>Severity</th>
              <th style={{ width: 140 }}>Device</th>
              <th>Message</th>
              <th style={{ width: 160 }}>Timestamp</th>
              <th style={{ width: 100 }}>State</th>
              <th style={{ width: 110 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((a) => (
              <tr key={a.id} data-testid={`alert-row-${a.id}`}>
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
                <td className="text-[12px] text-nv-text">{a.message}</td>
                <td className="font-mono text-[11px] text-nv-muted">
                  {new Date(a.timestamp).toLocaleString()}
                </td>
                <td>
                  <span className={`font-mono text-[11px] uppercase ${a.acknowledged ? "text-[#16c79a]" : "text-[#f4d03f]"}`}>
                    {a.acknowledged ? "ACK" : "OPEN"}
                  </span>
                </td>
                <td>
                  <div className="flex gap-2">
                    <button
                      className="nv-btn"
                      onClick={() => mAck.mutate(a.id)}
                      disabled={a.acknowledged}
                      data-testid={`alert-ack-${a.id}`}
                      title="Acknowledge"
                    >
                      <Check size={12} /> ACK
                    </button>
                    <button
                      className="text-nv-muted hover:text-[#e74c3c] px-1"
                      onClick={() => mDel.mutate(a.id)}
                      data-testid={`alert-delete-${a.id}`}
                      title="Delete"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={6} className="text-center py-10 text-nv-muted font-mono text-[12px]">NO ALERTS</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
