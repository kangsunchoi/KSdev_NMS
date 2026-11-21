import React, { useEffect, useState } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import Devices from "@/pages/Devices";
import Discovery from "@/pages/Discovery";
import Topology from "@/pages/Topology";
import Alerts from "@/pages/Alerts";
import Settings from "@/pages/Settings";
import Login from "@/pages/Login";
import { fetchAuthConfig, fetchMe, getToken, setSession } from "@/lib/auth";
import { I18nProvider } from "@/lib/i18n";

function AppShell() {
  return (
    <div className="App">
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/discovery" element={<Discovery />} />
            <Route path="/devices" element={<Devices />} />
            <Route path="/topology" element={<Topology />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </div>
  );
}

function App() {
  const [ready, setReady] = useState(false);
  const [configError, setConfigError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [authEnabled, setAuthEnabled] = useState(false);
  const [authed, setAuthed] = useState(!!getToken());

  useEffect(() => {
    let alive = true;
    setReady(false);
    setConfigError(false);
    fetchAuthConfig()
      .then(async (cfg) => {
        if (!alive) return;
        const on = !!cfg.auth_enabled;
        setAuthEnabled(on);
        window.__nvAuthEnabled = on;
        // Refresh the cached role so a role changed by an admin takes effect
        // (a 401 here drops the session via the api.js interceptor).
        if (on && getToken()) {
          try {
            const me = await fetchMe();
            if (alive) setSession(null, { username: me.username, role: me.role });
          } catch {
            /* 401 handled by interceptor; network errors keep the cached user */
          }
        }
        if (alive) setReady(true);
      })
      .catch(() => {
        // Issue #8: never fall back to "auth off" — that would show the app
        // without a login when the backend is merely unreachable.
        if (!alive) return;
        window.__nvAuthEnabled = true;
        setConfigError(true);
      });

    const onUnauth = () => setAuthed(false);
    window.addEventListener("nv-unauthorized", onUnauth);
    return () => {
      alive = false;
      window.removeEventListener("nv-unauthorized", onUnauth);
    };
  }, [attempt]);

  useEffect(() => {
    if (!configError) return undefined;
    const id = setTimeout(() => setAttempt((n) => n + 1), 10000); // auto-retry
    return () => clearTimeout(id);
  }, [configError]);

  let content;
  if (configError) {
    content = (
      <div className="min-h-screen bg-nv-bg text-nv-muted flex flex-col items-center justify-center gap-3 font-mono text-[12px]"
        role="alert" data-testid="auth-config-error">
        <div>Cannot reach the NetVision server. Retrying every 10 seconds.</div>
        <button className="nv-btn" onClick={() => setAttempt((n) => n + 1)} data-testid="auth-config-retry">
          Retry now
        </button>
      </div>
    );
  } else if (!ready) {
    content = (
      <div className="min-h-screen bg-nv-bg text-nv-muted flex items-center justify-center font-mono text-[12px]">
        Loading…
      </div>
    );
  } else if (authEnabled && !authed) {
    content = <Login onSuccess={() => setAuthed(true)} />;
  } else {
    content = <AppShell />;
  }

  return <I18nProvider>{content}</I18nProvider>;
}

export default App;
