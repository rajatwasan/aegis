import { useCallback, useState } from "react";
import {
  useApproveProposal,
  useCannedInstructions,
  usePendingProposals,
  useRejectProposal,
  useRunAgent,
} from "../../api/queries";
import type { ProposalRow } from "../../api/types";
import { Page } from "../../components/layout/Page";
import { ApproverIdentity } from "../../components/ui/ApproverIdentity";
import { Badge, Dot, StatusBadge } from "../../components/ui/Badge";
import { Amount, HashChip } from "../../components/ui/Mono";
import { Countdown } from "../../components/ui/Time";
import { EmptyState, ErrorState } from "../../components/ui/States";
import { useBusSubscription } from "../../lib/EventsProvider";
import type { BusEvent } from "../../lib/events";
import { useApproverToken, useResolvedApprover } from "../../lib/approver";
import { cn, operationName } from "../../lib/format";
import type { Tone } from "../../lib/tone";

/**
 * The full HITL loop on one screen: instruct the agent on the left and watch
 * its steps stream in; anything the policy escalates appears on the right
 * with inline approve/reject, and the resumed execution streams back in.
 */
export function ConsolePage() {
  const canned = useCannedInstructions();
  const run = useRunAgent();
  const [instruction, setInstruction] = useState("");
  const [steps, setSteps] = useState<BusEvent[]>([]);
  const [token, setToken] = useApproverToken();
  const { canAct } = useResolvedApprover(token);

  useBusSubscription(
    useCallback((event: BusEvent) => {
      if (event.type === "agent.step") {
        setSteps((prior) => [...prior, event]);
      }
    }, []),
  );

  const start = (text: string) => {
    const trimmed = text.trim();
    if (trimmed === "") return;
    setInstruction(trimmed);
    setSteps([]);
    run.mutate(trimmed);
  };

  return (
    <Page
      title="Console"
      subtitle="instruct the agent, watch the gate act"
      actions={<ApproverIdentity token={token} onChange={setToken} />}
    >
      <div className="border-b border-edge px-5 py-4">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            start(instruction);
          }}
        >
          <input
            type="text"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder="instruction for the agent"
            aria-label="instruction"
            className={cn(
              "mono flex-1 rounded border border-edge bg-panel px-3 py-1.5 text-[13px]",
              "placeholder:text-ink-faint focus:border-edge-2 focus:outline-none",
            )}
          />
          <button
            type="submit"
            disabled={run.isPending || instruction.trim() === ""}
            className={cn(
              "rounded border border-accent/40 bg-accent-dim px-4 py-1.5 text-[13px] font-medium text-accent",
              "hover:bg-accent/15 disabled:cursor-not-allowed disabled:opacity-40",
            )}
          >
            Run
          </button>
        </form>
        <div className="mt-2 flex flex-wrap gap-2">
          {(canned.data?.instructions ?? []).map((chip) => (
            <button
              key={chip.instruction}
              type="button"
              title={chip.description}
              onClick={() => start(chip.instruction)}
              disabled={run.isPending}
              className={cn(
                "rounded-full border border-edge bg-panel px-3 py-1 text-xs text-ink-dim",
                "hover:border-edge-2 hover:text-ink disabled:opacity-40",
              )}
            >
              {chip.instruction}
            </button>
          ))}
        </div>
        {run.isError && <ErrorState message={run.error.message} />}
      </div>

      <div className="grid min-h-0 flex-1 lg:grid-cols-2">
        <section
          aria-label="agent steps"
          className="min-h-64 overflow-y-auto border-b border-edge lg:border-b-0 lg:border-r"
        >
          <SectionHeader>Agent steps</SectionHeader>
          {steps.length === 0 ? (
            <EmptyState
              title="No run yet."
              hint="Fire a canned instruction to watch the agent work."
            />
          ) : (
            <ol className="px-5 pb-4" data-testid="console-steps">
              {steps.map((event) => (
                <StepRow key={event.seq} event={event} />
              ))}
            </ol>
          )}
        </section>

        <section aria-label="escalations" className="min-h-64 overflow-y-auto">
          <SectionHeader>Escalations</SectionHeader>
          <EscalationsPanel canAct={canAct} />
        </section>
      </div>
    </Page>
  );
}

function StepRow({ event }: { event: BusEvent }) {
  const phase = String(event.data.phase ?? "");
  const detail = describeStep(event);
  const tone: Tone =
    phase === "failed"
      ? "danger"
      : phase === "awaiting_approval"
        ? "warn"
        : phase === "finished"
          ? "ok"
          : "info";
  return (
    <li className="relative border-l border-edge pb-1 pl-4 last:border-transparent">
      <span className="absolute -left-1 top-2">
        <Dot tone={tone} pulse={phase === "awaiting_approval"} />
      </span>
      <div className="flex flex-wrap items-baseline gap-x-2 py-1 text-[13px]">
        <span className="mono text-[12px] text-ink">{phase}</span>
        <span className="text-xs text-ink-dim">{detail}</span>
      </div>
    </li>
  );
}

