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
import { fetchAuthConfig, getToken } from "@/lib/auth";
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
  const [authEnabled, setAuthEnabled] = useState(false);
  const [authed, setAuthed] = useState(!!getToken());

  useEffect(() => {
    let alive = true;
    fetchAuthConfig()
      .then((cfg) => {
        if (!alive) return;
        const on = !!cfg.auth_enabled;
        setAuthEnabled(on);
        window.__nvAuthEnabled = on;
      })
      .catch(() => {
        // Older backend / unreachable: behave exactly as before (no auth gate).
        if (!alive) return;
        setAuthEnabled(false);
        window.__nvAuthEnabled = false;
      })
      .finally(() => {
        if (alive) setReady(true);
      });

    const onUnauth = () => setAuthed(false);
    window.addEventListener("nv-unauthorized", onUnauth);
    return () => {
      alive = false;
      window.removeEventListener("nv-unauthorized", onUnauth);
    };
  }, []);

  let content;
  if (!ready) {
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
