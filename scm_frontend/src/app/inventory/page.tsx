"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { InventoryAnalysis, InventoryItem } from "@/lib/types";
import { statusClass, stockColorClass } from "@/lib/ui";

export default function InventoryPage() {
  const [items, setItems]           = useState<InventoryItem[]>([]);
  const [alerts, setAlerts]         = useState<InventoryAnalysis[]>([]);
  const [selectedProduct, setSelectedProduct] = useState("");
  const [analysis, setAnalysis]     = useState<InventoryAnalysis | null>(null);
  const [loading, setLoading]       = useState(false);
  const [analyzing, setAnalyzing]   = useState(false);
  const [error, setError]           = useState("");
  const [search, setSearch]         = useState("");

  const loadInventory = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [list, a] = await Promise.all([api.getInventory(), api.getInventoryAlerts()]);
      setItems(list);
      setAlerts(a);
      if (!selectedProduct && list.length > 0) setSelectedProduct(list[0].product_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load inventory");
    } finally {
      setLoading(false);
    }
  }, [selectedProduct]);

  useEffect(() => { void loadInventory(); }, [loadInventory]);

  async function runAnalysis(productId?: string) {
    const id = productId ?? selectedProduct;
    if (!id) return;
    setAnalyzing(true);
    setError("");
    if (productId) setSelectedProduct(productId);
    try {
      const result = await api.analyzeInventoryItem(id);
      setAnalysis(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  }

  const filtered = items.filter((i) =>
    i.product_name.toLowerCase().includes(search.toLowerCase()) ||
    i.product_id.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="page-wrap">
      {error && <div className="banner banner-danger">{error}</div>}
      {(loading || analyzing) && (
        <div className="banner">
          <span className="spinner" style={{ display: "inline-block", marginRight: 8 }} />
          {analyzing ? "Running analysis..." : "Loading inventory..."}
        </div>
      )}

      {/* Alert chips */}
      {alerts.length > 0 && (
        <div className="card" style={{ gap: 10 }}>
          <div className="card-label">Active Alerts — click to analyze</div>
          <div className="alert-chips">
            {alerts.map((a) => (
              <button
                key={a.product_id}
                type="button"
                className={`alert-chip ${a.status === "Red" ? "alert-chip-red" : "alert-chip-yellow"}`}
                onClick={() => void runAnalysis(a.product_id)}
              >
                {a.product_name}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="page-grid grid-2" style={{ alignItems: "start" }}>

        {/* Analysis panel */}
        <div className="card" style={{ gap: 14 }}>
          <div className="card-label">Run Product Analysis</div>

          <div className="stack" style={{ gap: 10 }}>
            <select
              value={selectedProduct}
              onChange={(e) => setSelectedProduct(e.target.value)}
            >
              <option value="">Select product</option>
              {items.map((i, idx) => (
                <option value={i.product_id} key={`${i.product_id}-${idx}`}>
                  {i.product_id} — {i.product_name}
                </option>
              ))}
            </select>

            <div className="row-wrap">
              <button
                className="btn btn-primary"
                type="button"
                onClick={() => void runAnalysis()}
                disabled={!selectedProduct || analyzing}
              >
                {analyzing ? <><span className="spinner" /> Analyzing...</> : "Analyze SKU"}
              </button>
              <button
                className="btn btn-ghost"
                type="button"
                onClick={() => void loadInventory()}
                disabled={loading}
              >
                ↻ Reload
              </button>
            </div>
          </div>

          {analysis && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
              <div className="row">
                <strong style={{ color: "var(--text)", fontSize: 15 }}>{analysis.product_name}</strong>
                <span className={statusClass(analysis.status)}>{analysis.status}</span>
              </div>

              {/* KPI grid */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {[
                  ["Days Until Stockout", analysis.days_until_stockout],
                  ["EOQ (units)", analysis.eoq],
                  ["Safety Stock", analysis.safety_stock],
                  ["Reorder Point", analysis.reorder_point?.toFixed(0)],
                  ["Est. Order Cost", `$${analysis.estimated_cost}`],
                  ["Lead Time", `${analysis.used_lead_time_days}d`],
                ].map(([label, value]) => (
                  <div key={String(label)} className="kpi-card kpi-ok">
                    <div className="kpi-label">{String(label)}</div>
                    <div style={{ fontSize: 20, fontWeight: 700, color: "var(--text)" }}>{String(value)}</div>
                  </div>
                ))}
              </div>

              {/* Reasoning */}
              {analysis.recommended_action && (
                <div style={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8, padding: 14 }}>
                  <div className="card-label" style={{ marginBottom: 8 }}>Recommendation</div>
                  <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text)", marginBottom: 8 }}>
                    {analysis.recommended_action}
                  </p>
                  {analysis.reasoning && (
                    <p style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.7 }}>
                      {analysis.reasoning}
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Snapshot table */}
        <div className="card" style={{ gap: 12 }}>
          <div className="row">
            <div className="card-label">Inventory Snapshot</div>
            <input
              placeholder="Search products..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ width: 200 }}
            />
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Stock</th>
                  <th>Threshold</th>
                  <th>Warehouse</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((i, idx) => (
                  <tr
                    key={`${i.product_id}-${idx}`}
                    onClick={() => void runAnalysis(i.product_id)}
                    style={{ cursor: "pointer" }}
                  >
                    <td style={{ color: "var(--text)", fontWeight: 500 }}>{i.product_name}</td>
                    <td>
                      <span
                        className={stockColorClass(i.quantity_in_stock, i.reorder_threshold)}
                        style={{ fontWeight: 700, fontFamily: "var(--mono)" }}
                      >
                        {i.quantity_in_stock}
                      </span>
                    </td>
                    <td style={{ fontFamily: "var(--mono)", color: "var(--muted)" }}>{i.reorder_threshold}</td>
                    <td style={{ color: "var(--muted)", fontSize: 12 }}>{i.warehouse ?? "—"}</td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={4}>
                      <div className="empty-state" style={{ padding: 16 }}>
                        <div className="empty-state-text">No products found</div>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}