"use client";

import { useState, useCallback } from "react";
import { api } from "@/lib/api";
import type { RagResponse } from "@/lib/types";

const EXAMPLES = [
  "What is the penalty if a supplier's shipment is 4 days late?",
  "What is the minimum on-time delivery rate for carriers?",
  "Which products are at risk of stockout in the next 14 days?",
  "Which supplier has the best on-time delivery rate?",
  "What are the safety stock requirements for Tier 1 components?",
  "Which shipments are high risk right now?",
];

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [lastDoc, setLastDoc]   = useState(false);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState("");
  const [result, setResult]     = useState<RagResponse | null>(null);

  const ask = useCallback(async () => {
    if (!question.trim()) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const res = await api.queryRag({
        question: question.trim(),
        top_k: 5,
        use_only_last_document: lastDoc,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Query failed");
    } finally {
      setLoading(false);
    }
  }, [question, lastDoc]);

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void ask();
  };

  return (
    <div className="page-wrap">
      <div className="page-grid grid-2" style={{ alignItems: "start" }}>

        {/* ── Input Panel ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="card" style={{ gap: 14 }}>
            <div className="card-label">Ask a Question</div>
            <p style={{ fontSize: 12, color: "var(--muted)", marginTop: -4 }}>
              Ask about uploaded PDF documents (SLAs, contracts, policies)
              or live inventory, supplier, and shipment data.
              The system routes automatically.
            </p>

            {/* Example chips */}
            <div>
              <div className="card-label" style={{ marginBottom: 8 }}>Examples</div>
              <div className="chip-row">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    className={`chip${question === ex ? " chip-active" : ""}`}
                    type="button"
                    onClick={() => setQuestion(ex)}
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </div>

            <div className="stack" style={{ gap: 6 }}>
              <label htmlFor="question">Your Question</label>
              <textarea
                id="question"
                rows={4}
                placeholder="Ask about shipment SLAs, penalties, stock requirements, supplier performance..."
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={handleKey}
              />
              <div style={{ fontSize: 11, color: "var(--label)" }}>Ctrl+Enter to submit</div>
            </div>

            <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={lastDoc}
                onChange={(e) => setLastDoc(e.target.checked)}
              />
              <span style={{ fontSize: 13, color: "var(--text2)" }}>
                Restrict to last uploaded document only
              </span>
            </label>

            <button
              className="btn btn-primary"
              type="button"
              onClick={() => void ask()}
              disabled={loading || !question.trim()}
              style={{ width: "100%" }}
            >
              {loading ? <><span className="spinner" /> Searching...</> : "◈ Ask"}
            </button>
          </div>

          {/* Info banner */}
          <div className="banner" style={{ fontSize: 12 }}>
            <strong style={{ color: "var(--text)" }}>Document questions</strong> — queries about contracts, SLAs, policies, procedures — are answered from indexed PDFs.<br />
            <strong style={{ color: "var(--text)" }}>Data questions</strong> — about stock levels, suppliers, shipment risk — pull from live database.
          </div>
        </div>

        {/* ── Answer Panel ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

          {error && <div className="banner banner-danger">{error}</div>}

          {!result && !loading && (
            <div className="card">
              <div className="empty-state">
                <div className="empty-state-icon material-symbols-outlined">smart_toy</div>
                <div className="empty-state-text">
                  Submit a question to see the grounded answer.
                </div>
              </div>
            </div>
          )}

          {loading && (
            <div className="card">
              <div className="empty-state">
                <div className="spinner" style={{ width: 24, height: 24, borderWidth: 3 }} />
                <div className="empty-state-text pulse">Retrieving and generating answer...</div>
              </div>
            </div>
          )}

          {result && (
            <>
              <div className="card" style={{ gap: 14 }}>
                <div className="card-label">Answer</div>
                {result.question && (
                  <div style={{
                    fontSize: 12,
                    color: "var(--muted)",
                    fontStyle: "italic",
                    borderLeft: "3px solid var(--accent)",
                    paddingLeft: 10,
                  }}>
                    {result.question}
                  </div>
                )}
                <div className="prose">{result.answer}</div>
              </div>

              {/* Source citations */}
              {result.show_sources && result.sources.length > 0 && (
                <div className="card" style={{ gap: 12 }}>
                  <div className="card-label">Source Citations</div>
                  {result.sources.map((s, i) => (
                    <div key={i} className="conflict-card" style={{ borderLeftColor: "var(--accent)" }}>
                      <div className="row">
                        <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--accent)" }}>
                          {s.source || "Document"}
                        </span>
                        <span className="pill pill-muted">
                          {s.page ? `Page ${s.page}` : ""}
                        </span>
                      </div>
                      <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.6 }}>
                        {s.text}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {result.filtered_to_last_document && result.document_used && (
                <div className="banner">
                  Filtered to document: <strong style={{ color: "var(--text)" }}>{result.document_used}</strong>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
