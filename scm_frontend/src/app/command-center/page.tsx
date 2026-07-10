"use client";

import { useState, useCallback } from "react";
import { api } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type {
  AgentAction, AgentResponse, AgentTrace, JudgeVerdict,
} from "@/lib/types";

// ── Action definitions ───────────────────────────────────────

type ActionDef = {
  id: AgentAction;
  label: string;
  icon: string;
  desc: string;
  inputs: ("product_id" | "quantity" | "urgency" | "shipment_id" | "query")[];
};

const ACTIONS: ActionDef[] = [
  {
    id: "full_assessment",
    label: "Full Assessment",
    icon: "play_circle",
    desc: "Supervisor orchestrates all agents autonomously",
    inputs: [],
  },
  {
    id: "analyze_inventory",
    label: "Analyze Inventory",
    icon: "inventory_2",
    desc: "Stock health, EOQ, reorder urgency",
    inputs: ["product_id"],
  },
  {
    id: "select_supplier",
    label: "Select Supplier",
    icon: "storefront",
    desc: "Weighted ranking by urgency and context",
    inputs: ["quantity", "urgency"],
  },
  {
    id: "track_shipment",
    label: "Track Shipment",
    icon: "local_shipping",
    desc: "Delay risk and cascade detection",
    inputs: ["shipment_id"],
  },
  {
    id: "generate_report",
    label: "Generate Report",
    icon: "article",
    desc: "Executive KPI report across all domains",
    inputs: [],
  },
  {
    id: "ask",
    label: "Ask",
    icon: "smart_toy",
    desc: "Query documents or live supply chain data",
    inputs: ["query"],
  },
];

const URGENCY_OPTIONS = ["normal", "urgent", "immediate"];

// ── Agent dot color by name ──────────────────────────────────

function agentDotClass(name: string): string {
  if (name === "supervisor") return "trace-dot trace-dot-supervisor";
  return "trace-dot trace-dot-inventory";
}

function agentLabel(name: string): string {
  const labels: Record<string, string> = {
    supervisor:       "SUPERVISOR",
    inventory_agent:  "INVENTORY",
    supplier_agent:   "SUPPLIER",
    shipment_agent:   "SHIPMENT",
    report_agent:     "REPORT",
    judge:            "JUDGE",
  };
  return labels[name] ?? name.toUpperCase();
}

// ── Confidence bar class ─────────────────────────────────────

function confBarClass(c: number) {
  if (c >= 0.75) return "confidence-bar";
  if (c >= 0.55) return "confidence-bar confidence-bar-warn";
  return "confidence-bar confidence-bar-bad";
}

// ── Trace Timeline component ─────────────────────────────────

