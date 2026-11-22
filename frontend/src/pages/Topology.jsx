import React, { useEffect, useMemo, useRef, useState } from "react";
import CytoscapeComponent from "react-cytoscapejs";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Crosshair, Minus, Plus, X } from "lucide-react";
import { api, fetchAlerts, fetchTopology } from "../lib/api";
import { useI18n } from "../lib/i18n";

const BLACK = "#252b32";
const ORANGE = "#bc580e";
const RED = "#c73437";
const BLUE = "#205ec3";
const COLOR = { online: BLACK, warning: ORANGE, offline: RED, critical: RED };
const INK = {
  server: '<rect x="9" y="2" width="22" height="28" rx="2"/><path d="M13 9h14m-14 5h14m-14 9h3"/>',
  router: '<ellipse cx="20" cy="16" rx="17" ry="10"/><path d="M10 16h20m-5-4 5 4-5 4m-10-8-5 4 5 4"/>',
  switch: '<rect x="3" y="10" width="34" height="13" rx="2"/><path d="M8 15h3m3 0h3m3 0h3m3 0h3m3 0h1M8 19h9"/>',
  plc: '<rect x="5" y="5" width="30" height="22" rx="2"/><path d="M12 5v22m7-22v22m7-22v22M8 10v4"/>',
  hmi: '<rect x="4" y="4" width="32" height="21" rx="2"/><path d="M20 25v4m-7 0h14"/>',
  sensor: '<rect x="10" y="5" width="20" height="22" rx="3"/><path d="M14 16h3l2-5 3 10 2-5h2"/>',
  unmanaged_segment: '<rect x="3" y="10" width="34" height="14" rx="2" stroke-dasharray="4 2"/><path d="M10 17h3m5 0h3m5 0h3"/>',
  asset: '<rect x="8" y="4" width="24" height="24" rx="2"/><path d="M13 11h14m-14 6h10m-10 5h7"/>',
};
const ICONS = Object.fromEntries(Object.entries(INK).map(([key, value]) => [
  key, "data:image/svg+xml;charset=utf-8," + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="32" viewBox="0 0 40 32"><g fill="white" stroke="#252b32" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round">' + value + '</g></svg>'
  ),
]));
const LAYOUT = { name: "cose", animate: false, fit: true, padding: 48, idealEdgeLength: () => 115, nodeRepulsion: () => 9000, nodeDimensionsIncludeLabels: true };
const STORAGE_KEY = "nv_topo_link_style";

function makeGraph(data, showIp) {
  if (!data) return [];
  const nodes = data.nodes.map(({ data: node }) => {
    if (node.is_zone) return { data: node };
    return { data: { ...node, icon: ICONS[node.type] || ICONS.asset,
      caption: showIp && node.ip ? node.label + "\n" + node.ip : node.label,
    }};
  });
  return [...nodes, ...data.edges];
}

function graphStyles(linkStyle) {
  return [
    { selector: "node", style: {
      "background-color": "white", "background-image": "data(icon)", "background-fit": "contain",
      "background-image-crossorigin": "anonymous", shape: "rectangle", width: 40, height: 32,
      label: "data(caption)", color: BLACK, "font-family": "Arial, Malgun Gothic, sans-serif",
      "font-size": 12, "font-weight": 600, "text-valign": "bottom", "text-margin-y": 3,
      "text-wrap": "wrap", "text-max-width": 165, "text-background-color": "white", "text-background-opacity": 1,
    }},
    { selector: "node[?is_zone]", style: {
      label: "data(label)", "background-image": "none", shape: "round-rectangle",
      "background-color": "#f7f9fb", "background-opacity": .50, "border-width": 1, "border-color": "#c8cfd5",
      padding: 22, "text-valign": "top", color: "#546170", "font-size": 11,
    }},
    { selector: "node[status='warning']", style: { "border-width": 1.5, "border-color": ORANGE } },
    { selector: "node[status='critical'], node[status='offline']", style: { "border-width": 1.5, "border-color": RED } },
    { selector: "edge", style: { width: 1.5, "line-color": BLACK, "curve-style": linkStyle } },
    { selector: "edge[kind='unmanaged']", style: { "line-style": "dashed" } },
    { selector: "edge[kind='asset']", style: { "line-style": "dotted" } },
    { selector: "edge[status='warning']", style: { "line-color": ORANGE } },
    { selector: "edge[status='down'], edge[status='critical']", style: { "line-color": RED } },
    { selector: "edge[?label]", style: {
      label: "data(label)", "font-size": 10, color: "#485361", "text-rotation": "autorotate",
      "text-background-color": "white", "text-background-opacity": 1, "text-background-padding": 2,
      "min-zoomed-font-size": 7,
    }},
    { selector: "node:selected", style: { "border-color": BLUE, "border-width": 2, "overlay-color": BLUE, "overlay-opacity": .06, "overlay-padding": 4 } },
    { selector: "edge:selected", style: { width: 3, "line-color": BLUE } },
  ];
}