function describeStep(event: BusEvent): string {
  const data = event.data;
  const phase = String(data.phase ?? "");
  if (phase === "started") return `${String(data.steps_planned)} steps planned`;
  if (phase === "awaiting_approval")
    return `escalated — decision ${String(data.decision_id).slice(0, 8)}… awaits a human`;
  if (phase === "approval_resolved")
    return `human ${String(data.status)} — resuming`;
  if (phase === "failed") return String(data.error ?? "run failed");
  if (phase === "finished") return "run complete";
  if (phase === "node") {
    const node = String(data.node ?? "");
    if (node === "supervisor") {
      const action = data.action as {
        tool?: string;
        args?: Record<string, unknown>;
      } | null;
      if (action && typeof action.tool === "string") {
        const amount = action.args?.amount;
        return `plans ${action.tool}${typeof amount === "number" ? ` (${amount.toLocaleString("en-US")})` : ""}`;
      }
      return "supervisor: done";
    }
    const result = data.result as
      { effect?: string; status?: string; tx_hash?: string } | undefined;
    if (result !== undefined) {
      const parts = [
        result.effect !== undefined && `policy: ${result.effect}`,
        result.status !== undefined && `status: ${result.status}`,
        result.tx_hash !== undefined && "tx confirmed",
      ].filter(Boolean);
      return `${node} — ${parts.join(", ")}`;
    }
    return node;
  }
  return "";
}

function EscalationsPanel({ canAct }: { canAct: boolean }) {
  const pending = usePendingProposals();
  const rows = [...(pending.data ?? [])].sort(
    (a, b) => b.created_at - a.created_at,
  );

  if (pending.isError) {
    return (
      <ErrorState
        message={pending.error.message}
        onRetry={() => void pending.refetch()}
      />
    );
  }
  if (rows.length === 0) {
    return (
      <EmptyState
        title="Nothing escalated."
        hint="Large or unusual proposals appear here for sign-off."
      />
    );
  }
  return (
    <ul className="space-y-3 px-5 pb-4">
      {rows.map((row) => (
        <EscalationCard key={row.decision_id} row={row} canAct={canAct} />
      ))}
    </ul>
  );
}

function EscalationCard({
  row,
  canAct,
}: {
  row: ProposalRow;
  canAct: boolean;
}) {
  const approve = useApproveProposal();
  const reject = useRejectProposal();
  const [comment, setComment] = useState("");

  const busy = approve.isPending || reject.isPending;
  const disabled = busy || !canAct || comment.trim() === "";
  const error = approve.error ?? reject.error;

  const act = (action: "approve" | "reject") => {
    (action === "approve" ? approve : reject).mutate({
      decisionId: row.decision_id,
      comment: comment.trim(),
    });
  };

  return (
    <li
      data-testid={`escalation-${row.decision_id}`}
      className="rounded border border-warn/30 bg-panel p-3"
    >
      <div className="flex items-center gap-2 text-[13px]">
        <StatusBadge value="escalate" />
        <Badge tone="warn">{operationName(row.proposal.operation)}</Badge>
        <Amount value={row.proposal.amount} />
        <span className="ml-auto text-xs">
          <Countdown expiresAt={row.expires_at} />
        </span>
      </div>
      <div className="mt-1.5 flex items-center gap-1.5 text-[13px] text-ink-dim">
        <HashChip value={row.proposal.from} />
        <span aria-hidden="true" className="text-ink-faint">
          &rarr;
        </span>
        <HashChip value={row.proposal.to} />
      </div>
      {error !== null && (
        <p role="alert" className="mt-2 text-xs text-danger">
          {error.message}
        </p>
      )}
      <div className="mt-2 flex gap-2">
        <input
          type="text"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="comment (required)"
          aria-label={`comment for ${row.decision_id}`}
          className="min-w-0 flex-1 rounded border border-edge bg-panel-2 px-2 py-1 text-xs placeholder:text-ink-faint focus:border-edge-2 focus:outline-none"
        />
        <button
          type="button"
          disabled={disabled}
          onClick={() => act("approve")}
          className="rounded border border-ok/40 bg-ok-dim px-3 py-1 text-xs font-medium text-ok hover:bg-ok/15 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Approve
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={() => act("reject")}
          className="rounded border border-danger/40 bg-danger-dim px-3 py-1 text-xs font-medium text-danger hover:bg-danger/15 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Reject
        </button>
      </div>
    </li>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="px-5 pb-2 pt-4 text-[11px] font-medium uppercase tracking-wide text-ink-faint">
      {children}
    </h2>
  );
}
