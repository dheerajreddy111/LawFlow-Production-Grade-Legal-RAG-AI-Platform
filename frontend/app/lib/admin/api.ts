/**
 * Typed client for /api/v1/admin/*.
 *
 * Routes through apiFetch so requests inherit the bearer + refresh-on-401
 * behaviour. Callers receive typed responses or throw an AdminApiError.
 */

import { apiFetch } from "../auth/client";

export interface DocumentsSummary {
  total: number;
  chunks_total: number;
  chunks_active: number;
}

export interface QueriesSummary {
  total: number;
  by_route: Record<string, number>;
  route_share: Record<string, number>;
}

export interface LatencySummary {
  count: number;
  mean_ms: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
}

export interface IngestionSummary {
  by_extension: Record<string, number>;
  total: number;
}

export interface UsersSummary {
  total: number;
  active: number;
  admins: number;
}

export interface OverviewResponse {
  documents: DocumentsSummary;
  queries: QueriesSummary;
  latency: LatencySummary;
  ingestion: IngestionSummary;
  users: UsersSummary;
  uptime_seconds: number;
}

export class AdminApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "AdminApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function parseError(res: Response): Promise<AdminApiError> {
  let detail = `Request failed (HTTP ${res.status})`;
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    /* non-JSON body — fall back to status text */
  }
  return new AdminApiError(res.status, detail);
}

export async function fetchOverview(signal?: AbortSignal): Promise<OverviewResponse> {
  const res = await apiFetch("/api/v1/admin/overview", { signal });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as OverviewResponse;
}

// ── Documents ──────────────────────────────────────────────────────────────

export interface DocumentItem {
  source: string;
  chunks_total: number;
  chunks_active: number;
  versions: number;
  latest_ingested_at: string | null;
}

export interface DocumentsListResponse {
  documents: DocumentItem[];
  total: number;
}

export interface DocumentVersionEntry {
  version_id: string;
  version: number;
  superseded: boolean;
  ingested_at: string | null;
  chunk_count: number;
}

export interface DocumentDetail {
  source: string;
  chunks_total: number;
  chunks_active: number;
  versions: DocumentVersionEntry[];
}

export async function listDocuments(
  signal?: AbortSignal,
): Promise<DocumentsListResponse> {
  const res = await apiFetch("/api/v1/admin/documents", { signal });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as DocumentsListResponse;
}

