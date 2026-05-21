"use client";

import {
  type Row,
  type Table as ReactTable,
  flexRender,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { motion } from "framer-motion";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { type ReactNode, useRef } from "react";

import { cn } from "../../lib/cn";

interface VirtualizedTableProps<T> {
  table: ReactTable<T>;
  /** Estimated row height for the virtualizer (in pixels). */
  rowHeight?: number;
  /** Max viewport height; rows scroll inside this. */
  viewportClassName?: string;
  /** Rendered when there are zero rows. */
  emptyState?: ReactNode;
  /** Optional className applied to each <tr>. */
  rowClassName?: string;
  /** Loading state — renders the same skeleton the legacy tables used. */
  loading?: boolean;
  /** Fade-in animation on row enter — set false to disable when many rows. */
  animateRows?: boolean;
  /** Optional renderer for a row click — exposed because TanStack handles
   *  per-cell click handlers via the column def, not the row. */
  onRowClick?: (row: Row<T>) => void;
}

/**
 * Virtualised table for the admin surfaces.
 *
 * Wraps the TanStack table primitives the Documents + Evaluation pages
 * already use and adds row virtualisation via `@tanstack/react-virtual`.
 * Designed to be a drop-in for the inline `<table>` markup those pages
 * had: same header, same sort handles, same row treatment — just only
 * the visible rows mount.
 *
 * Why TanStack Virtual rather than react-window: TanStack Virtual is
 * already a sibling of `@tanstack/react-table` (one ecosystem, shared
 * primitives) and supports dynamic row heights cleanly via
 * `measureElement`. We use a fixed `rowHeight` estimate for the legal
 * tables since their cells are intentionally uniform, which gives the
 * smoothest scroll behaviour.
 */
export function VirtualizedTable<T>({
  table,
  rowHeight = 52,
  viewportClassName,
  emptyState,
  rowClassName,
  loading,
  animateRows = true,
  onRowClick,
}: VirtualizedTableProps<T>) {
  const parentRef = useRef<HTMLDivElement>(null);
  const rows = table.getRowModel().rows;

  // The virtualiser only needs to know how many rows + roughly how tall.
  // overscan keeps a small buffer rendered above/below the viewport so a
  // fast flick doesn't show blank rows.
  // eslint-disable-next-line react-hooks/incompatible-library
  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
    overscan: 8,
  });

  const totalSize = rowVirtualizer.getTotalSize();
  const virtualRows = rowVirtualizer.getVirtualItems();
  const paddingTop = virtualRows.length > 0 ? virtualRows[0].start : 0;
  const paddingBottom =
    virtualRows.length > 0
      ? totalSize - virtualRows[virtualRows.length - 1].end
      : 0;

  return (
    <div
      ref={parentRef}
      className={cn(
        "overflow-auto rounded-lg border border-slate-200/70 bg-white",
        viewportClassName ?? "max-h-[640px]",
      )}
    >
      <table className="w-full text-left">
        <thead className="sticky top-0 z-10 bg-slate-50/95 backdrop-blur">
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => {
                const sortable = header.column.getCanSort();
                const sort = header.column.getIsSorted();
                return (
                  <th
                    key={header.id}
                    scope="col"
                    className="border-b border-slate-200/70 px-4 py-2 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-slate-500"
                  >
                    {sortable ? (
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        className="group inline-flex items-center gap-1 hover:text-[#0A1628]"
                      >
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                        <span
                          className={cn(
                            "text-slate-300 group-hover:text-slate-500",
                            (sort === "asc" || sort === "desc") &&
                              "text-[#9E6A0E]",
                          )}
                        >
                          {sort === "asc" ? (
                            <ArrowUp className="h-2.5 w-2.5" aria-hidden />
                          ) : sort === "desc" ? (
                            <ArrowDown className="h-2.5 w-2.5" aria-hidden />
                          ) : (
                            <ArrowUpDown className="h-2.5 w-2.5" aria-hidden />
                          )}
                        </span>
                      </button>
                    ) : (
                      flexRender(
                        header.column.columnDef.header,
                        header.getContext(),
                      )
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>

        <tbody>
          {loading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <tr
                key={`sk-${i}`}
                className="border-b border-slate-100/80 last:border-b-0"
              >
                {table.getAllColumns().map((col) => (
                  <td key={col.id} className="px-4 py-2.5">
                    <div className="lf-shimmer h-3.5 w-full max-w-[140px] rounded bg-slate-100" />
                  </td>
                ))}
              </tr>
            ))
          ) : rows.length === 0 ? (
            <tr>
              <td
                colSpan={table.getAllColumns().length}
                className="px-4 py-12 text-center"
              >
                {emptyState}
              </td>
            </tr>
          ) : (
            <>
              {paddingTop > 0 && (
                <tr aria-hidden>
                  <td
                    colSpan={table.getAllColumns().length}
                    style={{ height: paddingTop }}
                  />
                </tr>
              )}
              {virtualRows.map((virtualRow) => {
                const row = rows[virtualRow.index];
                const RowTag = animateRows ? motion.tr : "tr";
                const rowAnimateProps = animateRows
                  ? {
                      initial: { opacity: 0, y: 4 },
                      animate: { opacity: 1, y: 0 },
                      transition: {
                        duration: 0.18,
                        delay: Math.min(virtualRow.index * 0.008, 0.12),
                        ease: [0.16, 1, 0.3, 1] as [
                          number,
                          number,
                          number,
                          number,
                        ],
                      },
                    }
                  : {};
                return (
                  <RowTag
                    key={row.id}
                    data-index={virtualRow.index}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    className={cn(
                      "border-b border-slate-100/80 last:border-b-0 transition-colors hover:bg-slate-50/40",
                      onRowClick && "cursor-pointer",
                      rowClassName,
                    )}
                    {...(rowAnimateProps as Record<string, unknown>)}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-4 py-2.5 align-middle">
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext(),
                        )}
                      </td>
                    ))}
                  </RowTag>
                );
              })}
              {paddingBottom > 0 && (
                <tr aria-hidden>
                  <td
                    colSpan={table.getAllColumns().length}
                    style={{ height: paddingBottom }}
                  />
                </tr>
              )}
            </>
          )}
        </tbody>
      </table>
    </div>
  );
}
