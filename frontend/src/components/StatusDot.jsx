import React from "react";

export const StatusDot = ({ status, pulse = false, label, testId }) => {
  const cls =
    status === "online"
      ? "nv-led-online"
      : status === "warning"
      ? "nv-led-warning"
      : status === "critical"
      ? "nv-led-critical"
      : "nv-led-offline";
  return (
    <span className="inline-flex items-center gap-2" data-testid={testId}>
      <span className={`nv-led ${cls} ${pulse ? "animate-led-pulse" : ""}`} />
      {label ? <span className="text-[12px] uppercase tracking-wider text-nv-muted">{label}</span> : null}
    </span>
  );
};

export default StatusDot;