export default function Topology() {
  const { t, lang } = useI18n();
  const ko = lang === "ko";
  const topology = useQuery({ queryKey: ["topology"], queryFn: fetchTopology, refetchInterval: 10000 });
  const events = useQuery({ queryKey: ["alerts"], queryFn: fetchAlerts, refetchInterval: 10000 });
  const zoneStats = useQuery({ queryKey: ["zones"], queryFn: () => api.get("/zones").then(r => r.data), refetchInterval: 10000 });
  const data = topology.data;
  const [selectedId, setSelectedId] = useState(null);
  const [collapsed, setCollapsed] = useState(() => new Set());
  const [showIp, setShowIp] = useState(false);
  const [linkStyle, setStyle] = useState(() => {
    try { return window.localStorage.getItem(STORAGE_KEY) === "taxi" ? "taxi" : "bezier"; }
    catch { return "bezier"; }
  });
  const canvas = useRef(null);
  const [cy, setCy] = useState(null);
  const elements = useMemo(() => makeGraph(data, showIp), [data, showIp]);
  const styles = useMemo(() => graphStyles(linkStyle), [linkStyle]);
  const selected = elements.find(el => el.data.id === selectedId)?.data;
  const labels = useMemo(() => new Map(data?.nodes.map(n => [n.data.id, n.data.label])), [data]);
  const devices = data?.nodes.filter(n => !n.data.is_zone && !n.data.is_asset && !n.data.is_segment);
  const recent = useMemo(() => (events.data || []).slice().sort((a,b) => Date.parse(b.timestamp) - Date.parse(a.timestamp)).slice(0, 12), [events.data]);

  function changeStyle(value) {
    setStyle(value);
    try { window.localStorage.setItem(STORAGE_KEY, value); } catch { /* Keep current session setting. */ }
  }
  function toggleZone(zone) {
    setCollapsed(prev => {
      const next = new Set(prev);
      if (next.has(zone)) next.delete(zone); else next.add(zone);
      return next;
    });
  }
  useEffect(() => {
    if (!cy || cy.destroyed()) return;
    const tap = event => {
      const el = event.target;
      if (el === cy) { setSelectedId(null); return; }
      if (el.data("is_zone")) { toggleZone(el.data("label")); return; }
      setSelectedId(el.id());
    };
    cy.on("tap", tap);
    const observer = new ResizeObserver(() => { if (!cy.destroyed()) cy.resize(); });
    observer.observe(canvas.current);
    return () => { cy.off("tap", tap); observer.disconnect(); };
  }, [cy]);

  // Place newly discovered devices near an existing neighbour without moving the
  // operator's manually arranged nodes or changing the current zoom.
  const previousGraph = useRef(null);
  useEffect(() => {
    if (!cy || cy.destroyed()) return;
    const previous = previousGraph.current;
    const ids = new Set(cy.nodes().map(n => n.id()));
    if (previous?.cy === cy) {
      cy.nodes().filter(n => !n.isParent() && !previous.ids.has(n.id())).forEach((n, index) => {
        const anchor = n.neighborhood("node").filter(adj => previous.ids.has(adj.id())).first();
        const center = anchor.length ? anchor.position() : { x: cy.extent().x1 + cy.extent().w / 2, y: cy.extent().y1 + cy.extent().h / 2 };
        const angle = index * 2.4;
        n.position({ x: center.x + Math.cos(angle) * 110, y: center.y + Math.sin(angle) * 110 });
      });
    }
    previousGraph.current = { cy, ids };
    cy.batch(() => {
      cy.nodes().forEach(n => n.style("display", !n.data("is_zone") && collapsed.has(n.data("zone")) ? "none" : "element"));
      cy.edges().forEach(e => e.style("display", e.source().visible() && e.target().visible() ? "element" : "none"));
    });
  }, [cy, elements, collapsed]);

  function closeSelection() {
    cy?.elements(":selected").unselect();
    setSelectedId(null);
  }
  function zoom(factor) {
    if (cy) cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  }
  function selectDevice(id) {
    if (!cy || !labels.has(id)) return;
    const node = cy.getElementById(id);
    const zone = node.data("zone");
    if (collapsed.has(zone)) toggleZone(zone);
    cy.elements(":selected").unselect();
    node.select();
    cy.center(node);
    setSelectedId(id);
  }

  const zones = data?.zones || [];
  const fieldRows = selected && (selected.source != null ? [
    [ko ? "시작 장비" : "Source", labels.get(selected.source)],
    [ko ? "도착 장비" : "Target", labels.get(selected.target)],
    [ko ? "연결 유형" : "Connection", selected.kind || (ko ? "장비 계층" : "Device hierarchy")],
    [ko ? "포트" : "Ports", selected.label],
    [ko ? "링크 상태" : "Link status", selected.status || (ko ? "미수집" : "Not reported")],
  ] : selected.is_segment ? [
    [t("topo.switchPort"), selected.port], [t("topo.hosts"), selected.mac_count], [t("topo.macAddresses"), selected.macs?.join(", ")],
  ] : selected.is_asset ? [
    [t("topo.type"), selected.asset_type], [t("topo.detail"), selected.detail],
  ] : [
    [t("topo.type"), selected.type], [t("topo.ip"), selected.ip], [t("topo.zone"), selected.zone],
    [t("topo.vendor"), selected.vendor], [t("topo.model"), selected.model], [t("topo.protocol"), selected.protocol], [t("topo.status"), selected.status],
  ]);
  return (
    <main className="flex min-w-0 flex-col p-4 md:p-6 gap-3 text-slate-900" data-testid="topology-page">
      <h1 className="text-[24px] font-semibold tracking-tight">{t("topo.title")}</h1>
      <div className="rounded-md border border-slate-300 bg-white">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-slate-200 px-4 py-3 text-xs">
          <b>{ko ? "모니터링" : "Monitoring"}</b>
          <div role="group" aria-label={t("topo.linkStyle")} data-testid="topology-link-style" className="flex items-center gap-1">
            <span className="mr-1">{t("topo.linkStyle")}</span>
            {["bezier","taxi"].map(style => <button key={style} type="button" aria-pressed={style === linkStyle} onClick={() => changeStyle(style)}
              data-testid={"topology-link-style-" + style} className={"rounded border px-2 py-1 " + (style === linkStyle ? "bg-slate-900 text-white" : "border-slate-300 bg-white")}>
              {t(style === "taxi" ? "topo.linkOrtho" : "topo.linkCurved")}
            </button>)}
          </div>
          <label className="flex items-center gap-2"><input type="checkbox" checked={showIp} onChange={e => setShowIp(e.target.checked)}/>{ko ? "IP 표시" : "Show IP"}</label>
          <details data-testid="topology-zones-panel" className="relative">
            <summary className="flex cursor-pointer items-center gap-1">{t("topo.zones")} ({zones.length}) <ChevronDown size={14}/></summary>
            <div className="absolute z-20 top-full mt-2 w-52 rounded border border-slate-300 bg-white p-2 shadow">
              {zones.map(zone => <button key={zone} onClick={() => toggleZone(zone)} aria-pressed={!collapsed.has(zone)} data-testid={"topology-zone-toggle-" + zone} className="flex w-full justify-between py-2 text-left">
                <span>{collapsed.has(zone) ? "+" : "−"} {zone}</span><span>{zoneStats.data?.find(s => s.name === zone)?.total ?? "—"}</span>
              </button>)}
              {!zones.length && <p className="mb-2">{t("topo.noZones")}</p>}
              <div className="flex gap-2"><button className="nv-btn" data-testid="topology-expand-all" onClick={() => setCollapsed(new Set())}>{t("topo.expandAll")}</button>
              <button className="nv-btn" data-testid="topology-collapse-all" onClick={() => setCollapsed(new Set(zones))}>{t("topo.collapseAll")}</button></div>
            </div>
          </details>
        </div>
        <div className="grid min-w-0 lg:grid-cols-[minmax(0,1fr)_minmax(230px,26%)]">
          <div ref={canvas} data-testid="topology-canvas" className="relative min-w-0 bg-white" style={{ height: "clamp(410px, 70vh, 900px)" }}>
            {data?.nodes.length > 0 && <CytoscapeComponent cy={setCy} elements={elements} stylesheet={styles} layout={LAYOUT} style={{height:"100%",width:"100%"}} wheelSensitivity={0.3}/>}
            {(!data?.nodes.length || topology.isError) && <div role="status" className="absolute left-4 top-4 rounded bg-white p-2 text-sm text-slate-600">
              {topology.isError ? (ko ? "토폴로지를 갱신할 수 없습니다." : "Topology update failed.") : topology.isLoading ? (ko ? "조회 중…" : "Loading…") : t("topo.noData")}
              {topology.isError && <button className="ml-3 underline" onClick={() => topology.refetch()}>{ko ? "다시 시도" : "Retry"}</button>}
            </div>}
          </div>
          <aside className="overflow-auto border-t border-slate-200 lg:border-t-0 lg:border-l" style={{maxHeight:"clamp(410px, 70vh, 900px)"}}>
            {selected && <section className="border-b border-slate-300 p-4" data-testid="topology-side-panel">
              <div className="flex justify-between gap-2"><h2 className="font-semibold">{selected.source != null ? (ko ? "연결 상세" : "Link details") : t("topo.nodeDetails")}</h2>
              <button type="button" onClick={closeSelection} aria-label={ko ? "닫기" : "Close"} data-testid="topology-close-panel"><X size={16}/></button></div>
              {selected.source == null && <div className="mt-3 font-semibold break-all">{selected.label}</div>}
              <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-xs">
                {fieldRows.map(([name,value]) => <React.Fragment key={name}><dt className="text-slate-600">{name}</dt><dd className="break-words">{value ?? "—"}</dd></React.Fragment>)}
              </dl>
            </section>}
            <section><h2 className="border-b border-slate-200 p-4 font-semibold">{ko ? "최근 이벤트" : "Recent events"}</h2>
              {events.isError && <p role="alert" className="px-4 py-3 text-sm">{ko ? "이벤트 갱신 실패" : "Event update failed"}</p>}
              {events.isLoading && <p className="p-4 text-sm">{ko ? "조회 중…" : "Loading…"}</p>}
              {!events.isLoading && !events.isError && !recent.length && <p className="p-4 text-sm text-slate-600">{ko ? "최근 이벤트가 없습니다." : "No recent events."}</p>}
              {recent.map(event => <button key={event.id} disabled={!labels.has(event.device_id)} onClick={() => selectDevice(event.device_id)}
                className="block w-full border-b border-slate-200 px-4 py-3 text-left enabled:hover:bg-slate-50">
                <div className="flex items-start justify-between gap-2 text-xs"><strong className="break-all">{event.device_name}</strong>
                <time title={event.timestamp} className="text-slate-500">{new Date(event.timestamp).toLocaleTimeString(ko ? "ko-KR" : "en-GB",{hour:"2-digit", minute:"2-digit", hour12:false})}</time></div>
                <div className="mt-1 border-l-2 pl-2 text-xs break-words" style={{borderColor:event.state === "resolved" ? BLACK : COLOR[event.severity] || BLACK}}>{event.message}</div>
              </button>)}
            </section>
          </aside>
        </div>
        <footer className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-slate-200 px-4 py-2 text-xs">
          <span>{ko ? "장비" : "Devices"} <b>{devices?.length ?? "—"}</b></span><span>{ko ? "연결" : "Links"} <b>{data?.edges.length ?? "—"}</b></span>
          {[[BLACK,ko?"기본 연결":"Connection"],[ORANGE,ko?"주의":"Warning"],[RED,ko?"단절 / 심각":"Down / critical"],[BLUE,ko?"선택":"Selected"]].map(([color,name]) =>
            <span key={color} className="inline-flex items-center gap-1.5"><i style={{background:color,width:17,height:2}}/>{name}</span>)}
          <div className="ml-auto flex gap-2">
            <button className="nv-btn" aria-label={ko?"축소":"Zoom out"} onClick={() => zoom(0.8)}><Minus size={15}/></button>
            <button className="nv-btn" aria-label={ko?"확대":"Zoom in"} onClick={() => zoom(1.25)}><Plus size={15}/></button>
            <button className="nv-btn" aria-label={ko?"화면 맞춤":"Fit to screen"} onClick={() => cy?.fit(cy.elements(":visible"), 42)}><Crosshair size={15}/></button>
          </div>
        </footer>
      </div>
    </main>
  );
}
