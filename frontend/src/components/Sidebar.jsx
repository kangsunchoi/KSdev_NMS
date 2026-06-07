import React, { useState } from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Server,
  Network,
  AlertTriangle,
  Radar,
  ChevronLeft,
  ChevronRight,
  Activity,
  LogOut,
  Settings as SettingsIcon,
} from "lucide-react";
import { getUser, clearSession } from "../lib/auth";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/discovery", label: "Discovery", icon: Radar, testId: "nav-discovery" },
  { to: "/devices", label: "Devices", icon: Server, testId: "nav-devices" },
  { to: "/topology", label: "Topology", icon: Network, testId: "nav-topology" },
  { to: "/alerts", label: "Alerts", icon: AlertTriangle, testId: "nav-alerts" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, testId: "nav-settings" },
];

export const Sidebar = () => {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <aside
      className={`fixed top-0 left-0 h-full border-r border-nv-border bg-[#131a30] flex flex-col transition-[width] duration-150 ${
        collapsed ? "w-[64px]" : "w-[220px]"
      }`}
      data-testid="sidebar"
    >
      {/* Brand */}
      <div className="flex items-center gap-2 px-4 h-[56px] border-b border-nv-border">
        <div className="w-7 h-7 flex items-center justify-center bg-[#16c79a] text-[#0b1220] rounded-sm">
          <Activity size={16} strokeWidth={2.5} />
        </div>
        {!collapsed && (
          <div className="leading-tight">
            <div className="text-[13px] font-semibold tracking-wide text-white">NetVision</div>
            <div className="text-[10px] font-mono tracking-[0.18em] text-nv-muted">OT MONITOR</div>
          </div>
        )}
      </div>

      <nav className="flex-1 py-2">
        {NAV.map(({ to, label, icon: Icon, testId }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            data-testid={testId}
            className={({ isActive }) => `nv-nav-item ${isActive ? "active" : ""}`}
          >
            <Icon size={18} strokeWidth={1.6} />
            {!collapsed && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      {window.__nvAuthEnabled && getUser() && (
        <div className="border-t border-nv-border px-3 py-2" data-testid="sidebar-user">
          {!collapsed && (
            <div className="mb-1.5 leading-tight">
              <div className="text-[12px] text-nv-text font-mono truncate">{getUser().username}</div>
              <div className="text-[10px] text-nv-muted uppercase tracking-wider">{getUser().role}</div>
            </div>
          )}
          <button
            type="button"
            onClick={() => { clearSession(); window.location.reload(); }}
            className="flex items-center gap-2 text-nv-muted hover:text-[#e74c3c] transition-colors text-[12px]"
            data-testid="logout-btn"
            title="Sign out"
          >
            <LogOut size={16} />
            {!collapsed && <span>Sign out</span>}
          </button>
        </div>
      )}

      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex items-center justify-center h-10 border-t border-nv-border text-nv-muted hover:text-[#16c79a] transition-colors"
        data-testid="sidebar-toggle-btn"
      >
        {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        {!collapsed && <span className="ml-2 text-[11px] uppercase tracking-wider">Collapse</span>}
      </button>
    </aside>
  );
};

export default Sidebar;
