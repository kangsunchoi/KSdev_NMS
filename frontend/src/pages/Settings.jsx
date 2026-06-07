import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchUsers, createUser, updateUser, deleteUser, fetchAudit } from "@/lib/api";
import { getUser } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { UserPlus, Trash2, Shield, ScrollText, Users as UsersIcon } from "lucide-react";
import { toast } from "sonner";

const ROLES = ["viewer", "operator", "admin"];

export default function Settings() {
  const { t } = useI18n();
  const authEnabled = !!window.__nvAuthEnabled;
  const me = getUser();
  const qc = useQueryClient();

  const usersQ = useQuery({
    queryKey: ["users"],
    queryFn: fetchUsers,
    enabled: authEnabled,
    retry: false,
  });
  const auditQ = useQuery({
    queryKey: ["audit"],
    queryFn: () => fetchAudit(200),
    refetchInterval: 15000,
  });

  const [form, setForm] = useState({ username: "", password: "", role: "viewer" });

  const mCreate = useMutation({
    mutationFn: () => createUser(form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success(t("set.userCreated"));
      setForm({ username: "", password: "", role: "viewer" });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || t("set.createFail")),
  });
  const mRole = useMutation({
    mutationFn: ({ username, role }) => updateUser(username, { role }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); toast.success(t("set.roleUpdated")); },
    onError: (e) => toast.error(e?.response?.data?.detail || t("set.updateFail")),
  });
  const mDelete = useMutation({
    mutationFn: (username) => deleteUser(username),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); toast.success(t("set.userDeleted")); },
    onError: (e) => toast.error(e?.response?.data?.detail || t("set.deleteFail")),
  });

  const usersForbidden = usersQ.isError;
  const users = usersQ.data || [];
  const audit = auditQ.data || [];

  return (
    <div className="p-6 space-y-5" data-testid="settings-page">
      <div>
        <div className="text-[11px] tracking-[0.2em] text-nv-muted uppercase font-mono">{t("set.administration")}</div>
        <h1 className="text-[22px] font-semibold tracking-tight">{t("nav.settings")}</h1>
      </div>

      {!authEnabled && (
        <div className="nv-panel px-4 py-3 text-[12px] text-nv-muted font-mono border-l-2 border-[#f4d03f]">
          {t("set.authOffPre")}<span className="text-[#16c79a]">AUTH_ENABLED=true</span>{t("set.authOffPost")}
        </div>
      )}

      {/* Users */}
      <div className="nv-panel">
        <div className="px-4 py-2 border-b border-nv-border flex items-center gap-2">
          <UsersIcon size={14} className="text-[#16c79a]" />
          <span className="nv-section-title">{t("set.usersRbac")}</span>
        </div>

        {authEnabled && !usersForbidden ? (
          <>
            <div className="px-4 py-3 flex flex-wrap gap-2 items-end border-b border-nv-border">
              <div>
                <div className="nv-label mb-1">{t("login.username")}</div>
                <input className="nv-input" value={form.username}
                  onChange={(e) => setForm({ ...form, username: e.target.value })}
                  data-testid="settings-new-username" />
              </div>
              <div>
                <div className="nv-label mb-1">{t("login.password")}</div>
                <input type="password" className="nv-input" value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  data-testid="settings-new-password" />
              </div>
              <div>
                <div className="nv-label mb-1">{t("set.role")}</div>
                <select className="nv-input" value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value })}
                  data-testid="settings-new-role">
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
              <button className="nv-btn nv-btn-primary" onClick={() => mCreate.mutate()}
                disabled={!form.username || !form.password} data-testid="settings-add-user">
                <UserPlus size={14} /> {t("set.add")}
              </button>
            </div>

            <table className="nv-table" data-testid="settings-users-table">
              <thead>
                <tr><th>{t("login.username")}</th><th style={{ width: 160 }}>{t("set.role")}</th><th style={{ width: 90 }}>{t("al.colActions")}</th></tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.username}>
                    <td className="font-mono text-nv-text">
                      {u.username}
                      {me?.username === u.username && <span className="ml-2 text-[10px] text-nv-muted">{t("set.you")}</span>}
                    </td>
                    <td>
                      <select className="nv-input py-1" value={u.role}
                        onChange={(e) => mRole.mutate({ username: u.username, role: e.target.value })}
                        data-testid={`settings-role-${u.username}`}>
                        {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                      </select>
                    </td>
                    <td>
                      <button className="text-nv-muted hover:text-[#e74c3c] px-1"
                        onClick={() => { if (window.confirm(t("set.confirmDelete").replace("{user}", u.username))) mDelete.mutate(u.username); }}
                        data-testid={`settings-delete-${u.username}`} title={t("common.delete")}>
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
                {users.length === 0 && (
                  <tr><td colSpan={3} className="text-center py-6 text-nv-muted font-mono text-[12px]">{t("set.noUsers")}</td></tr>
                )}
              </tbody>
            </table>
          </>
        ) : (
          <div className="px-4 py-5 text-[12px] text-nv-muted font-mono flex items-center gap-2">
            <Shield size={14} />
            {authEnabled ? t("set.adminRequired") : t("set.authOffUsers")}
          </div>
        )}
      </div>

      {/* Audit log */}
      <div className="nv-panel">
        <div className="px-4 py-2 border-b border-nv-border flex items-center gap-2">
          <ScrollText size={14} className="text-[#16c79a]" />
          <span className="nv-section-title">{t("set.auditLog")}</span>
          <span className="ml-auto text-[10px] text-nv-muted font-mono">{audit.length} {t("set.entries")}</span>
        </div>
        <div className="overflow-auto max-h-[420px]">
          <table className="nv-table" data-testid="settings-audit-table">
            <thead>
              <tr>
                <th style={{ width: 160 }}>{t("set.colTime")}</th>
                <th style={{ width: 120 }}>{t("set.colUser")}</th>
                <th style={{ width: 80 }}>{t("set.colMethod")}</th>
                <th>{t("set.colPath")}</th>
                <th style={{ width: 70 }}>{t("set.colStatus")}</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((r) => (
                <tr key={r.id}>
                  <td className="font-mono text-[11px] text-nv-muted">{new Date(r.ts).toLocaleString()}</td>
                  <td className="font-mono text-[12px] text-nv-text">{r.username} <span className="text-nv-muted">/{r.role}</span></td>
                  <td className="font-mono text-[11px]">{r.method}</td>
                  <td className="font-mono text-[11px] text-nv-text">{r.path}</td>
                  <td className="font-mono text-[11px] text-[#16c79a]">{r.status}</td>
                </tr>
              ))}
              {audit.length === 0 && (
                <tr><td colSpan={5} className="text-center py-6 text-nv-muted font-mono text-[12px]">{t("set.noAudit")}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
