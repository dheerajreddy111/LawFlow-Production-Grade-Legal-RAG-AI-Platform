"use client";

import {
  ColumnDef,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import {
  FileText,
  Layers,
  RefreshCcw,
  Search,
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
import { SectionCard } from "../../components/admin/SectionCard";
import { useToast } from "../../components/admin/Toast";
import { VirtualizedTable } from "../../components/admin/VirtualizedTable";
import { cn } from "../../lib/cn";
import {
  deleteDocument,
  listDocuments,
  uploadDocument,
  type DocumentItem,
} from "../../lib/admin/api";

// Extensions the backend pipeline accepts. Kept in sync with
// app/ingestion/pipeline.py:_PARSERS.
const ACCEPTED_EXTENSIONS = [
  ".pdf",
  ".docx",
  ".txt",
  ".md",
  ".csv",
  ".xlsx",
  ".png",
  ".jpg",
  ".jpeg",
  ".tiff",
  ".tif",
  ".bmp",
  ".webp",
] as const;
const ACCEPT_ATTR = ACCEPTED_EXTENSIONS.join(",");

function hasAcceptedExtension(filename: string): boolean {
  const lower = filename.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

function formatIngested(value: string | null): string {
  if (!value) return "—";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

export default function AdminDocumentsPage() {
  const { notify } = useToast();
  const [rows, setRows] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([
    { id: "latest_ingested_at", desc: true },
  ]);

  // Delete flow state
  const [pendingDelete, setPendingDelete] = useState<DocumentItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Upload flow state
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(
    async (silent: boolean) => {
      if (silent) setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        const data = await listDocuments();
        setRows(data.documents);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Could not load documents.";
        setError(message);
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!cancelled) await load(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  const columns = useMemo<ColumnDef<DocumentItem>[]>(
    () => [
      {
        id: "source",
        accessorKey: "source",
        header: "Source",
        cell: ({ row }) => (
          <div className="flex items-center gap-2.5">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
              <FileText className="h-3.5 w-3.5" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="truncate font-display text-[13px] font-semibold text-[#0A1628]">
                {row.original.source}
              </p>
              <p className="mt-0.5 text-[10.5px] uppercase tracking-[0.14em] text-slate-400">
                {row.original.versions > 1
                  ? `${row.original.versions} versions`
                  : "single version"}
              </p>
            </div>
          </div>
        ),
      },
      {
        id: "chunks_active",
        accessorKey: "chunks_active",
        header: "Active chunks",
        cell: ({ row }) => (
          <span className="font-display text-[13px] font-semibold tabular-nums text-[#0A1628]">
            {row.original.chunks_active.toLocaleString()}
          </span>
        ),
      },
      {
        id: "chunks_total",
        accessorKey: "chunks_total",
        header: "Total chunks",
        cell: ({ row }) => (
          <span className="tabular-nums text-[12.5px] text-slate-500">
            {row.original.chunks_total.toLocaleString()}
          </span>
        ),
      },
      {
        id: "versions",
        accessorKey: "versions",
        header: "Versions",
        cell: ({ row }) => (
          <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-slate-600">
            <Layers className="h-2.5 w-2.5" aria-hidden />
            {row.original.versions}
          </span>
        ),
      },
      {
        id: "latest_ingested_at",
        accessorKey: "latest_ingested_at",
        header: "Last ingested",
        cell: ({ row }) => (
          <span className="text-[12px] text-slate-500">
            {formatIngested(row.original.latest_ingested_at)}
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
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1 text-[11.5px] font-medium text-slate-600 transition-colors hover:border-red-300 hover:bg-red-50 hover:text-red-700"
            aria-label={`Delete ${row.original.source}`}
          >
            <Trash2 className="h-3 w-3" aria-hidden />
            Delete
          </button>
        ),
      },
    ],
    [],
  );

  // React Compiler intentionally skips memoising components that use
  // useReactTable because its API returns functions that aren't safe to
  // memoise. The warning is informational — disable per-call.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    globalFilterFn: (row, _columnId, filterValue: string) => {
      const needle = filterValue.trim().toLowerCase();
      if (!needle) return true;
      return row.original.source.toLowerCase().includes(needle);
    },
  });

  async function onConfirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteDocument(pendingDelete.source);
      setRows((prev) => prev.filter((d) => d.source !== pendingDelete.source));
      notify("success", `Deleted ${pendingDelete.source}`);
      setPendingDelete(null);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Delete failed";
      notify("error", message);
    } finally {
      setDeleting(false);
    }
  }

  async function runUpload(file: File) {
    if (uploading) return;
    if (!hasAcceptedExtension(file.name)) {
      notify(
        "error",
        `Unsupported file type. Accepted: ${ACCEPTED_EXTENSIONS.join(", ")}`,
      );
      return;
    }
    setUploading(true);
    try {
      const result = await uploadDocument(file);
      if (result.status === "ingested") {
        notify(
          "success",
          `Uploaded ${result.source} — ${result.chunks_created} chunk${
            result.chunks_created === 1 ? "" : "s"
          } · v${result.version}`,
        );
      } else {
        notify(
          "success",
          `${result.source} already on file — no changes (v${result.version})`,
        );
      }
      await load(true); // refresh the table
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  function onFileSelected(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    void runUpload(file);
    e.target.value = ""; // allow re-uploading the same filename
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    void runUpload(file);
  }

  const visibleRows = table.getRowModel().rows;
  const filtered = globalFilter.trim().length > 0;

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-5 py-6 sm:px-8 sm:py-8">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-[#9E6A0E]">
            Documents
          </p>
          <h1 className="mt-1.5 font-display text-[28px] font-semibold leading-tight tracking-tight text-[#0A1628]">
            Document management
          </h1>
          <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-slate-500">
            Every source indexed in the vector store. Drop superseded
            revisions or fully delete a source — chunks vanish from
            retrieval immediately.
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

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50/80 px-4 py-3 text-[12.5px] text-red-700"
        >
          {error}
        </div>
      )}

      {/* Upload */}
      <SectionCard
        title="Ingest a document"
        subtitle="Adds a new source to the corpus. Re-uploading the same content is idempotent — only changed bodies create new versions."
      >
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
            {uploading ? "Ingesting…" : "Drop a document here"}
          </p>
          <p className="mt-0.5 text-[11px] text-slate-500">
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
          <p className="mt-1.5 text-[10.5px] text-slate-400">
            Accepted: pdf, docx, txt, md, csv, xlsx, png/jpg/jpeg/tiff/bmp/webp ·
            max 50 MB
          </p>
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPT_ATTR}
            onChange={onFileSelected}
            className="hidden"
            disabled={uploading}
          />
        </div>
      </SectionCard>

      {/* Toolbar */}
      <div className="flex flex-col gap-2.5 rounded-xl border border-slate-200 bg-white p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative flex-1 max-w-md">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400"
            aria-hidden
          />
          <input
            type="search"
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            placeholder="Search by source…"
            className="w-full rounded-lg border border-slate-200 bg-white py-1.5 pl-7 pr-3 text-[12.5px] text-[#0A1628] placeholder:text-slate-400 focus:border-[#C9892A]/55 focus:outline-none focus:ring-2 focus:ring-[#C9892A]/15"
            aria-label="Search documents"
          />
        </div>
        <div className="text-[11.5px] text-slate-500">
          {loading
            ? "Loading…"
            : filtered
            ? `${visibleRows.length} of ${rows.length} sources`
            : `${rows.length} sources`}
        </div>
      </div>

      {/* Table — virtualised once 50+ sources are indexed so the page stays
          responsive even at corpus scale. The visible row count is small but
          the row sub-tree is moderately heavy (icon + version count etc.). */}
      <VirtualizedTable
        table={table}
        loading={loading}
        rowHeight={52}
        viewportClassName="max-h-[60vh]"
        animateRows={visibleRows.length < 60}
        emptyState={
          <div className="mx-auto max-w-sm">
            <FileText
              className="mx-auto h-7 w-7 text-slate-300"
              aria-hidden
            />
            <p className="mt-3 font-display text-[14px] font-semibold text-[#0A1628]">
              {filtered
                ? "No matching documents"
                : "No documents indexed yet"}
            </p>
            <p className="mt-1 text-[12px] text-slate-500">
              {filtered
                ? "Try a different search term."
                : "Sources land here when an admin uploads a file or ingests a URL."}
            </p>
          </div>
        }
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete document?"
        description={
          <>
            <p>
              This permanently removes every chunk for{" "}
              <span className="font-semibold text-[#0A1628]">
                {pendingDelete?.source}
              </span>{" "}
              from the vector store. Retrieval will stop returning this
              source immediately. This action cannot be undone.
            </p>
            {pendingDelete && pendingDelete.versions > 1 && (
              <p className="mt-2 text-slate-500">
                {pendingDelete.versions} versions ({pendingDelete.chunks_total}{" "}
                total chunks) will be removed.
              </p>
            )}
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

