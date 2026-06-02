import React, { useMemo, useRef, useEffect, useState } from "react";
import CytoscapeComponent from "react-cytoscapejs";
import { useQuery } from "@tanstack/react-query";
import { fetchTopology } from "../lib/api";
import { StatusDot } from "../components/StatusDot";
import { X } from "lucide-react";

const STATUS_COLOR = {
  online: "#16c79a",
  warning: "#f4d03f",
  critical: "#e74c3c",
  offline: "#6b7280",
};

const TYPE_SHAPE = {
  switch: "round-rectangle",
  plc: "hexagon",
  hmi: "diamond",
  sensor: "ellipse",
};

const TYPE_BASE = {
  switch: "#3b82f6", // blue
  plc: "#16c79a",    // green
  hmi: "#a78bfa",    // purple
  sensor: "#94a3b8", // gray
};

export default function Topology() {
  const { data, isLoading } = useQuery({
    queryKey: ["topology"],
    queryFn: fetchTopology,
    refetchInterval: 5000,
  });

  const [selected, setSelected] = useState(null);
  const cyRef = useRef(null);

  const elements = useMemo(() => {
    if (!data) return [];
    const nodes = data.nodes.map((n) => ({
      data: {
        ...n.data,
        bg: TYPE_BASE[n.data.type] || "#94a3b8",
        border: STATUS_COLOR[n.data.status] || "#94a3b8",
        shape: TYPE_SHAPE[n.data.type] || "ellipse",
      },
    }));
    return [...nodes, ...data.edges];
  }, [data]);

  // Bind selection event when cy ready
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const handler = (evt) => setSelected(evt.target.data());
    const unselect = () => setSelected(null);
    cy.on("tap", "node", handler);
    cy.on("tap", (e) => { if (e.target === cy) unselect(); });
    return () => { cy.removeListener("tap"); };
  }, [elements]);

  const stylesheet = [
    {
      selector: "node",
      style: {
        "background-color": "data(bg)",
        "border-color": "data(border)",
        "border-width": 2,
        shape: "data(shape)",
        label: "data(label)",
        color: "#f8f9fa",
        "font-family": "JetBrains Mono, monospace",
        "font-size": 10,
        "text-valign": "bottom",
        "text-margin-y": 6,
        "text-outline-color": "#1a1a2e",
        "text-outline-width": 2,
        width: 36,
        height: 36,
      },
    },
    {
      selector: "node[type = 'switch']",
      style: { width: 56, height: 30 },
    },
    {
      selector: "node[type = 'plc']",
      style: { width: 44, height: 40 },
    },
    {
      selector: "node:selected",
      style: {
        "border-color": "#16c79a",
        "border-width": 4,
        "overlay-color": "#16c79a",
        "overlay-opacity": 0.18,
        "overlay-padding": 8,
      },
    },
    {
      selector: "edge",
      style: {
        width: 1.2,
        "line-color": "#2a3b55",
        "target-arrow-color": "#2a3b55",
        "curve-style": "bezier",
      },
    },
  ];

  return (
    <div className="p-6 flex flex-col h-screen" data-testid="topology-page">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-[11px] tracking-[0.2em] text-nv-muted uppercase font-mono">Network Map</div>
          <h1 className="text-[22px] font-semibold tracking-tight">Topology Viewer</h1>
        </div>
        <div className="flex items-center gap-4 text-[11px] font-mono">
          <Legend />
        </div>
      </div>

      <div className="flex-1 flex gap-3 min-h-0">
        <div className="nv-panel flex-1 relative overflow-hidden" data-testid="topology-canvas">
          <div className="absolute inset-0 nv-topo">
            {!isLoading && elements.length > 0 && (
              <CytoscapeComponent
                cy={(cy) => { cyRef.current = cy; }}
                elements={elements}
                style={{ width: "100%", height: "100%" }}
                layout={{ name: "breadthfirst", directed: true, padding: 30, spacingFactor: 1.2 }}
                stylesheet={stylesheet}
                wheelSensitivity={0.3}
              />
            )}
            {!isLoading && elements.length === 0 && (
              <div className="h-full flex items-center justify-center text-nv-muted text-[12px] font-mono">NO TOPOLOGY DATA</div>
            )}
          </div>
        </div>

        {selected && (
          <div className="nv-panel w-[320px] flex-shrink-0" data-testid="topology-side-panel">
            <div className="px-4 py-3 border-b border-nv-border flex items-center justify-between">
              <span className="nv-section-title">Node Details</span>
              <button onClick={() => setSelected(null)} className="text-nv-muted hover:text-white" data-testid="topology-close-panel">
                <X size={14} />
              </button>
            </div>
            <div className="p-4 space-y-3">
              <div className="flex items-center gap-3">
                <StatusDot status={selected.status} pulse={selected.status !== "online"} />
                <div>
                  <div className="font-mono text-[14px] text-nv-text">{selected.label}</div>
                  <div className="text-[11px] uppercase tracking-wider text-nv-muted">{selected.type}</div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-y-2 text-[12px]">
                <div className="nv-label">IP</div><div className="font-mono text-[#16c79a]">{selected.ip}</div>
                <div className="nv-label">Vendor</div><div className="font-mono">{selected.vendor}</div>
                <div className="nv-label">Model</div><div className="font-mono">{selected.model}</div>
                <div className="nv-label">Protocol</div><div className="font-mono">{selected.protocol}</div>
                <div className="nv-label">Status</div><div className="font-mono uppercase">{selected.status}</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const Legend = () => (
  <div className="flex items-center gap-4 text-nv-muted">
    <span className="flex items-center gap-1.5"><span className="w-3 h-2 bg-[#3b82f6] inline-block" /> SWITCH</span>
    <span className="flex items-center gap-1.5"><span className="w-3 h-3 bg-[#16c79a] inline-block" style={{clipPath:"polygon(25% 0,75% 0,100% 50%,75% 100%,25% 100%,0 50%)"}} /> PLC</span>
    <span className="flex items-center gap-1.5"><span className="w-3 h-3 bg-[#a78bfa] inline-block rotate-45" /> HMI</span>
    <span className="flex items-center gap-1.5"><span className="w-3 h-3 bg-[#94a3b8] inline-block rounded-full" /> SENSOR</span>
  </div>
);
