import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuditRecords } from "../../api/queries";
import { Page } from "../../components/layout/Page";
import { Badge, StatusBadge } from "../../components/ui/Badge";
import { HashChip } from "../../components/ui/Mono";
import { TimeAgo } from "../../components/ui/Time";
import {
  EmptyState,
  ErrorState,
  SkeletonRows,
} from "../../components/ui/States";
import { cn } from "../../lib/format";

const PAGE_SIZE = 25;

/** The hash-chained log, newest first, each row linking into the chain view. */
export function AuditPage() {
  const [offset, setOffset] = useState(0);
  const records = useAuditRecords(PAGE_SIZE, offset);

  const total = records.data?.total ?? 0;
  const items = records.data?.items ?? [];

  return (
    <Page
      title="Audit"
      subtitle={`${total} records, hash-chained and Ed25519-signed`}
      actions={
        <Pager
          offset={offset}
          pageSize={PAGE_SIZE}
          total={total}
          onChange={setOffset}
        />
      }
    >
      {records.isPending ? (
        <SkeletonRows rows={8} />
      ) : records.isError ? (
        <ErrorState
          message={records.error.message}
          onRetry={() => void records.refetch()}
        />
      ) : items.length === 0 ? (
        <EmptyState
          title="The audit log is empty."
          hint="Every gate decision and human action lands here."
        />
      ) : (
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-edge text-left text-[11px] uppercase tracking-wide text-ink-faint">
              <th className="px-4 py-2 font-medium">#</th>
              <th className="px-2 py-2 font-medium">decision id</th>
              <th className="px-2 py-2 font-medium">actor</th>
              <th className="px-2 py-2 font-medium">effect</th>
              <th className="px-2 py-2 font-medium">human action</th>
              <th className="px-2 py-2 font-medium">record hash</th>
              <th className="px-4 py-2 text-right font-medium">when</th>
            </tr>
          </thead>
          <tbody>
            {items.map((record) => (
              <tr
                key={record.record_hash}
                className="border-b border-edge/60 transition-colors hover:bg-panel"
              >
                <td className="mono px-4 py-2 text-ink-faint">{record.index}</td>
                <td className="px-2 py-2">
                  <Link
                    to={`/audit/${record.decision_id}`}
                    className="mono text-[12px] text-accent hover:underline"
                  >
                    {record.decision_id.slice(0, 8)}…
                  </Link>
                </td>
                <td className="px-2 py-2 text-ink-dim">{record.actor}</td>
                <td className="px-2 py-2">
                  {typeof record.policy_result.effect === "string" ? (
                    <StatusBadge value={record.policy_result.effect} />
                  ) : (
                    <span className="text-ink-faint">&mdash;</span>
                  )}
                </td>
                <td className="px-2 py-2">
                  {record.human_action !== null &&
                  record.human_action !== undefined &&
                  typeof record.human_action.action === "string" ? (
                    <Badge tone="info">{record.human_action.action}</Badge>
                  ) : (
                    <span className="text-ink-faint">&mdash;</span>
                  )}
                </td>
                <td className="px-2 py-2">
                  <HashChip value={record.record_hash} />
                </td>
                <td className="px-4 py-2 text-right">
                  <TimeAgo value={record.ts} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Page>
  );
}

function Pager({
  offset,
  pageSize,
  total,
  onChange,
}: {
  offset: number;
  pageSize: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  const button = (enabled: boolean) =>
    cn(
      "rounded border border-edge px-2 py-0.5 text-[11px]",
      enabled
        ? "text-ink-dim hover:bg-panel-2 hover:text-ink"
        : "cursor-not-allowed text-ink-faint opacity-50",
    );
  return (
    <div className="flex items-center gap-2 text-[11px] text-ink-faint">
      <button
        type="button"
        disabled={offset === 0}
        className={button(offset > 0)}
        onClick={() => onChange(Math.max(0, offset - pageSize))}
      >
        newer
      </button>
      <span className="mono">
        {total === 0 ? "0" : `${offset + 1}–${Math.min(offset + pageSize, total)}`}{" "}
        of {total}
      </span>
      <button
        type="button"
        disabled={offset + pageSize >= total}
        className={button(offset + pageSize < total)}
        onClick={() => onChange(offset + pageSize)}
      >
        older
      </button>
    </div>
  );
}
