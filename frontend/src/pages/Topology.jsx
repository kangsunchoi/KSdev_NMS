import React, { useMemo, useRef, useEffect, useState } from "react";
import CytoscapeComponent from "react-cytoscapejs";
import { useQuery } from "@tanstack/react-query";
import { fetchTopology } from "../lib/api";
import { api } from "../lib/api";
import { StatusDot } from "../components/StatusDot";
import { X, ChevronDown, ChevronRight, Boxes } from "lucide-react";
import { useI18n } from "../lib/i18n";

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
  unmanaged_segment: "round-rectangle",
  asset: "round-rectangle",
};

const TYPE_BASE = {
  switch: "#3b82f6",
  plc: "#16c79a",
  hmi: "#a78bfa",
  sensor: "#94a3b8",
  unmanaged_segment: "#475569",
  asset: "#0e7490",
};

export default function Topology() {
  const { t } = useI18n();
  const { data, isLoading } = useQuery({
    queryKey: ["topology"],
    queryFn: fetchTopology,
    refetchInterval: 10000,
  });
  const { data: zoneStats = [] } = useQuery({
    queryKey: ["zones"],
    queryFn: () => api.get("/zones").then((r) => r.data),
    refetchInterval: 8000,
  });

  const [selected, setSelected] = useState(null);
  const [collapsedZones, setCollapsedZones] = useState(() => new Set());
  const cyRef = useRef(null);

  const zones = data?.zones || [];

  const elements = useMemo(() => {
    if (!data) return [];
    const zoneNodes = data.nodes.filter((n) => n.data.is_zone).map((n) => ({
      data: { ...n.data },
    }));
    const deviceNodes = data.nodes.filter((n) => !n.data.is_zone).map((n) => ({
      data: {
        ...n.data,
        bg: TYPE_BASE[n.data.type] || "#94a3b8",
        border: STATUS_COLOR[n.data.status] || TYPE_BASE[n.data.type] || "#94a3b8",
        shape: TYPE_SHAPE[n.data.type] || "ellipse",
      },
    }));
    return [...zoneNodes, ...deviceNodes, ...data.edges];
  }, [data]);

  // Apply collapsed state by hiding device nodes of collapsed zones
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.nodes().forEach((n) => {
        const z = n.data("zone");
        const isZoneNode = n.data("is_zone");
        if (isZoneNode) {
          // keep zone parent visible always; just collapse its children
          return;
        }
        if (z && collapsedZones.has(z)) {
          n.style("display", "none");
          n.connectedEdges().style("display", "none");
        } else {
          n.style("display", "element");
          n.connectedEdges().style("display", "element");
        }
      });
    });
    cy.layout({ name: "breadthfirst", directed: true, padding: 30, spacingFactor: 1.1 }).run();
  }, [collapsedZones, elements]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const handler = (evt) => {
      const d = evt.target.data();
      if (d.is_zone) {
        // toggle collapse on zone tap
        setCollapsedZones((prev) => {
          const next = new Set(prev);
          if (next.has(d.label)) next.delete(d.label);
          else next.add(d.label);
          return next;
        });
        return;
      }
      setSelected(d);
    };
    const unselect = () => setSelected(null);
    cy.on("tap", "node", handler);
    cy.on("tap", (e) => { if (e.target === cy) unselect(); });
    return () => { cy.removeListener("tap"); };
  }, [elements]);

  const toggleZone = (z) => {
    setCollapsedZones((prev) => {
      const next = new Set(prev);
      if (next.has(z)) next.delete(z);
      else next.add(z);
      return next;
    });
  };

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
    { selector: "node[type = 'switch']", style: { width: 56, height: 30 } },
    { selector: "node[type = 'plc']", style: { width: 44, height: 40 } },
    {
      selector: "node[?is_zone]",
      style: {
        "background-color": "#16213e",
        "background-opacity": 0.45,
        "border-color": "#2a3b55",
        "border-width": 1,
        "border-style": "dashed",
        shape: "round-rectangle",
        label: "data(label)",
        color: "#16c79a",
        "font-size": 11,
        "font-family": "JetBrains Mono, monospace",
        "text-valign": "top",
        "text-halign": "left",
        "text-margin-y": 6,
        "text-margin-x": 10,
        "text-transform": "uppercase",
        "padding-top": "16px",
        "padding-bottom": "12px",
        "padding-left": "12px",
        "padding-right": "12px",
      },
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
    {
      selector: "edge[kind = 'unmanaged']",
      style: { "line-style": "dashed", "line-color": "#64748b", "target-arrow-shape": "none" },
    },
    {
      selector: "edge[kind = 'asset']",
      style: { "line-style": "dotted", "line-color": "#0e7490", width: 1 },
    },
    {
      selector: "node[?is_segment]",
      style: {
        "background-opacity": 0.3,
        "border-style": "dashed",
        "border-color": "#94a3b8",
        shape: "round-rectangle",
        width: 54,
        height: 34,
        "font-size": 9,
      },
    },
    {
      selector: "node[?is_asset]",
      style: { width: 24, height: 24, "font-size": 9 },
    },
  ];

  return (
    <div className="p-6 flex flex-col h-screen" data-testid="topology-page">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-[11px] tracking-[0.2em] text-nv-muted uppercase font-mono">{t("topo.networkMap")}</div>
          <h1 className="text-[22px] font-semibold tracking-tight">{t("topo.title")}</h1>
        </div>
        <div className="flex items-center gap-4 text-[11px] font-mono">
          <Legend />
        </div>
      </div>

      <div className="flex-1 flex gap-3 min-h-0">
        {/* Left: zone controls */}
        <div className="nv-panel w-[200px] flex-shrink-0" data-testid="topology-zones-panel">
          <div className="px-3 py-2 border-b border-nv-border flex items-center gap-2">
            <Boxes size={14} className="text-[#16c79a]" />
            <span className="nv-section-title">{t("topo.zones")}</span>
          </div>
          <div>
            {zones.map((z) => {
              const collapsed = collapsedZones.has(z);
              const stat = zoneStats.find((s) => s.name === z);
              return (
                <button
                  key={z}
                  type="button"
                  onClick={() => toggleZone(z)}
                  className="w-full flex items-center gap-2 px-3 py-2 text-[12px] hover:bg-[#1c2748] border-b border-[#1f2a44] last:border-0 text-left"
                  data-testid={`topology-zone-toggle-${z}`}
                >
                  {collapsed ? <ChevronRight size={12} className="text-nv-muted" /> : <ChevronDown size={12} className="text-[#16c79a]" />}
                  <span className="font-mono text-nv-text flex-1">{z}</span>
                  {stat && (
                    <span className="flex items-center gap-1 font-mono text-[10px]">
                      <span className="text-[#16c79a]">{stat.online}</span>
                      <span className="text-nv-muted">/</span>
                      <span className="text-nv-text">{stat.total}</span>
                    </span>
                  )}
                </button>
              );
            })}
            {zones.length === 0 && (
              <div className="px-3 py-4 text-[11px] text-nv-muted font-mono text-center">{t("topo.noZones")}</div>
            )}
            <div className="px-3 py-2 border-t border-nv-border flex gap-2">
              <button
                className="nv-btn flex-1 justify-center"
                onClick={() => setCollapsedZones(new Set())}
                data-testid="topology-expand-all"
              >
                {t("topo.expandAll")}
              </button>
              <button
                className="nv-btn flex-1 justify-center"
                onClick={() => setCollapsedZones(new Set(zones))}
                data-testid="topology-collapse-all"
              >
                {t("topo.collapseAll")}
              </button>
            </div>
          </div>
        </div>

        {/* Canvas */}
        <div className="nv-panel flex-1 relative overflow-hidden" data-testid="topology-canvas">
          <div className="absolute inset-0 nv-topo">
            {!isLoading && elements.length > 0 && (
              <CytoscapeComponent
                cy={(cy) => { cyRef.current = cy; }}
                elements={elements}
                style={{ width: "100%", height: "100%" }}
                layout={{ name: "breadthfirst", directed: true, padding: 30, spacingFactor: 1.1 }}
                stylesheet={stylesheet}
                wheelSensitivity={0.3}
              />
            )}
            {!isLoading && elements.length === 0 && (
              <div className="h-full flex items-center justify-center text-nv-muted text-[12px] font-mono">{t("topo.noData")}</div>
            )}
          </div>
        </div>

        {selected && (
          <div className="nv-panel w-[320px] flex-shrink-0" data-testid="topology-side-panel">
            <div className="px-4 py-3 border-b border-nv-border flex items-center justify-between">
              <span className="nv-section-title">{t("topo.nodeDetails")}</span>
              <button onClick={() => setSelected(null)} className="text-nv-muted hover:text-white" data-testid="topology-close-panel">
                <X size={14} />
              </button>
            </div>
            <div className="p-4 space-y-3">
              {selected.is_segment ? (
                <>
                  <div>
                    <div className="font-mono text-[14px] text-nv-text">{selected.label}</div>
                    <div className="text-[11px] uppercase tracking-wider text-nv-muted">{t("topo.unmanagedSegment")}</div>
                  </div>
                  <div className="grid grid-cols-2 gap-y-2 text-[12px]">
                    <div className="nv-label">{t("topo.switchPort")}</div><div className="font-mono text-[#16c79a]">{selected.port}</div>
                    <div className="nv-label">{t("topo.hosts")}</div><div className="font-mono">{selected.mac_count}</div>
                  </div>
                  <div>
                    <div className="nv-label mb-1">{t("topo.macAddresses")}</div>
                    <div className="space-y-1 max-h-[220px] overflow-auto">
                      {(selected.macs || []).map((m) => (
                        <div key={m} className="font-mono text-[11px] text-nv-text">{m}</div>
                      ))}
                    </div>
                  </div>
                </>
              ) : selected.is_asset ? (
                <>
                  <div>
                    <div className="font-mono text-[14px] text-nv-text">{selected.label}</div>
                    <div className="text-[11px] uppercase tracking-wider text-nv-muted">{t("topo.logicalAsset")}</div>
                  </div>
                  <div className="grid grid-cols-2 gap-y-2 text-[12px]">
                    <div className="nv-label">{t("topo.type")}</div><div className="font-mono text-[#0e7490]">{selected.asset_type}</div>
                    <div className="nv-label">{t("topo.detail")}</div><div className="font-mono">{selected.detail || "—"}</div>
                  </div>
                </>
              ) : (
                <>
                  <div className="flex items-center gap-3">
                    <StatusDot status={selected.status} pulse={selected.status !== "online"} />
                    <div>
                      <div className="font-mono text-[14px] text-nv-text">{selected.label}</div>
                      <div className="text-[11px] uppercase tracking-wider text-nv-muted">{selected.type}</div>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-y-2 text-[12px]">
                    <div className="nv-label">{t("topo.ip")}</div><div className="font-mono text-[#16c79a]">{selected.ip}</div>
                    <div className="nv-label">{t("topo.zone")}</div><div className="font-mono">{selected.zone || "—"}</div>
                    <div className="nv-label">{t("topo.vendor")}</div><div className="font-mono">{selected.vendor}</div>
                    <div className="nv-label">{t("topo.model")}</div><div className="font-mono">{selected.model}</div>
                    <div className="nv-label">{t("topo.protocol")}</div><div className="font-mono">{selected.protocol}</div>
                    <div className="nv-label">{t("topo.status")}</div><div className="font-mono uppercase">{selected.status}</div>
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const ZoneStatusDots = () => null;

const Legend = () => (
  <div className="flex items-center gap-4 text-nv-muted">
    <span className="flex items-center gap-1.5"><span className="w-3 h-2 bg-[#3b82f6] inline-block" /> SWITCH</span>
    <span className="flex items-center gap-1.5"><span className="w-3 h-3 bg-[#16c79a] inline-block" style={{clipPath:"polygon(25% 0,75% 0,100% 50%,75% 100%,25% 100%,0 50%)"}} /> PLC</span>
    <span className="flex items-center gap-1.5"><span className="w-3 h-3 bg-[#a78bfa] inline-block rotate-45" /> HMI</span>
    <span className="flex items-center gap-1.5"><span className="w-3 h-3 bg-[#94a3b8] inline-block rounded-full" /> SENSOR</span>
    <span className="flex items-center gap-1.5"><span className="w-3 h-2 bg-[#475569] inline-block border border-dashed border-[#94a3b8]" /> SEGMENT</span>
    <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 bg-[#0e7490] inline-block" /> ASSET</span>
  </div>
);