function TraceTimeline({ trace }: { trace: AgentTrace }) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const toggle = (i: number) =>
    setExpanded((prev) => {
      const s = new Set(prev);
      s.has(i) ? s.delete(i) : s.add(i);
      return s;
    });

  const totalSec = (trace.total_duration_ms / 1000).toFixed(1);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      <div className="card-label" style={{ marginBottom: 12 }}>Execution Trace</div>
      <div className="trace-timeline">
        {trace.steps.map((step, i) => {
          const isExp = expanded.has(i);
          const isJudge = step.agent_name === "judge";
          const judgeOk = isJudge && (step.data as Record<string, unknown>)?.is_valid === true;
          return (
            <div key={i} className="trace-step">
              <div className={
                isJudge
                  ? judgeOk ? "trace-dot trace-dot-judge-ok" : "trace-dot trace-dot-judge-fail"
                  : agentDotClass(step.agent_name)
              } />
              <div className="trace-body" onClick={() => toggle(i)} style={{ cursor: "pointer" }}>
                <div className="trace-header">
                  <span className="trace-agent" style={
                    step.agent_name === "supervisor" ? { color: "var(--accent)" } :
                    isJudge ? { color: judgeOk ? "var(--green)" : "var(--red)" } :
                    { color: "var(--text2)" }
                  }>
                    {agentLabel(step.agent_name)}
                  </span>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span className="pill" style={{ background: "rgba(0,0,0,0.04)", color: "var(--muted)", fontSize: 10, padding: "2px 8px" }}>
                      {(step.confidence * 100).toFixed(0)}%
                    </span>
                    <span className="trace-duration">
                      {step.duration_ms > 0 ? `${(step.duration_ms / 1000).toFixed(1)}s` : "—"}
                    </span>
                    <span style={{ color: "var(--label)", fontSize: 10 }}>{isExp ? "▲" : "▼"}</span>
                  </div>
                </div>
                <div className="trace-finding">{step.finding}</div>
                {isExp && (
                  <div className="trace-detail">
                    <div style={{ marginBottom: 6, fontWeight: 500, color: "var(--muted)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "var(--mono)" }}>Task</div>
                    <div style={{ marginBottom: 10 }}>{step.task}</div>
                    {Boolean((step.data as Record<string, unknown>)?.reasoning) && (
                      <>
                        <div style={{ marginBottom: 6, fontWeight: 500, color: "var(--muted)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "var(--mono)" }}>Reasoning</div>
                        <div className="prose">{String((step.data as Record<string, unknown>).reasoning ?? "")}</div>
                      </>
                    )}
                    {isJudge && Array.isArray((step.data as Record<string, unknown>).warnings) &&
                      ((step.data as Record<string, unknown>).warnings as string[]).length > 0 && (
                        <div style={{ marginTop: 8 }}>
                          {((step.data as Record<string, unknown>).warnings as string[]).map((w, wi) => (
                            <div key={wi} className="judge-issue-item" style={{ marginTop: 4 }}>⚠ {String(w)}</div>
                          ))}
                        </div>
                      )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="trace-summary">
        <span>Total: <strong style={{ color: "var(--text)" }}>{totalSec}s</strong></span>
        <span>Steps: <strong style={{ color: "var(--text)" }}>{trace.steps.length}</strong></span>
        {trace.judge_verdict && (
          <span>Confidence:{" "}
            <strong style={{ color: trace.judge_verdict.overall_confidence >= 0.75 ? "var(--green)" : "var(--yellow)" }}>
              {(trace.judge_verdict.overall_confidence * 100).toFixed(0)}%
            </strong>
          </span>
        )}
        <span style={{ marginLeft: "auto", fontStyle: "italic" }}>Run {trace.run_id.slice(0, 8)}</span>
      </div>
    </div>
  );
}

// ── Judge Verdict component ──────────────────────────────────

function JudgeCard({ verdict }: { verdict: JudgeVerdict }) {
  const pct = Math.round(verdict.overall_confidence * 100);
  return (
    <div className={`judge-card ${verdict.is_valid ? "judge-card-valid" : "judge-card-invalid"}`}>
      <div className="judge-header">
        <div className="judge-title">Judge Verdict</div>
        <div className="judge-status" style={{ color: verdict.is_valid ? "var(--green)" : "var(--red)" }}>
          {verdict.is_valid ? "✓ Valid" : "✗ Invalid"}
        </div>
      </div>
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontSize: 12, color: "var(--muted)" }}>
          <span>Overall Confidence</span>
          <span style={{ fontFamily: "var(--mono)", fontWeight: 700, color: pct >= 75 ? "var(--green)" : pct >= 55 ? "var(--yellow)" : "var(--red)" }}>{pct}%</span>
        </div>
        <div className="confidence-bar-wrap">
          <div className={confBarClass(verdict.overall_confidence)} style={{ width: `${pct}%` }} />
        </div>
      </div>
      {verdict.contradictions.length > 0 && (
        <div>
          <div className="card-label" style={{ marginBottom: 6, color: "var(--red)" }}>Contradictions</div>
          <div className="judge-issues" style={{ maxHeight: "200px", overflowY: "auto", paddingRight: 4, display: "flex", flexDirection: "column", gap: 8 }}>
            {verdict.contradictions.map((c, i) => (
              <div key={i} className="judge-issue-item" style={{ borderLeftColor: "var(--red)" }}>✗ {c}</div>
            ))}
          </div>
        </div>
      )}
      {verdict.warnings.length > 0 && (
        <div>
          <div className="card-label" style={{ marginBottom: 6 }}>Warnings</div>
          <div className="judge-issues" style={{ maxHeight: "200px", overflowY: "auto", paddingRight: 4, display: "flex", flexDirection: "column", gap: 8 }}>
            {verdict.warnings.map((w, i) => (
              <div key={i} className="judge-issue-item">⚠ {w}</div>
            ))}
          </div>
        </div>
      )}
      {verdict.improvements.length > 0 && (
        <div>
          <div className="card-label" style={{ marginBottom: 6, color: "var(--green)" }}>Improvements</div>
          <div className="judge-issues" style={{ maxHeight: "200px", overflowY: "auto", paddingRight: 4, display: "flex", flexDirection: "column", gap: 8 }}>
            {verdict.improvements.map((imp, i) => (
              <div key={i} className="judge-issue-item" style={{ borderLeftColor: "var(--green)" }}>💡 {imp}</div>
            ))}
          </div>
        </div>
      )}
      {verdict.reasoning && (
        <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.6, paddingTop: 4, borderTop: "1px solid var(--border)" }}>
          {verdict.reasoning}
        </div>
      )}
    </div>
  );
}

// ── Executive Report View ────────────────────────────────────

function ReportView({ result, pdfUrl }: { result: AgentResponse; pdfUrl: string }) {
  const kpis = result.kpis as Record<string, number> | undefined;

  const kpiFormatted = (key: string, val: unknown) => {
    if (typeof val === "number") {
      if (key.includes("rate") || key.includes("health") || key.includes("score")) return `${val.toFixed(1)}%`;
      return val % 1 === 0 ? String(val) : val.toFixed(1);
    }
    return String(val ?? "—");
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      {/* KPI Snapshot */}
      {kpis && (
        <div className="card" style={{ gap: 12 }}>
          <div className="card-label">KPI Snapshot</div>
          <div className="kpi-grid">
            {Object.entries(kpis).map(([k, v]) => {
              const numVal = typeof v === "number" ? v : 0;
              const color = numVal >= 80 ? "var(--green)" : numVal >= 60 ? "var(--yellow)" : "var(--red)";
              return (
                <div key={k} className="kpi-card">
                  <div className="kpi-label">{k.replace(/_/g, " ")}</div>
                  <div className="kpi-value" style={{ color, fontSize: 22, fontWeight: 700 }}>
                    {kpiFormatted(k, v)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Executive Summary */}
      {result.executive_summary && (
        <div className="card" style={{ gap: 12 }}>
          <div className="card-label" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>summarize</span>
            Executive Summary
          </div>
          <div style={{ fontSize: 14, lineHeight: 1.8, color: "var(--text2)", whiteSpace: "pre-wrap" }}>
            {result.executive_summary}
          </div>
        </div>
      )}

      {/* Root Causes */}
      {result.root_causes && result.root_causes.length > 0 && (
        <div className="card" style={{ gap: 12 }}>
          <div className="card-label" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>troubleshoot</span>
            Root Causes
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {result.root_causes.map((cause, i) => (
              <div key={i} className="judge-issue-item" style={{ borderLeftColor: "var(--yellow)" }}>{cause}</div>
            ))}
          </div>
        </div>
      )}

      {/* Forward Projections */}
      {result.forward_projections && result.forward_projections.length > 0 && (
        <div className="card" style={{ gap: 12 }}>
          <div className="card-label" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>trending_up</span>
            Forward Projections
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {result.forward_projections.map((proj, i) => (
              <div key={i} className="judge-issue-item" style={{ borderLeftColor: "var(--accent)" }}>{proj}</div>
            ))}
          </div>
        </div>
      )}

      {/* Recommendations */}
      {Array.isArray((result.recommendation as Record<string, unknown>)?.report_actions) &&
        ((result.recommendation as Record<string, unknown>).report_actions as string[]).length > 0 && (
        <div className="card" style={{ gap: 12 }}>
          <div className="card-label" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>checklist</span>
            Recommendations
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {((result.recommendation as Record<string, unknown>).report_actions as string[]).map((rec, i) => (
              <div key={i} className="judge-issue-item" style={{ borderLeftColor: "var(--green)" }}>💡 {rec}</div>
            ))}
          </div>
        </div>
      )}

      {/* Download */}
      <a
        href={pdfUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="btn btn-primary"
        style={{ textAlign: "center", textDecoration: "none", display: "block" }}
      >
        ↓ Download Full Report as PDF
      </a>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────

export default function CommandCenterPage() {
  const [selectedAction, setSelectedAction] = useState<AgentAction>("full_assessment");
  const [productId, setProductId] = useState("");
  const [quantity, setQuantity] = useState(100);
  const [urgency, setUrgency] = useState("normal");
  const [shipmentId, setShipmentId] = useState("");
  const [query, setQuery] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<AgentResponse | null>(null);

  const selectedDef = ACTIONS.find((a) => a.id === selectedAction)!;
  const [isDownloading, setIsDownloading] = useState(false);

  const handleDownloadReport = useCallback(async () => {
    if (!result) return;
    
    setIsDownloading(true);
    try {
      const payload = {
        assessment_result: result.result || undefined,
        judge_status: result.judge_verdict?.is_valid ? "Valid" : "Invalid",
        judge_reasoning: result.judge_verdict?.reasoning || undefined
      };
      
      const blob = await api.downloadReportPdfContext(payload);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `assessment_report_${new Date().getTime()}.pdf`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      alert("Failed to download PDF: " + (err as Error).message);
    } finally {
      setIsDownloading(false);
    }
  }, [result]);

  const run = useCallback(async () => {
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const res = await api.executeAgent({
        action: selectedAction,
        product_id: productId || undefined,
        quantity: quantity || 100,
        urgency: urgency || "normal",
        shipment_id: shipmentId || undefined,
        query: query || undefined,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Agent run failed");
    } finally {
      setLoading(false);
    }
  }, [selectedAction, productId, quantity, urgency, shipmentId, query]);

  const isReportMode = selectedAction === "generate_report";

  return (
    <div className="page-wrap">
      <div style={{ display: "grid", gridTemplateColumns: "380px 1fr", gap: 20, alignItems: "start" }}>

        {/* ── LEFT PANEL ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

          {/* Action Selection */}
          <div className="card" style={{ gap: 12 }}>
            <div className="card-label">Select Action</div>
            <div className="action-grid">
              {ACTIONS.map((action) => (
                <button
                  key={action.id}
                  className={`action-card${selectedAction === action.id ? " action-card-active" : ""}`}
                  onClick={() => { setSelectedAction(action.id); setResult(null); }}
                  type="button"
                >
                  <div className="action-card-title">
                    <span className="material-symbols-outlined" style={{ marginRight: 6, fontSize: 18, verticalAlign: "middle" }}>{action.icon}</span>
                    {action.label}
                  </div>
                  <div className="action-card-desc">{action.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Inputs */}
          {selectedDef.inputs.length > 0 && (
            <div className="card" style={{ gap: 12 }}>
              <div className="card-label">Parameters</div>
              <div className="stack">
                {selectedDef.inputs.includes("product_id") && (
                  <div className="stack" style={{ gap: 4 }}>
                    <label htmlFor="product_id">Product ID</label>
                    <input id="product_id" type="text" placeholder="e.g. P020 or leave empty for all"
                      value={productId} onChange={(e) => setProductId(e.target.value)} />
                  </div>
                )}
                {selectedDef.inputs.includes("quantity") && (
                  <div className="stack" style={{ gap: 4 }}>
                    <label htmlFor="quantity">Quantity</label>
                    <input id="quantity" type="number" min={1} value={quantity}
                      onChange={(e) => setQuantity(Number(e.target.value))} />
                  </div>
                )}
                {selectedDef.inputs.includes("urgency") && (
                  <div className="stack" style={{ gap: 4 }}>
                    <label htmlFor="urgency">Urgency</label>
                    <select id="urgency" value={urgency} onChange={(e) => setUrgency(e.target.value)}>
                      {URGENCY_OPTIONS.map((u) => (
                        <option key={u} value={u}>{u.charAt(0).toUpperCase() + u.slice(1)}</option>
                      ))}
                    </select>
                  </div>
                )}
                {selectedDef.inputs.includes("shipment_id") && (
                  <div className="stack" style={{ gap: 4 }}>
                    <label htmlFor="shipment_id">Shipment ID</label>
                    <input id="shipment_id" type="text" placeholder="e.g. SHP-001"
                      value={shipmentId} onChange={(e) => setShipmentId(e.target.value)} />
                  </div>
                )}
                {selectedDef.inputs.includes("query") && (
                  <div className="stack" style={{ gap: 4 }}>
                    <label htmlFor="query">Question</label>
                    <textarea id="query" rows={3} placeholder="Ask about inventory, suppliers, shipments..."
                      value={query} onChange={(e) => setQuery(e.target.value)} />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Execute */}
          <button className="btn btn-primary btn-lg" onClick={() => void run()} disabled={loading} type="button" style={{ width: "100%" }}>
            {loading ? (<><span className="spinner" /> Running {selectedDef.label}...</>) : (`▶  Run ${selectedDef.label}`)}
          </button>

        </div>

        {/* ── RIGHT PANEL ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

          {error && <div className="banner banner-danger">{error}</div>}

          {!result && !loading && (
            <div className="card">
              <div className="empty-state">
                <div className="empty-state-icon material-symbols-outlined">
                  {isReportMode ? "article" : "settings_suggest"}
                </div>
                <div className="empty-state-text">
                  {isReportMode
                    ? "Click Run Generate Report to produce your Executive Supply Chain Report."
                    : "Select an action and click Run to see the Supervisor-Judge pipeline in action."}
                </div>
              </div>
            </div>
          )}

          {loading && (
            <div className="card">
              <div className="empty-state">
                <div className="spinner" style={{ width: 24, height: 24, borderWidth: 3 }} />
                <div className="empty-state-text pulse">
                  {isReportMode
                    ? "Report Agent is gathering KPIs and synthesising the executive report..."
                    : "Supervisor is planning... agents are running..."}
                </div>
              </div>
            </div>
          )}

          {/* ── GENERATE REPORT: show structured report ── */}
          {result && isReportMode && (
            <ReportView result={result} pdfUrl={api.reportPdfUrl} />
          )}

          {/* ── ALL OTHER ACTIONS: show assessment trace ── */}
          {result && !isReportMode && (
            <>
              {/* Main Finding */}
              <div className="card" style={{ gap: 12 }}>
                <div className="card-label">Assessment Result</div>
                {result.result && (
                  <div style={{ fontSize: 14, fontWeight: 500, color: "var(--text)" }} className="prose">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.result}</ReactMarkdown>
                  </div>
                )}
                {result.reasoning && (
                  <div style={{ fontSize: 13, color: "var(--text2)", lineHeight: 1.7, paddingTop: 8, borderTop: "1px solid var(--border)" }}>
                    {result.reasoning}
                  </div>
                )}
                {result.issue && (
                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                    {typeof result.issue.critical_inventory_items === "number" && result.issue.critical_inventory_items > 0 && (
                      <span className="pill pill-danger">{result.issue.critical_inventory_items as number} Critical Items</span>
                    )}
                    {typeof result.issue.high_risk_shipments === "number" && result.issue.high_risk_shipments > 0 && (
                      <span className="pill pill-warning">{result.issue.high_risk_shipments as number} High-Risk Shipments</span>
                    )}
                    {typeof result.issue.cascade_risks === "number" && result.issue.cascade_risks > 0 && (
                      <span className="pill pill-danger">{result.issue.cascade_risks as number} Cascade Risk(s)</span>
                    )}
                  </div>
                )}
              </div>

              {/* Agent Trace Timeline */}
              {result.trace && result.trace.steps.length > 0 && (
                <div className="card" style={{ gap: 12 }}>
                  <TraceTimeline trace={result.trace} />
                </div>
              )}

              {/* Judge Verdict */}
              {result.judge_verdict && <JudgeCard verdict={result.judge_verdict} />}

              {/* KPIs */}
              {result.kpis && (
                <div className="card" style={{ gap: 12 }}>
                  <div className="card-label">KPIs</div>
                  <div className="kpi-grid">
                    {Object.entries(result.kpis).map(([k, v]) => (
                      <div key={k} className="kpi-card">
                        <div className="kpi-label">{k.replace(/_/g, " ")}</div>
                        <div className="kpi-value" style={{ color: "var(--text)", fontSize: 18 }}>
                          {typeof v === "number" ? (v > 10 ? v.toFixed(1) : v) : String(v)}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Cascade Risks */}
              {result.cascade_risk && (
                <div className="banner banner-danger" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <strong>Cascade Risk(s):</strong>
                  <ul style={{ margin: 0, paddingLeft: 20, fontSize: 14, lineHeight: 1.5, display: "flex", flexDirection: "column", gap: 4 }}>
                    {result.cascade_risk.split("\n").filter(Boolean).map((risk, i) => (
                      <li key={i}>{risk.replace(/🚨|⚠️/g, "")}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Download Assessment Report - hidden for Ask action */}
              {selectedAction !== "ask" && (
                <button 
                  className="btn btn-primary" 
                  onClick={() => void handleDownloadReport()}
                  disabled={isDownloading}
                  type="button"
                  style={{ width: "100%", marginTop: 8, justifyContent: "center" }}
                >
                  {isDownloading ? "Generating PDF..." : "↓ Download Assessment Report as PDF"}
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
