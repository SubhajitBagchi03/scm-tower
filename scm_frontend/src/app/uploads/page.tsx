"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CommitRequest, CommitResult, ConflictItem, FileRecord, UploadPreviewResponse } from "@/lib/types";

type ConflictResolution = "use_existing" | "use_incoming" | "keep_both";

export default function UploadsPage() {
  const [csvFile, setCsvFile]   = useState<File | null>(null);
  const [pdfFiles, setPdfFiles] = useState<File[]>([]);
  const [preview, setPreview]   = useState<UploadPreviewResponse | null>(null);
  const [commitResult, setCommitResult] = useState<CommitResult | null>(null);
  const [pdfResult, setPdfResult]       = useState("");
  const [files, setFiles]               = useState<FileRecord[]>([]);
  const [conflicts, setConflicts]       = useState<ConflictItem[]>([]);
  const [conflictResolutions, setConflictResolutions] = useState<Record<number, ConflictResolution>>({});
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState("");
  const [inputKey, setInputKey] = useState(0);
  const [pdfInputKey, setPdfInputKey] = useState(0);

  const [pdfHistory, setPdfHistory]       = useState<{filename: string, chunks: number, upload_timestamp: string}[]>([]);

  async function loadMeta() {
    try {
      const [fileRows, conflictRows, pdfRows] = await Promise.all([
        api.listUploadedFiles(), 
        api.listConflicts(),
        api.listPdfFiles()
      ]);
      setFiles(fileRows);
      setConflicts(conflictRows);
      setPdfHistory(pdfRows);
    } catch { /* keep functional */ }
  }

  useEffect(() => { void loadMeta(); }, []);

  async function onCsvPreview(e: FormEvent) {
    e.preventDefault();
    if (!csvFile) return;
    setLoading(true); setError("");
    try {
      const result = await api.previewCsv(csvFile);
      setPreview(result);
      setCommitResult(null);
      setConflictResolutions({});
    } catch (err) {
      setError(err instanceof Error ? err.message : "CSV preview failed");
    } finally { setLoading(false); }
  }

  async function onCsvCommit() {
    if (!preview) return;
    setLoading(true); setError("");
    try {
      const payload: CommitRequest = {
        file_id: preview.file_id,
        conflict_resolutions: Object.entries(conflictResolutions).map(([idx, res]) => {
          const c = (preview.conflicts[Number(idx)] as Record<string, string>) ?? {};
          return { product_name: c.product_name ?? "", field_name: c.field ?? "", resolution: res };
        }),
      };
      const result = await api.commitCsv(payload);
      setCommitResult(result);
      // Clear the form for the next upload
      setPreview(null);
      setCsvFile(null);
      setConflictResolutions({});
      setInputKey((k) => k + 1);
      
      await loadMeta();
    } catch (err) {
      setError(err instanceof Error ? err.message : "CSV commit failed");
    } finally { setLoading(false); }
  }

  async function onPdfUpload(e: FormEvent) {
    e.preventDefault();
    if (pdfFiles.length === 0) return;
    setLoading(true); setError("");
    try {
      const result = await api.uploadPdf(pdfFiles);
      setPdfResult(`Indexed ${result.chunks_added} chunks from ${pdfFiles.length} file(s).`);
      setPdfFiles([]);
      setPdfInputKey(k => k + 1);
      await loadMeta();
    } catch (err) {
      setError(err instanceof Error ? err.message : "PDF upload failed");
    } finally { setLoading(false); }
  }

  function setResolution(idx: number, res: ConflictResolution) {
    setConflictResolutions((prev) => ({ ...prev, [idx]: res }));
  }

  return (
    <div className="page-wrap">
      {error       && <div className="banner banner-danger">{error}</div>}
      {loading     && <div className="banner"><span className="spinner" style={{ display: "inline-block", marginRight: 8 }} />Running...</div>}
      {commitResult && <div className="banner banner-success">{commitResult.message} — {commitResult.rows_saved} rows saved.</div>}
      {pdfResult   && <div className="banner banner-success">{pdfResult}</div>}

      <div className="page-grid grid-2" style={{ alignItems: "start" }}>

        {/* ── CSV Upload ── */}
        <div className="card" style={{ gap: 14 }}>
          <div className="card-label">CSV Upload — Preview & Commit</div>

          <form className="stack" onSubmit={onCsvPreview} style={{ gap: 10 }}>
            <input key={inputKey} type="file" accept=".csv" onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)} />
            <button className="btn btn-primary" type="submit" disabled={!csvFile || loading}>
              {loading ? <><span className="spinner" /> Previewing...</> : "Preview with AI"}
            </button>
          </form>

          {preview && (
            <div className="stack" style={{ gap: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
              {/* Meta */}
              <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                <div className="kv">
                  <span className="kv-label">Detected Type</span>
                  <strong className="kv-value"><span className="pill pill-accent">{preview.file_type}</span></strong>
                </div>
                <div className="kv">
                  <span className="kv-label">Total Rows</span>
                  <strong className="kv-value" style={{ fontFamily: "var(--mono)" }}>{preview.total_rows}</strong>
                </div>
                <div className="kv" style={{ borderBottom: "none" }}>
                  <span className="kv-label">Can Commit</span>
                  <span className={preview.can_commit ? "pill pill-success" : "pill pill-danger"}>
                    {preview.can_commit ? "Yes" : "No"}
                  </span>
                </div>
              </div>

              {preview.message && (
                <div className="muted" style={{ fontSize: 12 }}>{preview.message}</div>
              )}

              {/* Column Mapping */}
              {Object.keys(preview.column_mapping).length > 0 && (
                <div>
                  <div className="card-label" style={{ marginBottom: 8 }}>Column Mapping</div>
                  {Object.entries(preview.column_mapping).map(([from, to]) => (
                    <div key={from} className="mapping-row">
                      <span className="mapping-from">{from}</span>
                      <span className="mapping-arrow">→</span>
                      <span className="mapping-to">{to}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Missing fields */}
              {preview.missing_required.length > 0 && (
                <div className="banner banner-warning">
                  Missing required fields: <strong>{preview.missing_required.join(", ")}</strong>
                </div>
              )}

              {/* Conflicts */}
              {Array.isArray(preview.conflicts) && preview.conflicts.length > 0 && (
                (() => {
                  const manualConflicts = preview.conflicts.filter(c => !(c as any).auto_applied);
                  const autoResolvedCount = preview.conflicts.length - manualConflicts.length;

                  return (
                    <div>
                      {autoResolvedCount > 0 && (
                        <div className="banner" style={{ marginBottom: 16, backgroundColor: "var(--surface)", border: "1px solid var(--border)", color: "var(--text)" }}>
                          ✨ <strong>AI Conflict Resolution:</strong> {autoResolvedCount} conflicts were auto-resolved with high confidence.
                        </div>
                      )}
                      
                      {manualConflicts.length > 0 && (
                        <>
                          <div className="card-label" style={{ marginBottom: 8 }}>
                            Conflicts for Manual Review ({manualConflicts.length})
                          </div>
                          {manualConflicts.map((c) => {
                            const conflict = c as Record<string, any>;
                            const idx = preview.conflicts.indexOf(c);
                            const selected = conflictResolutions[idx];
                            return (
                              <div key={idx} className="conflict-card" style={{ marginBottom: 8 }}>
                                <div style={{ fontWeight: 600, fontSize: 13, color: "var(--text)" }}>
                                  {conflict.product_name ?? "Unknown"}
                                </div>
                                <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                                  Field: {conflict.field}
                                </div>
                                <div style={{ display: "flex", gap: 16, fontSize: 12, color: "var(--muted)" }}>
                                  <span>Existing: <strong style={{ color: "var(--text)" }}>{conflict.existing_value}</strong></span>
                                  <span>Incoming: <strong style={{ color: "var(--yellow)" }}>{conflict.incoming_value}</strong></span>
                                </div>
                                <div className="row-wrap" style={{ gap: 6 }}>
                                  {(["use_incoming", "use_existing", "keep_both"] as ConflictResolution[]).map((r) => (
                                    <button
                                      key={r}
                                      type="button"
                                      className={`btn btn-sm ${selected === r ? "btn-primary" : "btn-ghost"}`}
                                      onClick={() => setResolution(idx, r)}
                                    >
                                      {r.replace(/_/g, " ")}
                                    </button>
                                  ))}
                                </div>
                              </div>
                            );
                          })}
                        </>
                      )}
                    </div>
                  );
                })()
              )}

              <button
                className="btn btn-primary"
                type="button"
                onClick={() => void onCsvCommit()}
                disabled={loading || !preview.can_commit}
              >
                Commit to Database
              </button>
            </div>
          )}
        </div>

        {/* ── PDF Indexing ── */}
        <div className="card" style={{ gap: 14 }}>
          <div className="card-label">PDF Indexing</div>

          <div className="pipeline">
            <span className="pipeline-step">Extract</span>
            <span className="pipeline-arrow">→</span>
            <span className="pipeline-step">Chunk</span>
            <span className="pipeline-arrow">→</span>
            <span className="pipeline-step">Embed</span>
            <span className="pipeline-arrow">→</span>
            <span className="pipeline-step">ChromaDB</span>
          </div>

          <form className="stack" onSubmit={onPdfUpload} style={{ gap: 10 }}>
            <input
              key={`pdf-${pdfInputKey}`}
              type="file"
              multiple
              accept=".pdf"
              onChange={(e) => setPdfFiles(Array.from(e.target.files ?? []))}
            />
            {pdfFiles.length > 0 && (
              <div style={{ fontSize: 12, color: "var(--muted)", fontFamily: "var(--mono)" }}>
                {pdfFiles.length} file(s): {pdfFiles.map((f) => f.name).join(", ")}
              </div>
            )}
            <button className="btn btn-primary" type="submit" disabled={pdfFiles.length === 0 || loading}>
              Index PDF Files
            </button>
          </form>

          <p className="muted" style={{ fontSize: 12, lineHeight: 1.6 }}>
            PDFs are chunked into 1000-character segments with 200-character overlap,
            embedded with local all-MiniLM-L6-v2 embeddings, and stored in ChromaDB for semantic retrieval via the Ask page.
          </p>
        </div>
      </div>

      {/* ── History & Conflict Log ── */}
      <div className="page-grid grid-2">
        <div className="stack" style={{ gap: 16 }}>
          <div className="card" style={{ gap: 12 }}>
            <div className="card-label">Upload History</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Filename</th>
                    <th>Type</th>
                    <th>Rows</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {files.slice(0, 15).map((f) => (
                    <tr key={f.file_id}>
                      <td style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{f.filename}</td>
                      <td><span className="pill pill-muted">{f.file_type}</span></td>
                      <td style={{ fontFamily: "var(--mono)" }}>{f.row_count}</td>
                      <td>
                        <span className={f.status === "confirmed" ? "pill pill-success" : "pill pill-warning"}>
                          {f.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                  {files.length === 0 && (
                    <tr><td colSpan={4} style={{ textAlign: "center", color: "var(--muted)" }}>No uploads yet</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card" style={{ gap: 12 }}>
            <div className="card-label">PDF Index History</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Filename</th>
                    <th>Vector Chunks</th>
                    <th>Indexed At</th>
                  </tr>
                </thead>
                <tbody>
                  {pdfHistory.map((pdf, idx) => (
                    <tr key={idx}>
                      <td style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{pdf.filename}</td>
                      <td style={{ fontFamily: "var(--mono)" }}>{pdf.chunks}</td>
                      <td style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--muted)" }}>
                        {pdf.upload_timestamp ? new Date(pdf.upload_timestamp).toLocaleString() : "Unknown"}
                      </td>
                    </tr>
                  ))}
                  {pdfHistory.length === 0 && (
                    <tr><td colSpan={3} style={{ textAlign: "center", color: "var(--muted)" }}>No PDFs indexed yet</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="card" style={{ gap: 12 }}>
          <div className="card-label">Conflict Log</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Field</th>
                  <th>Existing</th>
                  <th>Incoming</th>
                  <th>Resolution</th>
                </tr>
              </thead>
              <tbody>
                {conflicts.slice(0, 15).map((c) => (
                  <tr key={c.id}>
                    <td style={{ color: "var(--text)" }}>{c.product_name}</td>
                    <td style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{c.field}</td>
                    <td style={{ color: "var(--muted)", fontSize: 12 }}>{c.existing_value}</td>
                    <td style={{ color: "var(--yellow)", fontSize: 12 }}>{c.incoming_value}</td>
                    <td>
                      <span className={c.resolution === "pending" || !c.resolution ? "pill pill-warning" : "pill pill-success"}>
                        {c.resolution ?? "pending"}
                      </span>
                    </td>
                  </tr>
                ))}
                {conflicts.length === 0 && (
                  <tr><td colSpan={5} style={{ textAlign: "center", color: "var(--muted)" }}>No conflicts recorded</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}