export async function getDocumentDetail(
  source: string,
  signal?: AbortSignal,
): Promise<DocumentDetail> {
  const res = await apiFetch(
    `/api/v1/admin/documents/${encodeURIComponent(source)}`,
    { signal },
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as DocumentDetail;
}

export async function deleteDocument(source: string): Promise<void> {
  const res = await apiFetch(
    `/api/v1/admin/documents/${encodeURIComponent(source)}`,
    { method: "DELETE" },
  );
  if (!res.ok && res.status !== 204) throw await parseError(res);
}

export interface AdminUploadResponse {
  source: string;
  stored_as: string;
  status: "ingested" | "noop";
  chunks_created: number;
  chunks_superseded: number;
  version: number;
  version_id: string;
  is_new_version: boolean;
  file_size: number;
  word_count: number;
  char_count: number;
  latency_ms: number;
}

/**
 * Upload a corpus document via the admin endpoint. Multipart form-data;
 * apiFetch leaves Content-Type unset on FormData bodies so fetch's
 * auto-boundary path is used.
 */
export async function uploadDocument(file: File): Promise<AdminUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiFetch("/api/v1/admin/documents/upload", {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as AdminUploadResponse;
}

// ── System Health ──────────────────────────────────────────────────────────

export interface HealthCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface VectorStoreStatus {
  collection: string;
  count: number;
  embedding_dim: number;
  path: string;
}

export interface LangSmithStatus {
  configured: boolean;
  project: string;
  endpoint: string | null;
  // Broken-out flags so the UI can distinguish "flag on but no key" from
  // "fully wired". Matches the backend pydantic shape.
  tracing_flag_enabled: boolean;
  api_key_present: boolean;
  // Startup reachability probe outcome.
  connectivity: "unknown" | "ok" | "error";
  connectivity_detail: string | null;
}

export interface LLMProviderInfo {
  name: string;
  configured: boolean;
  model: string | null;
}

export interface LLMProvidersStatus {
  active: string | null;
  providers: LLMProviderInfo[];
}

export interface MemoryStatus {
  sessions: number;
  turns_total: number;
  max_sessions: number;
  window: number;
}

export interface ProcessStatus {
  environment: string;
  debug: boolean;
  python_version: string;
  uptime_seconds: number;
}

export interface CounterEntry {
  name: string;
  value: number;
}

export interface CorpusActRow {
  act_key: string;
  name: string;
  indexed: boolean;
  chunk_count: number;
  domain: string | null;
}

export interface CorpusStatusBlock {
  supported_keys: string[];
  indexed_keys: string[];
  missing_keys: string[];
  orphan_keys: string[];
  total_indexed_chunks: number;
  acts: CorpusActRow[];
}

export interface SystemResponse {
  status: "ok" | "degraded";
  checks: HealthCheck[];
  vector_store: VectorStoreStatus;
  langsmith: LangSmithStatus;
  llm_providers: LLMProvidersStatus;
  memory: MemoryStatus;
  process: ProcessStatus;
  ingest_failures: CounterEntry[];
  error_counters: CounterEntry[];
  corpus: CorpusStatusBlock;
}

export async function fetchSystem(signal?: AbortSignal): Promise<SystemResponse> {
  const res = await apiFetch("/api/v1/admin/system", { signal });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as SystemResponse;
}

// ── Analytics ──────────────────────────────────────────────────────────────

export type AnalyticsRange = "1h" | "24h" | "7d" | "30d";

export interface AnalyticsTotals {
  total: number;
  errors: number;
  error_rate: number;
  avg_latency_ms: number;
  window_start: string;
}

export interface IntentCount {
  intent: string;
  count: number;
}

export interface FailureEntry {
  ts: string;
  query: string;
  intent: string;
  route: string;
  error_reason: string | null;
}

/**
 * One row of the timeseries — always carries `ts` plus one numeric
 * column per active route. Routes are listed under `routes`.
 */
export type TimeseriesRow = { ts: string } & Record<string, string | number>;

export interface AnalyticsResponse {
  range: AnalyticsRange;
  routes: string[];
  timeseries: TimeseriesRow[];
  intent_distribution: IntentCount[];
  route_share: Record<string, number>;
  totals: AnalyticsTotals;
  recent_failures: FailureEntry[];
}

export async function fetchAnalytics(
  range: AnalyticsRange,
  signal?: AbortSignal,
): Promise<AnalyticsResponse> {
  const res = await apiFetch(
    `/api/v1/admin/analytics?range=${encodeURIComponent(range)}`,
    { signal },
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as AnalyticsResponse;
}

// ── Evaluation runs ────────────────────────────────────────────────────────

export interface EvaluationRunSummary {
  id: number;
  name: string;
  dataset_filename: string;
  total_rows: number;
  scored_rows: number;
  failed_rows: number;
  f1_mean: number;
  cosine_mean: number;
  keyword_mean: number;
  retrieval_mean: number;
  created_by: number | null;
  created_at: string;
}

export interface EvaluationRunsListResponse {
  runs: EvaluationRunSummary[];
  total: number;
  /** Cursor for the next page; null when no more rows exist. */
  next_cursor: number | null;
}

export interface EvaluationRowMetric {
  mean: number;
  min: number;
  max: number;
}

export interface EvaluationReportSummary {
  dataset: string;
  total_rows: number;
  scored_rows: number;
  failed_rows: number;
  f1_score: EvaluationRowMetric;
  cosine_similarity: EvaluationRowMetric;
  keyword_overlap: EvaluationRowMetric;
  retrieval_confidence: EvaluationRowMetric;
}

export interface EvaluationRowResult {
  question: string;
  expected_answer: string;
  generated_answer: string;
  f1_score: number;
  cosine_similarity: number;
  keyword_overlap: number;
  retrieval_confidence: number;
  intent: string | null;
  route: string | null;
  error: string | null;
}

export interface EvaluationReport {
  summary: EvaluationReportSummary;
  results: EvaluationRowResult[];
}

export interface EvaluationRunDetail extends EvaluationRunSummary {
  report: EvaluationReport;
}

export async function listEvaluationRuns(
  options: { limit?: number; cursor?: number | null; signal?: AbortSignal } = {},
): Promise<EvaluationRunsListResponse> {
  const params = new URLSearchParams();
  if (options.limit) params.set("limit", String(options.limit));
  if (options.cursor) params.set("cursor", String(options.cursor));
  const qs = params.toString();
  const path = qs
    ? `/api/v1/admin/evaluation/runs?${qs}`
    : "/api/v1/admin/evaluation/runs";
  const res = await apiFetch(path, { signal: options.signal });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as EvaluationRunsListResponse;
}

export async function getEvaluationRun(
  runId: number,
  signal?: AbortSignal,
): Promise<EvaluationRunDetail> {
  const res = await apiFetch(
    `/api/v1/admin/evaluation/runs/${runId}`,
    { signal },
  );
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as EvaluationRunDetail;
}

export async function deleteEvaluationRun(runId: number): Promise<void> {
  const res = await apiFetch(
    `/api/v1/admin/evaluation/runs/${runId}`,
    { method: "DELETE" },
  );
  if (!res.ok && res.status !== 204) throw await parseError(res);
}

/**
 * Upload a CSV (multipart) to the existing /evaluation/run endpoint.
 * The form auto-persists the run; the response also contains the full
 * EvaluationReport for immediate display.
 */
export async function uploadEvaluation(
  file: File,
  options: { name?: string } = {},
): Promise<EvaluationReport> {
  const form = new FormData();
  form.append("file", file);
  if (options.name) form.append("name", options.name);
  const res = await apiFetch("/api/v1/evaluation/run", {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as EvaluationReport;
}

// ── Jobs ───────────────────────────────────────────────────────────────────

export type JobStatus = "queued" | "running" | "completed" | "failed";

export interface JobOut {
  id: number;
  type: string;
  status: JobStatus;
  payload: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface JobListResponse {
  jobs: JobOut[];
  total: number;
}

export async function listJobs(
  limit = 50,
  signal?: AbortSignal,
): Promise<JobListResponse> {
  const res = await apiFetch(`/api/v1/jobs?limit=${limit}`, { signal });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as JobListResponse;
}

export async function getJob(jobId: number, signal?: AbortSignal): Promise<JobOut> {
  const res = await apiFetch(`/api/v1/jobs/${jobId}`, { signal });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as JobOut;
}

export interface AsyncRunResponse {
  job: JobOut;
}

/**
 * Queue an evaluation as a background job. Returns the job descriptor;
 * caller polls /api/v1/jobs/{id} until terminal.
 */
export async function uploadEvaluationAsync(
  file: File,
  options: { name?: string } = {},
): Promise<AsyncRunResponse> {
  const form = new FormData();
  form.append("file", file);
  if (options.name) form.append("name", options.name);
  const res = await apiFetch("/api/v1/evaluation/run-async", {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as AsyncRunResponse;
}
