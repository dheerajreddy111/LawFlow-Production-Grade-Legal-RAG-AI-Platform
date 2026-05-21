"use client";

import {
  ColumnDef,
  getCoreRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import {
  ClipboardCheck,
  GitCompare,
  RefreshCcw,
  Trash2,
  Upload,
} from "lucide-react";
import {
  ChangeEvent,
  DragEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ConfirmDialog } from "../../components/admin/ConfirmDialog";
import { EvaluationCompareDrawer } from "../../components/admin/EvaluationCompareDrawer";
import { EvaluationRunDrawer } from "../../components/admin/EvaluationRunDrawer";
import { SectionCard } from "../../components/admin/SectionCard";
import { useToast } from "../../components/admin/Toast";
import { VirtualizedTable } from "../../components/admin/VirtualizedTable";
import { cn } from "../../lib/cn";
import {
  deleteEvaluationRun,
  getEvaluationRun,
  listEvaluationRuns,
  uploadEvaluation,
  type EvaluationRunDetail,
  type EvaluationRunSummary,
} from "../../lib/admin/api";

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export default function AdminEvaluationPage() {
  const { notify } = useToast();
  const [runs, setRuns] = useState<EvaluationRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "created_at", desc: true },
  ]);

  // Upload state
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [uploadName, setUploadName] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Drawer state
  const [detail, setDetail] = useState<EvaluationRunDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Delete state
  const [pendingDelete, setPendingDelete] = useState<EvaluationRunSummary | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Side-by-side comparison: track which runs are checked. Capped at 2 —
  // an extra click clears the oldest selection so the operator always
  // ends up with exactly two on a third click.
  const [compareIds, setCompareIds] = useState<number[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);

  const toggleCompare = useCallback((id: number) => {
    setCompareIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      const next = [...prev, id];
      return next.length > 2 ? next.slice(-2) : next;
    });
  }, []);

  // Cursor pagination state — `cursor` is the next-page handle returned
  // by the previous fetch. Null when no more rows exist.
  const [cursor, setCursor] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const load = useCallback(async (silent: boolean) => {
    if (silent) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const data = await listEvaluationRuns({ limit: 50 });
      setRuns(data.runs);
      setCursor(data.next_cursor);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load runs.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const loadMore = useCallback(async () => {
    if (cursor === null || loadingMore) return;
    setLoadingMore(true);
    try {
      const data = await listEvaluationRuns({ limit: 50, cursor });
      setRuns((prev) => [...prev, ...data.runs]);
      setCursor(data.next_cursor);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load more.");
    } finally {
      setLoadingMore(false);
    }
  }, [cursor, loadingMore]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!cancelled) await load(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  const openDetail = useCallback(async (runId: number) => {
    setDrawerOpen(true);
    setDetailLoading(true);
    setDetailError(null);
    setDetail(null);
    try {
      const data = await getEvaluationRun(runId);
      setDetail(data);
    } catch (err) {
      setDetailError(
        err instanceof Error ? err.message : "Could not load run detail.",
      );
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const closeDetail = useCallback(() => {
    setDrawerOpen(false);
    setDetail(null);
    setDetailError(null);
  }, []);

  async function runUpload(file: File) {
    setUploading(true);
    try {
      await uploadEvaluation(file, {
        name: uploadName.trim() || undefined,
      });
      notify("success", `Ran ${file.name} — added to history`);
      setUploadName("");
      await load(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload failed";
      notify("error", message);
    } finally {
      setUploading(false);
    }
  }

  function onFileSelected(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    void runUpload(file);
    e.target.value = "";
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".csv")) {
      notify("error", "Only .csv files are supported.");
      return;
    }
    void runUpload(file);
  }

  async function onConfirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteEvaluationRun(pendingDelete.id);
      setRuns((prev) => prev.filter((r) => r.id !== pendingDelete.id));
      notify("success", `Deleted ${pendingDelete.name}`);
      setPendingDelete(null);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeleting(false);
    }
  }

  const columns = useMemo<ColumnDef<EvaluationRunSummary>[]>(
    () => [
      {
        id: "compare",
        // The header is a visually hidden label — the checkbox column is
        // wide enough that a header label would compete with the content.
        header: () => <span className="sr-only">Compare</span>,
        enableSorting: false,
        cell: ({ row }) => {
          const checked = compareIds.includes(row.original.id);
          return (
            <label
              className="inline-flex items-center justify-center"
              onClick={(e) => e.stopPropagation()}
            >
              <input
                type="checkbox"
                aria-label={`Select ${row.original.name} for comparison`}
                className="h-3.5 w-3.5 accent-[#C9892A]"
                checked={checked}
                onChange={() => toggleCompare(row.original.id)}
              />
            </label>
          );
        },
      },
      {
        id: "name",
        accessorKey: "name",
        header: "Run",
        cell: ({ row }) => (
          <button
            type="button"
            onClick={() => openDetail(row.original.id)}
            className="flex items-start gap-2.5 text-left"
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#0A1628] text-[#D8A849]">
              <ClipboardCheck className="h-3.5 w-3.5" aria-hidden />
            </span>
            <span className="min-w-0">
              <p className="truncate font-display text-[13px] font-semibold text-[#0A1628] hover:underline">
                {row.original.name}
              </p>
              <p className="mt-0.5 truncate font-mono text-[10.5px] text-slate-500">
                {row.original.dataset_filename}
              </p>
            </span>
          </button>
        ),
      },
      {
        id: "scored_rows",
        accessorKey: "scored_rows",
        header: "Rows",
        cell: ({ row }) => (
          <span className="text-[12.5px] text-slate-700">
            <span className="font-display font-semibold text-[#0A1628]">
              {row.original.scored_rows}
            </span>
            <span className="text-slate-400"> / {row.original.total_rows}</span>
            {row.original.failed_rows > 0 && (
              <span className="ml-1.5 rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-bold text-red-700 ring-1 ring-red-200">
                {row.original.failed_rows} failed
              </span>
            )}
          </span>
        ),
      },
      {
        id: "f1_mean",
        accessorKey: "f1_mean",
        header: "F1",
        cell: ({ row }) => <MetricChip value={row.original.f1_mean} />,
      },
      {
        id: "cosine_mean",
        accessorKey: "cosine_mean",
        header: "Cosine",
        cell: ({ row }) => <MetricChip value={row.original.cosine_mean} />,
      },
      {
        id: "retrieval_mean",
        accessorKey: "retrieval_mean",
        header: "Retrieval",
        cell: ({ row }) => <MetricChip value={row.original.retrieval_mean} />,
      },
      {
        id: "created_at",
        accessorKey: "created_at",
        header: "When",
        cell: ({ row }) => (
          <span className="text-[12px] text-slate-500">
            {formatTimestamp(row.original.created_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: () => <span className="sr-only">Actions</span>,
        enableSorting: false,
        cell: ({ row }) => (
          <button
            type="button"
            onClick={() => setPendingDelete(row.original)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1 text-[11px] font-medium text-slate-600 transition-colors hover:border-red-300 hover:bg-red-50 hover:text-red-700"
            aria-label={`Delete ${row.original.name}`}
          >
            <Trash2 className="h-3 w-3" aria-hidden />
            Delete
          </button>
        ),
      },
    ],
    [compareIds, openDetail, toggleCompare],
  );

  // React Compiler skips memoisation around useReactTable — the table
  // API returns functions that can't be memoised safely. Suppress the
  // informational warning per-call (matches the Documents page).
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: runs,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const rows = table.getRowModel().rows;

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-5 py-6 sm:px-8 sm:py-8">
      {/* Page header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-[#9E6A0E]">
            Evaluation
          </p>
          <h1 className="mt-1.5 font-display text-[28px] font-semibold leading-tight tracking-tight text-[#0A1628]">
            Benchmark history
          </h1>
          <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-slate-500">
            Upload a CSV with <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px]">question</code>{" "}
            +{" "}
            <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px]">expected_answer</code>{" "}
            columns. Each run is scored against the live pipeline and persisted
            so trends are visible across model + corpus changes.
          </p>
        </div>
        <button
          type="button"
          onClick={() => load(true)}
          disabled={refreshing || loading}
          className="inline-flex items-center gap-1.5 self-start rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-700 transition-colors hover:border-[#C9892A]/40 hover:text-[#0A1628] disabled:cursor-not-allowed disabled:opacity-60 sm:self-auto"
        >
          <RefreshCcw
            className={cn("h-3.5 w-3.5", refreshing && "animate-spin")}
            aria-hidden
          />
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {/* Upload zone */}
      <SectionCard
        title="Run a new benchmark"
        subtitle="Drag-and-drop or pick a CSV. Scoring uses the live LawFlow pipeline — long datasets take time; the run will appear in the table when complete."
      >
        <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              if (!uploading) setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            className={cn(
              "flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-5 py-6 text-center transition-colors",
              uploading
                ? "border-slate-200 bg-slate-50/60"
                : dragOver
                ? "border-[#C9892A] bg-[#FBF1DC]/40"
                : "border-slate-200 bg-slate-50/40 hover:border-[#C9892A]/55 hover:bg-[#FBF1DC]/20",
            )}
          >
            <Upload
              className={cn(
                "h-5 w-5",
                dragOver ? "text-[#9E6A0E]" : "text-slate-400",
              )}
              aria-hidden
            />
            <p className="mt-2 font-display text-[13px] font-semibold text-[#0A1628]">
              {uploading ? "Running benchmark…" : "Drop a CSV here"}
            </p>
            <p className="text-[11px] text-slate-500">
              or{" "}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="font-semibold text-[#9E6A0E] underline-offset-4 hover:underline disabled:opacity-50"
              >
                browse for a file
              </button>
            </p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,text/csv"
              onChange={onFileSelected}
              className="hidden"
              disabled={uploading}
            />
          </div>

          <div className="flex flex-col gap-2 sm:max-w-[220px]">
            <label className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              Run label (optional)
            </label>
            <input
              type="text"
              value={uploadName}
              onChange={(e) => setUploadName(e.target.value)}
              placeholder="e.g. baseline-v3"
              maxLength={200}
              disabled={uploading}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[12.5px] text-[#0A1628] placeholder:text-slate-400 focus:border-[#C9892A]/60 focus:outline-none focus:ring-2 focus:ring-[#C9892A]/15 disabled:cursor-not-allowed disabled:opacity-60"
            />
            <p className="text-[10.5px] text-slate-400">
              Defaults to filename when empty.
            </p>
          </div>
        </div>
      </SectionCard>

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50/80 px-4 py-3 text-[12.5px] text-red-700"
        >
          {error}
        </div>
      )}

      {/* History toolbar — title row + compare button */}
      <div className="flex flex-col gap-1.5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h3 className="font-display text-[14.5px] font-semibold leading-tight tracking-tight text-[#0A1628]">
            Run history
          </h3>
          <p className="mt-0.5 text-[11.5px] leading-relaxed text-slate-500">
            Click a row to inspect its per-row breakdown — or select two
            runs to compare side-by-side.{" "}
            {!loading && (
              <span className="text-slate-400">
                Showing {runs.length} run{runs.length === 1 ? "" : "s"}.
              </span>
            )}
          </p>
        </div>
        <button
          type="button"
          disabled={compareIds.length !== 2}
          onClick={() => setCompareOpen(true)}
          className={cn(
            "inline-flex items-center gap-1.5 self-start rounded-lg border px-3 py-1.5 text-[12px] font-medium transition-colors sm:self-auto",
            compareIds.length === 2
              ? "border-[#C9892A]/55 bg-[#FBF1DC]/40 text-[#9E6A0E] hover:bg-[#FBF1DC]/60"
              : "cursor-not-allowed border-slate-200 bg-white text-slate-400",
          )}
        >
          <GitCompare className="h-3.5 w-3.5" aria-hidden />
          Compare {compareIds.length}/2
        </button>
      </div>

      {/* Virtualised history table — caps the viewport at ~640px and only
          mounts visible rows. Cursor pagination feeds in 50 rows at a time. */}
      <VirtualizedTable
        table={table}
        loading={loading}
        rowHeight={56}
        viewportClassName="max-h-[60vh]"
        animateRows={rows.length < 60}
        emptyState={
          <>
            <ClipboardCheck
              className="mx-auto h-7 w-7 text-slate-300"
              aria-hidden
            />
            <p className="mt-3 font-display text-[14px] font-semibold text-[#0A1628]">
              No benchmark runs yet
            </p>
            <p className="mt-1 text-[12px] text-slate-500">
              Upload a CSV above to score the live pipeline.
            </p>
          </>
        }
      />

      {cursor !== null && (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={loadMore}
            disabled={loadingMore}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-[12px] font-medium text-slate-700 transition-colors hover:border-[#C9892A]/40 hover:text-[#0A1628] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      )}

      {drawerOpen && (
        <EvaluationRunDrawer
          detail={detail}
          loading={detailLoading}
          error={detailError}
          onClose={closeDetail}
        />
      )}

      <EvaluationCompareDrawer
        open={compareOpen}
        runIds={compareIds.length === 2 ? (compareIds as [number, number]) : null}
        onClose={() => setCompareOpen(false)}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete run?"
        description={
          <>
            <p>
              Permanently removes the persisted run{" "}
              <span className="font-semibold text-[#0A1628]">
                {pendingDelete?.name}
              </span>{" "}
              and its per-row report. The live pipeline is unaffected.
            </p>
          </>
        }
        variant="destructive"
        confirmLabel={deleting ? "Deleting…" : "Delete forever"}
        cancelLabel="Cancel"
        busy={deleting}
        onConfirm={onConfirmDelete}
        onCancel={() => !deleting && setPendingDelete(null)}
      />
    </div>
  );
}

function MetricChip({ value }: { value: number }) {
  const p = Math.round(value * 100);
  const tone =
    p >= 80
      ? "text-emerald-700 bg-emerald-50 ring-emerald-200"
      : p >= 50
      ? "text-[#9E6A0E] bg-[#FBF1DC] ring-[#E8C97A]/70"
      : "text-rose-700 bg-rose-50 ring-rose-200";
  return (
    <span
      className={cn(
        "inline-flex min-w-[3.5rem] justify-center tabular-nums rounded px-1.5 py-0.5 text-[11px] font-bold ring-1",
        tone,
      )}
    >
      {pct(value)}
    </span>
  );
}
