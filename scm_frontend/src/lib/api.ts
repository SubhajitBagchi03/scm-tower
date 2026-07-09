
import type {
  AgentRequest,
  AgentResponse,
  AppHealth,
  CommitRequest,
  CommitResult,
  ConflictItem,
  FileRecord,
  InventoryAnalysis,
  InventoryItem,
  RagRequest,
  RagResponse,
  UploadPreviewResponse,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  getHealth:           () => request<AppHealth>("/"),
  getInventory:        () => request<InventoryItem[]>("/inventory/"),
  getInventoryAlerts:  () => request<InventoryAnalysis[]>("/inventory/status/alerts"),
  analyzeInventoryItem:(productId: string) =>
    request<InventoryAnalysis>(`/inventory/${encodeURIComponent(productId)}/analyze`),

  previewCsv: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadPreviewResponse>("/upload/preview", { method: "POST", body: form });
  },

  commitCsv: (payload: CommitRequest) =>
    request<CommitResult>("/upload/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  uploadPdf: async (files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return request<{ status: string; chunks_added: number }>("/upload/pdf", {
      method: "POST",
      body: form,
    });
  },

  listUploadedFiles: () => request<FileRecord[]>("/upload/files"),
  listPdfFiles:      () => request<{filename: string, chunks: number, upload_timestamp: string}[]>("/upload/pdf/files"),
  listConflicts:     () => request<ConflictItem[]>("/upload/conflicts"),

  queryRag: (payload: RagRequest) =>
    request<RagResponse>("/rag/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  async executeAgent(req: AgentRequest): Promise<AgentResponse> {
    return request<AgentResponse>("/agent/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
  },

  async resetSystem(): Promise<{status: string, message: string}> {
    return request<{status: string, message: string}>("/system/reset", {
      method: "POST",
    });
  },

  async downloadReportPdfContext(payload: { assessment_result?: string, judge_status?: string, judge_reasoning?: string }): Promise<Blob> {
    const response = await fetch(`${API_BASE}/agent/report/pdf_context`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(`Failed to download PDF: ${response.status}`);
    }
    return response.blob();
  },

  reportPdfUrl: `${API_BASE}/agent/report/pdf`,
};