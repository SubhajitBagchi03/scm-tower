"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { AppHealth, FileRecord, InventoryAnalysis, InventoryItem } from "@/lib/types";

export default function DashboardPage() {
  const router = useRouter();
  const [health, setHealth]       = useState<AppHealth | null>(null);
  const [inventory, setInventory] = useState<InventoryItem[]>([]);
  const [alerts, setAlerts]       = useState<InventoryAnalysis[]>([]);
  const [files, setFiles]         = useState<FileRecord[]>([]);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [h, inv, a, f] = await Promise.all([
        api.getHealth(),
        api.getInventory(),
        api.getInventoryAlerts(),
        api.listUploadedFiles(),
      ]);
      setHealth(h);
      setInventory(inv);
      setAlerts(a);
      setFiles(f);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const stats = useMemo(() => ({
    inventory: inventory.length,
    red:    alerts.filter((a) => a.status === "Red").length,
    yellow: alerts.filter((a) => a.status === "Yellow").length,
    files:  files.length,
  }), [alerts, files.length, inventory.length]);

  const redAlerts    = alerts.filter((a) => a.status === "Red");
  const yellowAlerts = alerts.filter((a) => a.status === "Yellow");

  function statusColor(s: string) {
    if (s === "Red")    return "var(--red)";
    if (s === "Yellow") return "var(--yellow)";
    return "var(--green)";
  }

  function pillClass(s: string) {
    if (s === "Red")    return "pill pill-danger";
    if (s === "Yellow") return "pill pill-warning";
    return "pill pill-success";
  }

  return (
    <div className="page-wrap">

      {/* Header row */}
      <div className="row">
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: "var(--text)" }}>Operations Dashboard</h1>
          <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 2 }}>
            System overview, active risk signals, and data freshness.
          </p>
        </div>
        <div className="row-wrap">
          <button className="btn btn-ghost btn-sm" type="button" onClick={() => void load()} disabled={loading}>
            {loading ? <><span className="spinner" /> Refreshing</> : "↻ Refresh"}
          </button>
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => router.push("/command-center")}
          >
            ▶ Full Assessment
          </button>
        </div>
      </div>

      {error && <div className="banner banner-danger">{error}</div>}

      {/* Stat cards */}
      <div className="page-grid grid-4">
        <div className="stat-card">
          <div className="stat-label">Inventory Records</div>
          <div className="stat-value">{stats.inventory}</div>
        </div>
        <div className="stat-card stat-border-red">
          <div className="stat-label">Red Alerts</div>
          <div className="stat-value" style={{ color: stats.red > 0 ? "var(--red)" : "var(--text)" }}>
            {stats.red}
          </div>
        </div>
        <div className="stat-card stat-border-yellow">
          <div className="stat-label">Yellow Alerts</div>
          <div className="stat-value" style={{ color: stats.yellow > 0 ? "var(--yellow)" : "var(--text)" }}>
            {stats.yellow}
          </div>
        </div>
        <div className="stat-card stat-border-accent">
          <div className="stat-label">Total Uploads</div>
          <div className="stat-value">{stats.files}</div>
        </div>
      </div>

      {/* Alert chips */}
      {(redAlerts.length > 0 || yellowAlerts.length > 0) && (
        <div className="card" style={{ gap: 12 }}>
          <div className="card-label">Active Alerts — click to analyze</div>
          <div className="alert-chips">
            {redAlerts.map((a) => (
              <button
                key={a.product_id}
                className="alert-chip alert-chip-red"
                type="button"
                onClick={() => router.push("/inventory")}
              >
                {a.product_name}
              </button>
            ))}
            {yellowAlerts.map((a) => (
              <button
                key={a.product_id}
                className="alert-chip alert-chip-yellow"
                type="button"
                onClick={() => router.push("/inventory")}
              >
                {a.product_name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* System health + Critical alerts */}
      <div className="page-grid grid-2">
        <div className="card" style={{ gap: 0 }}>
          <div className="card-label" style={{ marginBottom: 12 }}>System Health</div>
          <div className="kv">
            <span className="kv-label">Status</span>
            <strong className="kv-value" style={{ color: health?.status === "online" ? "var(--green)" : "var(--red)" }}>
              {health?.status ?? "—"}
            </strong>
          </div>
          <div className="kv">
            <span className="kv-label">Service</span>
            <strong className="kv-value">{health?.system ?? "—"}</strong>
          </div>
          <div className="kv">
            <span className="kv-label">Database</span>
            <strong className="kv-value">
              {health == null ? "—" : (
                <span className={health.db_configured ? "pill pill-success" : "pill pill-danger"}>
                  {health.db_configured ? "Configured" : "Missing"}
                </span>
              )}
            </strong>
          </div>
          <div className="kv">
            <span className="kv-label">LLM Key</span>
            <strong className="kv-value">
              {health == null ? "—" : (
                <span className={health.api_key_configured ? "pill pill-success" : "pill pill-danger"}>
                  {health.api_key_configured ? "Configured" : "Missing"}
                </span>
              )}
            </strong>
          </div>
          <div className="kv" style={{ borderBottom: "none" }}>
            <span className="kv-label">Active Agents</span>
            <strong className="kv-value" style={{ fontSize: 11, textAlign: "right" }}>
              {health?.agents_active?.join(", ") ?? "—"}
            </strong>
          </div>
        </div>

        <div className="card" style={{ gap: 0 }}>
          <div className="card-label" style={{ marginBottom: 12 }}>Critical Inventory Alerts</div>
          {alerts.length === 0 ? (
            <div className="empty-state" style={{ padding: 20 }}>
              <div className="empty-state-text">No alerts — all items healthy.</div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
              {alerts.slice(0, 8).map((a) => (
                <div
                  key={`${a.product_id}-${a.status}`}
                  className="row"
                  style={{
                    padding: "9px 0",
                    borderBottom: "1px solid var(--border)",
                    cursor: "pointer",
                  }}
                  onClick={() => router.push("/inventory")}
                >
                  <span style={{ fontSize: 13, color: "var(--text2)" }}>{a.product_name}</span>
                  <span className={pillClass(a.status)}>{a.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Recent uploads */}
      <div className="card" style={{ gap: 12 }}>
        <div className="row">
          <div className="card-label">Recent Uploads</div>
          <button
            className="btn btn-ghost btn-sm"
            type="button"
            onClick={() => router.push("/uploads")}
          >
            View All
          </button>
        </div>
        {files.length === 0 ? (
          <div className="empty-state" style={{ padding: 20 }}>
            <div className="empty-state-text">No uploads yet. <a href="/uploads" style={{ color: "var(--accent)", textDecoration: "none" }}>Upload data →</a></div>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Filename</th>
                  <th>Type</th>
                  <th>Rows</th>
                  <th>Status</th>
                  <th>Uploaded</th>
                </tr>
              </thead>
              <tbody>
                {files.slice(0, 10).map((f) => (
                  <tr key={f.file_id}>
                    <td style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{f.filename}</td>
                    <td><span className="pill pill-muted">{f.file_type}</span></td>
                    <td style={{ fontFamily: "var(--mono)" }}>{f.row_count}</td>
                    <td>
                      <span className={f.status === "confirmed" ? "pill pill-success" : "pill pill-warning"}>
                        {f.status}
                      </span>
                    </td>
                    <td style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--muted)" }}>
                      {f.uploaded_at ? new Date(f.uploaded_at).toLocaleDateString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}