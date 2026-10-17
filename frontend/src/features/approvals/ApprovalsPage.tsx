import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { usePendingProposals } from "../../api/queries";
import type { ProposalRow } from "../../api/types";
import { Page } from "../../components/layout/Page";
import { Badge } from "../../components/ui/Badge";
import { Amount, HashChip } from "../../components/ui/Mono";
import { Countdown, TimeAgo } from "../../components/ui/Time";
import {
  EmptyState,
  ErrorState,
  SkeletonRows,
} from "../../components/ui/States";
import { ApproverTokenField } from "../../components/ui/ApproverTokenField";
import { useApproverToken } from "../../lib/approverToken";
import { cn, operationName } from "../../lib/format";
import { useNow } from "../../lib/useNow";
import { ProposalDrawer } from "./ProposalDrawer";

/**
 * The core screen: every pending escalation, newest first, live via SSE
 * (proposal.* events invalidate the query). Rows decay out as their TTL
 * dies; clicking one opens the decision drawer.
 */
export function ApprovalsPage() {
  const proposals = usePendingProposals();
  const [selected, setSelected] = useState<string | null>(null);
  const [intent, setIntent] = useState<"approve" | "reject" | null>(null);
  const [token, setToken] = useApproverToken();

  const rows = [...(proposals.data ?? [])].sort(
    (a, b) => b.created_at - a.created_at,
  );

  const open = (decisionId: string, withIntent: "approve" | "reject" | null) => {
    setSelected(decisionId);
    setIntent(withIntent);
  };

  /** j/k walk the queue, a/r jump straight into acting on the focused row. */
  const onTableKeyDown = (e: React.KeyboardEvent<HTMLTableSectionElement>) => {
    const focused = (e.target as HTMLElement).closest("tr");
    if (focused === null) return;
    if (e.key === "j" || e.key === "k") {
      e.preventDefault();
      const sibling =
        e.key === "j"
          ? focused.nextElementSibling
          : focused.previousElementSibling;
      if (sibling instanceof HTMLElement) sibling.focus();
    } else if (e.key === "a" || e.key === "r") {
      e.preventDefault();
      const decisionId = focused.dataset.testid?.replace("proposal-", "");
      if (decisionId !== undefined) {
        open(decisionId, e.key === "a" ? "approve" : "reject");
      }
    }
  };

  return (
    <Page
      title="Approvals"
      subtitle="escalated proposals awaiting a guardian"
      actions={<ApproverTokenField value={token} onChange={setToken} />}
    >
      {proposals.isPending ? (
        <SkeletonRows rows={5} />
      ) : proposals.isError ? (
        <ErrorState
          message={proposals.error.message}
          onRetry={() => void proposals.refetch()}
        />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No proposals waiting."
          hint="Escalations from the agent appear here in real time."
        />
      ) : (
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-edge text-left text-[11px] uppercase tracking-wide text-ink-faint">
              <th className="px-4 py-2 font-medium">operation</th>
              <th className="px-2 py-2 font-medium">route</th>
              <th className="px-2 py-2 text-right font-medium">amount</th>
              <th className="px-2 py-2 font-medium">class</th>
              <th className="px-2 py-2 font-medium">expires in</th>
              <th className="px-2 py-2 font-medium">approvals</th>
              <th className="px-4 py-2 text-right font-medium">created</th>
            </tr>
          </thead>
          <tbody onKeyDown={onTableKeyDown}>
            {rows.map((row) => (
              <Row
                key={row.decision_id}
                row={row}
                onOpen={() => open(row.decision_id, null)}
              />
            ))}
          </tbody>
        </table>
      )}

      {selected !== null && (
        <ProposalDrawer
          decisionId={selected}
          token={token}
          intent={intent}
          onClose={() => setSelected(null)}
        />
      )}
    </Page>
  );
}

function Row({ row, onOpen }: { row: ProposalRow; onOpen: () => void }) {
  const queryClient = useQueryClient();
  const now = useNow(1_000);
  const expired = now / 1000 >= row.expires_at;

  return (
    <tr
      data-testid={`proposal-${row.decision_id}`}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      onAnimationEnd={
        expired
          ? () =>
              void queryClient.invalidateQueries({
                queryKey: ["proposals", "pending"],
              })
          : undefined
      }
      tabIndex={0}
      className={cn(
        "cursor-pointer border-b border-edge/60 transition-colors",
        "hover:bg-panel focus-visible:bg-panel",
        expired && "decay-out pointer-events-none",
      )}
    >
      <td className="px-4 py-2.5">
        <Badge tone="warn">{operationName(row.proposal.operation)}</Badge>
      </td>
      <td className="px-2 py-2.5 whitespace-nowrap">
        <span className="flex items-center gap-1.5">
          <HashChip value={row.proposal.from} />
          <span aria-hidden="true" className="text-ink-faint">
            &rarr;
          </span>
          <HashChip value={row.proposal.to} />
        </span>
      </td>
      <td className="px-2 py-2.5 text-right">
        <Amount value={row.proposal.amount} />
      </td>
      <td className="px-2 py-2.5">
        <span className="mono text-ink-dim">{row.proposal.asset_class}</span>
      </td>
      <td className="px-2 py-2.5">
        <Countdown expiresAt={row.expires_at} />
      </td>
      <td className="px-2 py-2.5">
        {row.approvals.length > 0 ? (
          <Badge tone="warn">{row.approvals.length} of 2</Badge>
        ) : (
          <span className="text-ink-faint">&mdash;</span>
        )}
      </td>
      <td className="px-4 py-2.5 text-right">
        <TimeAgo value={row.created_at} />
      </td>
    </tr>
  );
}
