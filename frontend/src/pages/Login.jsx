import React, { useState } from "react";
import { login, setSession } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { Activity, Lock } from "lucide-react";

export const Login = ({ onSuccess }) => {
  const { t } = useI18n();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!username || !password || busy) return;
    setBusy(true);
    setError("");
    try {
      const res = await login(username, password);
      setSession(res.token, { username: res.username, role: res.role });
      onSuccess && onSuccess();
    } catch (e) {
      setError(e?.response?.data?.detail || t("login.failed"));
      setBusy(false);
    }
  };

  const onKey = (e) => { if (e.key === "Enter") submit(); };

  return (
    <div className="min-h-screen bg-nv-bg text-nv-text flex items-center justify-center p-4">
      <div className="nv-panel w-[380px] max-w-full" data-testid="login-panel">
        <div className="px-5 py-4 border-b border-nv-border flex items-center gap-2">
          <div className="w-7 h-7 flex items-center justify-center bg-[#16c79a] text-[#0b1220] rounded-sm">
            <Activity size={16} strokeWidth={2.5} />
          </div>
          <div className="leading-tight">
            <div className="text-[14px] font-semibold tracking-wide text-white">NetVision</div>
            <div className="text-[10px] font-mono tracking-[0.18em] text-nv-muted">{t("brand.tagline")}</div>
          </div>
        </div>

        <div className="px-5 py-5 space-y-3">
          <div className="flex items-center gap-2 text-nv-muted text-[12px] font-mono mb-1">
            <Lock size={13} /> {t("login.subtitle")}
          </div>

          <div>
            <div className="nv-label mb-1">{t("login.username")}</div>
            <input className="nv-input w-full" value={username}
              onChange={(e) => setUsername(e.target.value)} onKeyDown={onKey} autoFocus
              data-testid="login-username" />
          </div>

          <div>
            <div className="nv-label mb-1">{t("login.password")}</div>
            <input type="password" className="nv-input w-full" value={password}
              onChange={(e) => setPassword(e.target.value)} onKeyDown={onKey}
              data-testid="login-password" />
          </div>

          {error ? (
            <div className="text-[12px] text-[#e74c3c] font-mono" data-testid="login-error">{error}</div>
          ) : null}

          <button className="nv-btn nv-btn-primary w-full mt-1" onClick={submit}
            disabled={busy || !username || !password} data-testid="login-submit">
            {busy ? t("login.signingIn") : t("login.signIn")}
          </button>
        </div>
      </div>
    </div>
  );
};

export default Login;
