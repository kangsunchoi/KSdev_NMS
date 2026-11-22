import React, { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchDiscovery, updateDiscovery, fetchDiscoveryCandidates, approveDiscoveryCandidate } from "../lib/api";
import { hasRole } from "../lib/auth";
import { useI18n } from "../lib/i18n";
import { Radar, Save, Search } from "lucide-react";
import { toast } from "sonner";

const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
const INPUT = "nv-input w-full px-3 py-2 text-[13px] rounded-sm";

export default function Discovery() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const candidates = useQuery({
    queryKey: ["discovery-candidates"],
    queryFn: fetchDiscoveryCandidates,
    refetchInterval: 5000,
  });
  const [approving, setApproving] = useState(null);
  const approve = async (id) => {
    setApproving(id);
    try {
      await approveDiscoveryCandidate(id);
      await Promise.all([
        candidates.refetch(),
        queryClient.invalidateQueries({ queryKey: ["devices"] }),
      ]);
      toast.success(t("disc.approved"));
    } catch {
      toast.error(t("disc.approveFail"));
    } finally {
      setApproving(null);
    }
  };
  const { data, refetch } = useQuery({
    queryKey: ["discovery"],
    queryFn: fetchDiscovery,
    refetchInterval: 5000,
  });

  const [form, setForm] = useState({
    subnet: "", community: "public", snmp_version: "2c", default_type: "switch",
  });
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (data && !loaded) {
      setForm({
        subnet: data.subnet || "",
        community: data.community || "public",
        snmp_version: data.snmp_version || "2c",
        default_type: data.default_type || "switch",
      });
      setLoaded(true);
    }
  }, [data, loaded]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const handleSave = async () => {
    try {
      await updateDiscovery(form);
      toast.success(t("disc.saved"));
      refetch();
    } catch (e) {
      toast.error(t("disc.saveFail"));
    }
  };

  const handleScan = async () => {
    if (!form.subnet.trim()) {
      toast.error(t("disc.subnetRequired"));
      return;
    }
    try {
      await updateDiscovery({ ...form, run_requested: true });
      toast.success(t("disc.scanRequested"));
      refetch();
    } catch (e) {
      toast.error(t("disc.scanFail"));
    }
  };

  const pending = data?.run_requested;

  return (
    <div className="p-6" data-testid="discovery-page">
      <div className="flex items-center justify-between mb-5">
        <div>
          <div className="text-[11px] tracking-[0.2em] text-nv-muted uppercase font-mono">{t("disc.network")}</div>
          <h1 className="text-[22px] font-semibold tracking-tight flex items-center gap-2">
            <Radar size={20} /> {t("nav.discovery")}
          </h1>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Settings */}
        <div className="nv-panel p-4">
          <div className="nv-section-title mb-3">{t("disc.scanSettings")}</div>

          <div className="nv-label mb-1">{t("disc.subnetLabel")}</div>
          <input
            className={`${INPUT} mb-3`}
            data-testid="discovery-subnet"
            placeholder="192.168.1.0/24"
            value={form.subnet}
            onChange={(e) => set("subnet", e.target.value)}
          />

          <div className="nv-label mb-1">{t("disc.community")}</div>
          <input
            className={`${INPUT} mb-3`}
            data-testid="discovery-community"
            placeholder="public"
            value={form.community}
            onChange={(e) => set("community", e.target.value)}
          />

          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="nv-label mb-1">{t("disc.version")}</div>
              <select
                className={INPUT}
                data-testid="discovery-version"
                value={form.snmp_version}
                onChange={(e) => set("snmp_version", e.target.value)}
              >
                <option value="1">v1</option>
                <option value="2c">v2c</option>
                <option value="3">v3</option>
              </select>
            </div>
            <div>
              <div className="nv-label mb-1">{t("disc.defaultType")}</div>
              <select
                className={INPUT}
                data-testid="discovery-type"
                value={form.default_type}
                onChange={(e) => set("default_type", e.target.value)}
              >
                <option value="switch">switch</option>
                <option value="plc">plc</option>
                <option value="hmi">hmi</option>
                <option value="sensor">sensor</option>
              </select>
            </div>
          </div>

          <div className="flex items-center gap-2 mt-4">
            <button className="nv-btn" onClick={handleSave} data-testid="discovery-save-btn">
              <Save size={14} /> {t("disc.save")}
            </button>
            <button className="nv-btn nv-btn-primary" onClick={handleScan} data-testid="discovery-scan-btn">
              <Search size={14} /> {t("disc.scanNow")}
            </button>
          </div>
        </div>

        {/* Status */}
        <div className="nv-panel p-4">
          <div className="nv-section-title mb-3">{t("disc.lastScan")}</div>
          <dl className="space-y-2 font-mono text-[13px]">
            <div className="flex justify-between">
              <dt className="text-nv-muted">{t("disc.status")}</dt>
              <dd className={pending ? "text-nv-accent" : "text-nv-text"}>
                {pending ? t("disc.pending") : t("disc.idle")}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-nv-muted">{t("disc.lastRun")}</dt>
              <dd className="text-nv-text">{fmt(data?.last_run)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-nv-muted">{t("disc.found")}</dt>
              <dd className="text-nv-text">{data?.last_found ?? 0}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-nv-muted">{t("disc.created")}</dt>
              <dd className="text-nv-text">{data?.last_queued ?? 0}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-nv-muted">{t("disc.message")}</dt>
              <dd className="text-nv-text">{data?.last_message || "—"}</dd>
            </div>
          </dl>
          <p className="text-[11px] text-nv-muted mt-4 leading-relaxed">
            {t("disc.note")}
          </p>
        </div>
      </div>
      <section className="nv-panel p-4 mt-4">
        <h2 className="nv-section-title mb-3">{t("disc.candidates")}</h2>
        {candidates.isError ? <p role="alert">{t("disc.loadFail")}</p> :
          candidates.isLoading ? <p>{t("disc.loading")}</p> :
          !candidates.data?.length ? <p>{t("disc.empty")}</p> :
          <ul>
            {candidates.data.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center gap-4 border-t py-2">
                <span>{t("disc.site")} {row.site_id}</span>
                <strong className="font-mono">{row.ip}</strong>
                <time dateTime={row.observed_at}>{fmt(row.observed_at)}</time>
                {hasRole("operator") && <button className="nv-btn ml-auto" disabled={approving !== null}
                  onClick={() => approve(row.id)}>{t("disc.approve")}</button>}
              </li>
            ))}
          </ul>}
      </section>
    </div>
  );
}
