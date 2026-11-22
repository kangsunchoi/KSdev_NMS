import React from "react";
import Sidebar from "./Sidebar";
import { Toaster } from "sonner";
import useLiveData from "../hooks/useLiveData";

export const Layout = ({ children }) => {
  useLiveData();
  return (
    <div className="nv-shell flex min-h-screen bg-nv-bg text-nv-text">
      <Sidebar />
      <main className="nv-main min-w-0 flex-1 min-h-screen" data-testid="app-main">
        {children}
      </main>
      <Toaster
        position="bottom-right"
        theme="light"
        toastOptions={{
          style: {
            background: "#ffffff",
            border: "1px solid #d3d8dd",
            color: "#181c20",
            borderRadius: "3px",
            fontFamily: "Inter, sans-serif",
          },
        }}
      />
    </div>
  );
};

export default Layout;
