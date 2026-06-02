import React from "react";
import Sidebar from "./Sidebar";
import { Toaster } from "sonner";
import useLiveData from "../hooks/useLiveData";

export const Layout = ({ children }) => {
  useLiveData();
  return (
    <div className="min-h-screen bg-nv-bg text-nv-text">
      <Sidebar />
      <main className="ml-[220px] min-h-screen" data-testid="app-main">
        {children}
      </main>
      <Toaster
        position="bottom-right"
        theme="dark"
        toastOptions={{
          style: {
            background: "#16213e",
            border: "1px solid #2a3b55",
            color: "#f8f9fa",
            borderRadius: "3px",
            fontFamily: "Inter, sans-serif",
          },
        }}
      />
    </div>
  );
};

export default Layout;
