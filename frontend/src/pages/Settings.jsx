import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchUsers, createUser, updateUser, deleteUser, fetchAudit } from "@/lib/api";
import { getUser } from "@/lib/auth";
import { UserPlus, Trash2, Shield, ScrollText, Users as UsersIcon } from "lucide-react";
import { toast } from "sonner";

const ROLES = ["viewer", "operator", "admin"];

export default function Settings() {
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
      toast.success("User created");
      setForm({ username: "", password: "", role: "viewer" });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Create failed"),
  });
  const mRole = useMutation({
    mutationFn: ({ username, role }) => updateUser(username, { role }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); toast.success("Role updated"); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Update failed"),
  });
  const mDelete = useMutation({
    mutationFn: (username) => deleteUser(username),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); toast.success("User deleted"); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Delete failed"),
  });

  const usersForbidden = usersQ.isError; // 403 (not admin) or auth off
  const users = usersQ.data || [];
  const audit = auditQ.data || [];

  return (
    <div className="p-6 space-y-5" data-testid="settings-page">
      <div>
        <div className="text-[11px] tracking-[0.2em] text-nv-muted uppercase font-mono">Administration</div>
        <h1 className="text-[22px] font-semibold tracking-tight">Settings</h1>
      </div>

      {!authEnabled && (
        <div className="nv-panel px-4 py-3 text-[12px] text-nv-muted font-mono border-l-2 border-[#f4d03f]">
          인증이 꺼져 있습니다. backend/.env 에서 <span className="text-[#16c79a]">AUTH_ENABLED=true</span> 로 켜면 사용자 관리(RBAC)가 활성화됩니다. (감사 로그는 항상 동작합니다.)
        </div>
      )}

      {/* Users */}
      <div className="nv-panel">
        <div className="px-4 py-2 border-b border-nv-border flex items-center gap-2">
          <UsersIcon size={14} className="text-[#16c79a]" />
          <span className="nv-section-title">Users (RBAC)</span>
        </div>

        {authEnabled && !usersForbidden ? (
          <>
            <div className="px-4 py-3 flex flex-wrap gap-2 items-end border-b border-nv-border">
              <div>
                <div className="nv-label mb-1">Username</div>
                <input className="nv-input" value={form.username}
                  onChange={(e) => setForm({ ...form, username: e.target.value })}
                  data-testid="settings-new-username" />
              </div>
              <div>
                <div className="nv-label mb-1">Password</div>
                <input type="password" className="nv-input" value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  data-testid="settings-new-password" />
              </div>
              <div>
                <div className="nv-label mb-1">Role</div>
                <select className="nv-input" value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value })}
                  data-testid="settings-new-role">
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
              <button className="nv-btn nv-btn-primary" onClick={() => mCreate.mutate()}
                disabled={!form.username || !form.password} data-testid="settings-add-user">
                <UserPlus size={14} /> Add
              </button>
            </div>

            <table className="nv-table" data-testid="settings-users-table">
              <thead>
                <tr><th>Username</th><th style={{ width: 160 }}>Role</th><th style={{ width: 90 }}>Actions</th></tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.username}>
                    <td className="font-mono text-nv-text">
                      {u.username}
                      {me?.username === u.username && <span className="ml-2 text-[10px] text-nv-muted">(you)</span>}
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
                        onClick={() => { if (window.confirm(`Delete user ${u.username}?`)) mDelete.mutate(u.username); }}
                        data-testid={`settings-delete-${u.username}`} title="Delete">
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
                {users.length === 0 && (
                  <tr><td colSpan={3} className="text-center py-6 text-nv-muted font-mono text-[12px]">NO USERS</td></tr>
                )}
              </tbody>
            </table>
          </>
        ) : (
          <div className="px-4 py-5 text-[12px] text-nv-muted font-mono flex items-center gap-2">
            <Shield size={14} />
            {authEnabled ? "관리자(admin) 권한이 필요합니다." : "인증을 켜면 사용자 관리가 표시됩니다."}
          </div>
        )}
      </div>

      {/* Audit log */}
      <div className="nv-panel">
        <div className="px-4 py-2 border-b border-nv-border flex items-center gap-2">
          <ScrollText size={14} className="text-[#16c79a]" />
          <span className="nv-section-title">Audit Log</span>
          <span className="ml-auto text-[10px] text-nv-muted font-mono">{audit.length} entries</span>
        </div>
        <div className="overflow-auto max-h-[420px]">
          <table className="nv-table" data-testid="settings-audit-table">
            <thead>
              <tr>
                <th style={{ width: 160 }}>Time</th>
                <th style={{ width: 120 }}>User</th>
                <th style={{ width: 80 }}>Method</th>
                <th>Path</th>
                <th style={{ width: 70 }}>Status</th>
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
                <tr><td colSpan={5} className="text-center py-6 text-nv-muted font-mono text-[12px]">NO AUDIT ENTRIES</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
