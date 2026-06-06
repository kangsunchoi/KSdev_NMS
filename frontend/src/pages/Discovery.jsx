import React, { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchDiscovery, updateDiscovery } from "../lib/api";
import { Radar, Save, Search } from "lucide-react";
import { toast } from "sonner";

const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
const INPUT = "nv-input w-full px-3 py-2 text-[13px] rounded-sm";

export default function Discovery() {
  const { data, refetch } = useQuery({
    queryKey: ["discovery"],
    queryFn: fetchDiscovery,
    refetchInterval: 5000,
  });

  const [form, setForm] = useState({
    subnet: "", community: "public", snmp_version: "2c", default_type: "switch",
  });
  const [loaded, setLoaded] = useState(false);

  // Initialize the form once from the server, then let the user edit freely.
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
      toast.success("설정을 저장했습니다");
      refetch();
    } catch (e) {
      toast.error("저장 실패");
    }
  };

  const handleScan = async () => {
    if (!form.subnet.trim()) {
      toast.error("IP 대역을 입력하세요");
      return;
    }
    try {
      await updateDiscovery({ ...form, run_requested: true });
      toast.success("스캔을 요청했습니다 — 최대 1분 내 실행됩니다");
      refetch();
    } catch (e) {
      toast.error("스캔 요청 실패");
    }
  };

  const pending = data?.run_requested;

  return (
    <div className="p-6" data-testid="discovery-page">
      <div className="flex items-center justify-between mb-5">
        <div>
          <div className="text-[11px] tracking-[0.2em] text-nv-muted uppercase font-mono">Network</div>
          <h1 className="text-[22px] font-semibold tracking-tight flex items-center gap-2">
            <Radar size={20} /> Discovery
          </h1>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Settings */}
        <div className="nv-panel p-4">
          <div className="nv-section-title mb-3">Scan Settings</div>

          <div className="nv-label mb-1">IP 대역 (CIDR 또는 범위)</div>
          <input
            className={`${INPUT} mb-3`}
            data-testid="discovery-subnet"
            placeholder="192.168.1.0/24"
            value={form.subnet}
            onChange={(e) => set("subnet", e.target.value)}
          />

          <div className="nv-label mb-1">SNMP Community</div>
          <input
            className={`${INPUT} mb-3`}
            data-testid="discovery-community"
            placeholder="public"
            value={form.community}
            onChange={(e) => set("community", e.target.value)}
          />

          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="nv-label mb-1">SNMP Version</div>
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
              <div className="nv-label mb-1">기본 장비 타입</div>
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
              <Save size={14} /> 설정 저장
            </button>
            <button className="nv-btn nv-btn-primary" onClick={handleScan} data-testid="discovery-scan-btn">
              <Search size={14} /> 지금 스캔
            </button>
          </div>
        </div>

        {/* Status */}
        <div className="nv-panel p-4">
          <div className="nv-section-title mb-3">Last Scan</div>
          <dl className="space-y-2 font-mono text-[13px]">
            <div className="flex justify-between">
              <dt className="text-nv-muted">상태</dt>
              <dd className={pending ? "text-nv-accent" : "text-nv-text"}>
                {pending ? "스캔 대기 중…" : "대기"}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-nv-muted">마지막 실행</dt>
              <dd className="text-nv-text">{fmt(data?.last_run)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-nv-muted">발견(alive)</dt>
              <dd className="text-nv-text">{data?.last_found ?? 0}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-nv-muted">신규 등록</dt>
              <dd className="text-nv-text">{data?.last_created ?? 0}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-nv-muted">메시지</dt>
              <dd className="text-nv-text">{data?.last_message || "—"}</dd>
            </div>
          </dl>
          <p className="text-[11px] text-nv-muted mt-4 leading-relaxed">
            "지금 스캔"을 누르면 Node-RED 수집기가 다음 폴링(최대 1분) 때 이 대역을
            fping으로 스윕해 살아있는 장비를 자동 등록합니다. 결과는 Devices 화면에서 확인하세요.
          </p>
        </div>
      </div>
    </div>
  );
}
