import React from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchDeviceInterfaces } from "../lib/api";
import { X } from "lucide-react";

// bits/sec -> human readable
const fmtBps = (v) => {
  if (v === null || v === undefined) return "—";
  if (v < 1000) return `${v.toFixed(0)} bps`;
  if (v < 1e6) return `${(v / 1e3).toFixed(1)} Kbps`;
  if (v < 1e9) return `${(v / 1e6).toFixed(2)} Mbps`;
  return `${(v / 1e9).toFixed(2)} Gbps`;
};

const fmtSpeed = (m) => {
  if (!m) return "—";
  if (m >= 1000) return `${m / 1000}G`;
  return `${m}M`;
};

const OperBadge = ({ oper }) => {
  const up = oper === 1;
  const down = oper === 2;
  const color = up ? "#16c79a" : down ? "#e74c3c" : "#64748b";
  const label = up ? "up" : down ? "down" : "—";
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-[11px]">
      <span className="w-2 h-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
};

export const InterfaceModal = ({ device, onClose }) => {
  const { data, isLoading } = useQuery({
    queryKey: ["interfaces", device?.id],
    queryFn: () => fetchDeviceInterfaces(device.id),
    enabled: !!device,
    refetchInterval: 5000,
  });

  if (!device) return null;

  const rows = data?.interfaces || [];
  const ts = data?.ts ? new Date(data.ts).toLocaleTimeString() : null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
      data-testid="interface-modal"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="nv-panel w-[960px] max-w-full max-h-[88vh] flex flex-col">
        <div className="px-4 py-3 border-b border-nv-border flex items-center justify-between">
          <div>
            <div className="nv-section-title">Interfaces</div>
            <div className="font-mono text-[14px] text-nv-text mt-0.5">
              {device.name} <span className="text-nv-muted">/ {device.ip}</span>
            </div>
          </div>
          <button onClick={onClose} className="text-nv-muted hover:text-white" data-testid="interface-close">
            <X size={16} />
          </button>
        </div>

        <div className="px-4 py-2 border-b border-nv-border flex items-center gap-3">
          <span className="font-mono text-[11px] text-nv-muted">
            {rows.length} ports {ts ? `· updated ${ts}` : ""} {isLoading ? "· loading" : ""}
          </span>
        </div>

        <div className="overflow-auto p-2">
          {rows.length === 0 ? (
            <div className="h-[200px] flex items-center justify-center text-nv-muted font-mono text-[12px]">
              NO INTERFACE DATA — collected via SNMP every ~30s. bps appears after the 2nd poll.
            </div>
          ) : (
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-nv-muted font-mono text-[11px] uppercase tracking-wider border-b border-nv-border">
                  <th className="text-left px-3 py-2">Interface</th>
                  <th className="text-left px-3 py-2">Status</th>
                  <th className="text-right px-3 py-2">Speed</th>
                  <th className="text-right px-3 py-2">In</th>
                  <th className="text-right px-3 py-2">Out</th>
                  <th className="text-right px-3 py-2">Err In/Out</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.ifindex} className="border-b border-nv-border/40" data-testid={`if-row-${r.ifindex}`}>
                    <td className="px-3 py-1.5 font-mono">{r.name || r.ifindex}</td>
                    <td className="px-3 py-1.5"><OperBadge oper={r.oper} /></td>
                    <td className="px-3 py-1.5 text-right font-mono text-nv-muted">{fmtSpeed(r.speed_mbps)}</td>
                    <td className="px-3 py-1.5 text-right font-mono text-[#16c79a]">{fmtBps(r.in_bps)}</td>
                    <td className="px-3 py-1.5 text-right font-mono text-[#60a5fa]">{fmtBps(r.out_bps)}</td>
                    <td className="px-3 py-1.5 text-right font-mono text-nv-muted">
                      {(r.in_errors ?? 0)}/{(r.out_errors ?? 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
};

export default InterfaceModal;
