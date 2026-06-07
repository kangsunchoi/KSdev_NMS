import React, { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchDevices,
  createDevice,
  updateDevice,
  deleteDevice,
  resetAll,
} from "../lib/api";
import { exportCsv } from "../lib/csv";
import { StatusDot } from "../components/StatusDot";
import { MetricChartModal } from "../components/MetricChartModal";
import { InterfaceModal } from "../components/InterfaceModal";
import { useI18n } from "../lib/i18n";
import { Plus, Pencil, Trash2, Eraser, Search, Download, Network, LineChart as LineIcon } from "lucide-react";
import { toast } from "sonner";

const TYPES = ["switch", "plc", "hmi", "sensor"];
const ZONES = ["Cell-A", "Cell-B", "Utilities"];

const empty = {
  name: "",
  ip: "",
  vendor: "",
  model: "",
  protocol: "",
  device_type: "switch",
  zone: "",
};

const DeviceModal = ({ open, onClose, initial, onSubmit }) => {
  const { t } = useI18n();
  const [form, setForm] = useState(initial || empty);
  React.useEffect(() => setForm(initial || empty), [initial, open]);

  if (!open) return null;
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const FIELDS = [
    { k: "name", l: t("dev.fName") },
    { k: "ip", l: t("dev.fIp") },
    { k: "vendor", l: t("dev.fVendor") },
    { k: "model", l: t("dev.fModel") },
    { k: "protocol", l: t("dev.fProtocol") },
  ];

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center" data-testid="device-modal">
      <div className="nv-panel w-[480px] max-w-[92vw]">
        <div className="px-4 py-3 border-b border-nv-border flex items-center justify-between">
          <span className="nv-section-title">{initial?.id ? t("dev.editDevice") : t("dev.addDevice")}</span>
          <button className="text-nv-muted hover:text-white" onClick={onClose} data-testid="device-modal-close">✕</button>
        </div>
        <div className="p-4 space-y-3">
          {FIELDS.map(({ k, l }) => (
            <div key={k}>
              <div className="nv-label mb-1">{l}</div>
              <input
                className="nv-input w-full px-3 py-2 text-[13px] rounded-sm"
                value={form[k]}
                onChange={(e) => set(k, e.target.value)}
                data-testid={`device-form-${k}`}
              />
            </div>
          ))}
          <div>
            <div className="nv-label mb-1">{t("dev.fType")}</div>
            <div className="flex gap-2">
              {TYPES.map((ty) => (
                <button
                  type="button"
                  key={ty}
                  onClick={() => set("device_type", ty)}
                  className={`nv-btn ${form.device_type === ty ? "nv-btn-primary" : ""}`}
                  data-testid={`device-form-type-${ty}`}
                >
                  {ty.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="nv-label mb-1">{t("dev.fZone")}</div>
            <div className="flex gap-2 flex-wrap">
              <button
                type="button"
                onClick={() => set("zone", "")}
                className={`nv-btn ${!form.zone ? "nv-btn-primary" : ""}`}
                data-testid="device-form-zone-none"
              >
                {t("common.none").toUpperCase()}
              </button>
              {ZONES.map((z) => (
                <button
                  type="button"
                  key={z}
                  onClick={() => set("zone", z)}
                  className={`nv-btn ${form.zone === z ? "nv-btn-primary" : ""}`}
                  data-testid={`device-form-zone-${z}`}
                >
                  {z.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="px-4 py-3 border-t border-nv-border flex justify-end gap-2">
          <button className="nv-btn" onClick={onClose} data-testid="device-form-cancel">{t("common.cancel")}</button>
          <button
            className="nv-btn nv-btn-primary"
            onClick={() => onSubmit(form)}
            disabled={!form.name || !form.ip}
            data-testid="device-form-submit"
          >
            {initial?.id ? t("common.save") : t("common.create")}
          </button>
        </div>
      </div>
    </div>
  );
};

export default function Devices() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const { data: devices = [], isLoading } = useQuery({
    queryKey: ["devices"],
    queryFn: fetchDevices,
  });

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [chartDevice, setChartDevice] = useState(null);
  const [ifDevice, setIfDevice] = useState(null);

  const mCreate = useMutation({
    mutationFn: createDevice,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["devices"] }); toast.success(t("dev.created")); },
    onError: () => toast.error(t("dev.createFail")),
  });
  const mUpdate = useMutation({
    mutationFn: ({ id, payload }) => updateDevice(id, payload),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["devices"] }); toast.success(t("dev.updated")); },
    onError: () => toast.error(t("dev.updateFail")),
  });
  const mDelete = useMutation({
    mutationFn: deleteDevice,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["devices"] }); toast.success(t("dev.removed")); },
    onError: () => toast.error(t("dev.deleteFail")),
  });

  const onSubmit = (form) => {
    if (editing?.id) {
      mUpdate.mutate({ id: editing.id, payload: form });
    } else {
      mCreate.mutate(form);
    }
    setModalOpen(false);
    setEditing(null);
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return devices
      .filter((d) => filter === "all" || d.device_type === filter)
      .filter((d) =>
        !q ||
        d.name.toLowerCase().includes(q) ||
        d.ip.toLowerCase().includes(q) ||
        d.vendor.toLowerCase().includes(q) ||
        d.model.toLowerCase().includes(q) ||
        d.protocol.toLowerCase().includes(q)
      );
  }, [devices, filter, search]);

  const handleExport = () => {
    const rows = filtered.map((d) => ({
      name: d.name,
      type: d.device_type,
      zone: d.zone || "",
      ip: d.ip,
      vendor: d.vendor,
      model: d.model,
      protocol: d.protocol,
      status: d.status,
      latency_ms: d.latency_ms,
      packet_loss: d.packet_loss,
      cpu_pct: d.cpu_pct,
      uptime_pct: d.uptime_pct,
      last_seen: d.last_seen,
    }));
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    exportCsv(`netvision-devices-${ts}.csv`, rows);
    toast.success(`${rows.length} ${t("dev.exportedSuffix")}`);
  };

  return (
    <div className="p-6" data-testid="devices-page">
      <div className="flex items-center justify-between mb-5">
        <div>
          <div className="text-[11px] tracking-[0.2em] text-nv-muted uppercase font-mono">{t("dev.assetRegistry")}</div>
          <h1 className="text-[22px] font-semibold tracking-tight">{t("dev.inventory")}</h1>
        </div>
        <div className="flex items-center gap-2">
          <button
            className="nv-btn"
            onClick={handleExport}
            disabled={filtered.length === 0}
            data-testid="devices-export-csv-btn"
          >
            <Download size={14} /> {t("common.exportCsv")}
          </button>
          <button
            className="nv-btn nv-btn-danger"
            onClick={async () => { if (window.confirm(t("dev.confirmReset"))) { await resetAll(); qc.invalidateQueries(); toast.success(t("dev.cleared")); } }}
            data-testid="devices-reset-btn"
          >
            <Eraser size={14} /> {t("dev.reset")}
          </button>
          <button
            className="nv-btn nv-btn-primary"
            onClick={() => { setEditing(null); setModalOpen(true); }}
            data-testid="devices-add-btn"
          >
            <Plus size={14} /> {t("dev.addDevice")}
          </button>
        </div>
      </div>

      {/* Filter chips + search */}
      <div className="flex gap-2 mb-3 items-center flex-wrap">
        {["all", ...TYPES].map((ty) => (
          <button
            key={ty}
            onClick={() => setFilter(ty)}
            className={`nv-btn ${filter === ty ? "nv-btn-primary" : ""}`}
            data-testid={`device-filter-${ty}`}
          >
            {ty === "all" ? t("common.all").toUpperCase() : ty.toUpperCase()}
          </button>
        ))}
        <div className="ml-2 flex items-center gap-2 flex-1 min-w-[200px]">
          <Search size={14} className="text-nv-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("dev.searchPlaceholder")}
            className="nv-input flex-1 px-3 py-1.5 text-[12px] rounded-sm max-w-[420px]"
            data-testid="devices-search-input"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="text-[11px] text-nv-muted hover:text-white font-mono"
              data-testid="devices-search-clear"
            >
              {t("common.clear").toUpperCase()}
            </button>
          )}
        </div>
        <div className="text-[11px] font-mono text-nv-muted">
          {filtered.length} / {devices.length} {t("dev.devicesUnit")}
        </div>
      </div>

      <div className="nv-panel overflow-hidden">
        <table className="nv-table" data-testid="devices-table">
          <thead>
            <tr>
              <th>{t("dev.colStatus")}</th>
              <th>{t("dev.colName")}</th>
              <th>{t("dev.colType")}</th>
              <th>{t("dev.colZone")}</th>
              <th>{t("dev.colIp")}</th>
              <th>{t("dev.colVendorModel")}</th>
              <th>{t("dev.colProtocol")}</th>
              <th>{t("dev.colLatency")}</th>
              <th>CPU</th>
              <th style={{ width: 140 }}>{t("dev.colActions")}</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((d) => (
              <tr key={d.id} data-testid={`device-row-${d.id}`}>
                <td>
                  <StatusDot status={d.status} pulse={d.status !== "online"} testId={`device-status-${d.id}`} />
                </td>
                <td className="font-mono text-nv-text">{d.name}</td>
                <td className="uppercase text-[11px] tracking-wider text-nv-muted">{d.device_type}</td>
                <td className="font-mono text-[11px] text-[#16c79a]">{d.zone || "—"}</td>
                <td className="font-mono text-[#16c79a]">{d.ip}</td>
                <td className="text-[12px]">{d.vendor} <span className="text-nv-muted">/ {d.model}</span></td>
                <td className="font-mono text-[11px] text-nv-muted">{d.protocol}</td>
                <td className="font-mono">{d.latency_ms}ms</td>
                <td className="font-mono">{d.cpu_pct}%</td>
                <td>
                  <div className="flex gap-3 items-center">
                    <button
                      className="text-nv-muted hover:text-[#16c79a]"
                      onClick={() => setChartDevice(d)}
                      data-testid={`device-chart-${d.id}`}
                      title={t("dev.history")}
                    >
                      <LineIcon size={14} />
                    </button>
                    <button
                      className="text-nv-muted hover:text-[#16c79a]"
                      onClick={() => setIfDevice(d)}
                      data-testid={`device-interfaces-${d.id}`}
                      title={t("dev.interfaces")}
                    >
                      <Network size={14} />
                    </button>
                    <button
                      className="text-nv-muted hover:text-[#16c79a]"
                      onClick={() => { setEditing(d); setModalOpen(true); }}
                      data-testid={`device-edit-${d.id}`}
                      title={t("common.edit")}
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      className="text-nv-muted hover:text-[#e74c3c]"
                      onClick={() => { if (window.confirm(`${d.name} ${t("common.deleteQ")}`)) mDelete.mutate(d.id); }}
                      data-testid={`device-delete-${d.id}`}
                      title={t("common.delete")}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && !isLoading && (
              <tr><td colSpan={10} className="text-center py-10 text-nv-muted font-mono text-[12px]">{t("dev.noDevices")}</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <DeviceModal
        open={modalOpen}
        onClose={() => { setModalOpen(false); setEditing(null); }}
        initial={editing}
        onSubmit={onSubmit}
      />

      {chartDevice && (
        <MetricChartModal device={chartDevice} onClose={() => setChartDevice(null)} />
      )}

      {ifDevice && (
        <InterfaceModal device={ifDevice} onClose={() => setIfDevice(null)} />
      )}
    </div>
  );
}
