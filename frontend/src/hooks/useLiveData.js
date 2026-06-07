import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
const WS_URL = BACKEND_URL.replace(/^http/, "ws") + "/api/ws";

/**
 * Opens a single WebSocket connection and pushes updates into React Query cache.
 * Auto-reconnects with a small backoff. Returns connection state via a global window flag.
 */
export const useLiveData = () => {
  const qc = useQueryClient();
  useEffect(() => {
    let socket;
    let attempt = 0;
    let retryTimer = null;
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      socket = new WebSocket(WS_URL);
      socket.onopen = () => {
        attempt = 0;
        window.__nvWsOpen = true;
      };
      socket.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg.type !== "tick") return;
          if (msg.summary) qc.setQueryData(["summary"], msg.summary);
          if (msg.devices) {
            qc.setQueryData(["devices"], msg.devices);
            // Topology now comes from /api/topology (it includes LLDP links,
            // unmanaged segments and logical assets that cannot be rebuilt from
            // the device list). The Topology page refreshes it on its own
            // interval, so we intentionally no longer overwrite ["topology"] here.
          }
          if (msg.alerts) qc.setQueryData(["alerts"], msg.alerts);
        } catch {
          /* ignore */
        }
      };
      socket.onclose = () => {
        window.__nvWsOpen = false;
        if (stopped) return;
        attempt += 1;
        const delay = Math.min(1000 * 2 ** Math.min(attempt, 4), 8000);
        retryTimer = setTimeout(connect, delay);
      };
      socket.onerror = () => {
        try { socket.close(); } catch { /* ignore */ }
      };
    };

    connect();
    return () => {
      stopped = true;
      if (retryTimer) clearTimeout(retryTimer);
      try { socket && socket.close(); } catch { /* ignore */ }
    };
  }, [qc]);
};

export default useLiveData;
