import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import Devices from "@/pages/Devices";
import Discovery from "@/pages/Discovery";
import Topology from "@/pages/Topology";
import Alerts from "@/pages/Alerts";

function App() {
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
          </Routes>
        </Layout>
      </BrowserRouter>
    </div>
  );
}

export default App;
