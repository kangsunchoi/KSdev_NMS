# NetVision OT — PRD

## Problem Statement
Build an industrial network monitoring dashboard called "NetVision OT" for factory engineers.
Tech: React frontend (JSX per platform rules), FastAPI Python backend, MongoDB, Cytoscape.js for network graphs, Tailwind CSS with dark industrial theme (background #1a1a2e, accent #16c79a).

## User Persona
Factory/OT engineer in a control room monitoring switches, PLCs, HMIs, and sensors on an industrial network. Needs at-a-glance device status, alert response, and topology visibility. Single-user, no login.

## Core Requirements (static)
1. Device inventory CRUD (switch, PLC, HMI, sensor) with fields: name, IP, vendor, model, protocol.
2. Dashboard: KPI cards (total devices, online count, critical alerts), alert feed, network health score.
3. Topology viewer: Cytoscape graph (switch=rectangle blue, PLC=hexagon green, end device=circle gray), click for side panel.
4. Alerts page: severity-colored table with acknowledge button.
5. Mock data generator: 20 realistic industrial devices with simulated metrics.
6. No login.

## User Choices
- Auto-seed on startup AND manual "Generate Mock Data" button.
- Live metrics simulated, auto-refresh every few seconds.
- Topology auto-generated as realistic hierarchy (switch → PLC/HMI → sensors).
- Alerts auto-generated based on simulated device states.
- Strict design: bg #1a1a2e, accent #16c79a, surface #16213e, border #2a3b55. Inter UI + JetBrains Mono data. Sharp corners (2-4px). LED dot status indicators. Dotted topology grid. Compact 40px table rows.

## Implemented (2026-02)
- FastAPI backend with MongoDB models: Device, Alert.
- Endpoints: /api/devices CRUD, /api/alerts (list/ack/delete), /api/topology, /api/dashboard/summary, /api/mock/generate, /api/mock/reset.
- Background simulation loop jiggles metrics every 5s, derives status, raises auto-alerts.
- React frontend: Sidebar (collapsible) + 4 pages — Dashboard, Devices, Topology, Alerts.
- Cytoscape topology with breadth-first hierarchy layout, status-colored borders, side panel on node click.
- Tailwind theme with custom nv palette + LED dot CSS, compact tables, dotted grid background.

## Implemented (2026-02 iteration 2)
- **Metric history**: device_metrics MongoDB collection w/ TTL index (24h), sampled every 60s. GET /api/devices/{id}/metrics?hours=N returns sorted points.
- **Metric chart modal**: recharts LineChart with range (1H/6H/12H/24H) + metric (latency/pkt loss/CPU) selectors + Brush zoom. Opens from Devices table chart icon.
- **Bulk acknowledge**: POST /api/alerts/bulk-acknowledge {ids?} — empty/null payload acks all open. Per-row checkboxes + select-all on Alerts page.
- **Text search**: client-side filter on Devices (name/IP/vendor/model/protocol) and Alerts (device/message/severity).
- **WebSocket push**: /api/ws broadcasts {summary, devices, alerts} every 5s. useLiveData hook drives React Query cache; refetchInterval removed from all main queries.
- **CSV export**: client-side CSV builder (`/lib/csv.js`), Export buttons on Devices and Alerts pages.

## Backlog
- P1: Per-device historical metric chart (recharts) on click.
- P1: Bulk acknowledge alerts.
- P1: Search/filter on devices table (text search beyond type chips).
- P2: WebSocket push for true real-time vs. polling.
- P2: Custom topology connection editor.
- P2: CSV export of devices/alerts.
- P2: Group devices by zone/cell.
