import { useState } from "react";
import { useDecisions } from "../../api/queries";
import type { DecisionItem } from "../../api/types";
import { Page } from "../../components/layout/Page";
import { Badge, Dot, StatusBadge } from "../../components/ui/Badge";
import { Amount, HashChip } from "../../components/ui/Mono";
import { TimeAgo } from "../../components/ui/Time";
import {
  EmptyState,
  ErrorState,
  SkeletonRows,
} from "../../components/ui/States";
import { useFeed } from "../../lib/EventsProvider";
import type { BusEvent } from "../../lib/events";
import { cn, operationName, OPERATION_NAMES } from "../../lib/format";
import { toneFor } from "../../lib/tone";

const EFFECTS = ["allow", "escalate", "deny"] as const;
type EffectFilter = (typeof EFFECTS)[number] | "all";
type OpFilter = number | "all";

/** One row of the chronological feed: a gate decision or a live agent step. */
type Entry =
  | { kind: "decision"; key: string; ts: string; decision: DecisionItem }
  | { kind: "step"; key: string; ts: string; event: BusEvent };

/**
 * The control-room ticker: every policy decision (backfilled from /decisions,
 * kept fresh by decision.recorded invalidations) interleaved with live
 * agent.step events, effect-colored, filterable by effect and operation.
 */
export function ActivityPage() {
  const decisions = useDecisions(100, 0);
  const feed = useFeed();
  const [effect, setEffect] = useState<EffectFilter>("all");
  const [operation, setOperation] = useState<OpFilter>("all");

  const entries: Entry[] = [
    ...(decisions.data?.items ?? []).map(
      (decision): Entry => ({
        kind: "decision",
        key: `decision-${decision.decision_id}-${decision.ts}`,
        ts: decision.ts,
        decision,
      }),
    ),
    ...feed.events
      .filter((event) => event.type === "agent.step")
      .map(
        (event): Entry => ({
          kind: "step",
          key: `step-${event.seq}`,
          ts: event.ts,
          event,
        }),
      ),
  ]
    .filter((entry) => {
      if (entry.kind === "step") {
        // steps carry no effect/operation: any specific filter hides them
        return effect === "all" && operation === "all";
      }
      const d = entry.decision;
      if (effect !== "all" && d.effect !== effect) return false;
      if (operation !== "all" && d.proposal.operation !== operation) return false;
      return true;
    })
    .sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts));

  return (
    <Page
      title="Activity"
      subtitle="decisions and agent steps, as they happen"
      actions={
        <div className="flex items-center gap-4">
          <FilterGroup
            label="effect"
            value={effect}
            options={EFFECTS.map((e) => ({ value: e, label: e }))}
            onChange={setEffect}
          />
          <FilterGroup
            label="operation"
            value={operation}
            options={Object.entries(OPERATION_NAMES).map(([op, name]) => ({
              value: Number(op),
              label: name,
            }))}
            onChange={setOperation}
          />
        </div>
      }
    >
      {decisions.isPending ? (
        <SkeletonRows rows={6} />
      ) : decisions.isError ? (
        <ErrorState
          message={decisions.error.message}
          onRetry={() => void decisions.refetch()}
        />
      ) : entries.length === 0 ? (
        <EmptyState
          title="Nothing to show."
          hint="Run an instruction from the Console to see the gate at work."
        />
      ) : (
        <ol className="px-5 py-3" data-testid="activity-feed">
          {entries.map((entry) => (
            <li
              key={entry.key}
              className="relative border-l border-edge pb-1 pl-5 last:border-transparent"
            >
              <span className="absolute -left-1 top-2">
                <Dot tone={entryTone(entry)} />
              </span>
              {entry.kind === "decision" ? (
                <DecisionLine decision={entry.decision} />
              ) : (
                <StepLine event={entry.event} />
              )}
            </li>
          ))}
        </ol>
      )}
    </Page>
  );
}

function entryTone(entry: Entry) {
  if (entry.kind === "decision") return toneFor(entry.decision.effect);
  const phase = String(entry.event.data.phase ?? "");
  if (phase === "awaiting_approval") return toneFor("pending");
  if (phase === "failed") return toneFor("failed");
  return "info" as const;
}

function DecisionLine({ decision }: { decision: DecisionItem }) {
  const proposal = decision.proposal;
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 py-1.5 text-[13px]">
      <StatusBadge value={decision.effect} />
      <span className="text-ink-dim">
        {operationName(Number(proposal.operation ?? 0))}
      </span>
      {typeof proposal.amount === "number" && <Amount value={proposal.amount} />}
      {typeof proposal.from === "string" && typeof proposal.to === "string" && (
        <span className="flex items-center gap-1 text-ink-dim">
          <HashChip value={proposal.from} />
          <span aria-hidden="true" className="text-ink-faint">
            &rarr;
          </span>
          <HashChip value={proposal.to} />
        </span>
      )}
      {decision.status !== null && decision.status !== undefined && (
        <StatusBadge value={decision.status} />
      )}
      {(decision.matched_rules ?? []).length > 0 && (
        <span className="mono text-[11px] text-ink-faint">
          {(decision.matched_rules ?? []).join(", ")}
        </span>
      )}
      {decision.tx_hash !== null && decision.tx_hash !== undefined && (
        <span className="text-xs text-ink-faint">
          tx <HashChip value={withHexPrefix(decision.tx_hash)} />
        </span>
      )}
      <span className="ml-auto">
        <TimeAgo value={decision.ts} />
      </span>
    </div>
  );
}

function StepLine({ event }: { event: BusEvent }) {
  const phase = String(event.data.phase ?? "step");
  const instruction = String(event.data.instruction ?? "");
  const node = typeof event.data.node === "string" ? event.data.node : null;
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 py-1.5 text-[13px]">
      <Badge tone={toneFor(phase) === "neutral" ? "info" : toneFor(phase)}>
        agent
      </Badge>
      <span className={cn("mono text-[12px]", "text-ink-dim")}>
        {phase}
        {node !== null && ` · ${node}`}
      </span>
      <span className="truncate text-xs text-ink-faint">{instruction}</span>
      <span className="ml-auto">
        <TimeAgo value={event.ts} />
      </span>
    </div>
  );
}

function FilterGroup<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T | "all";
  options: Array<{ value: T; label: string }>;
  onChange: (value: T | "all") => void;
}) {
  const chip = (active: boolean) =>
    cn(
      "rounded px-2 py-0.5 text-[11px] transition-colors",
      active
        ? "bg-panel-2 text-ink border border-edge-2"
        : "text-ink-dim border border-transparent hover:text-ink",
    );
  return (
    <div
      role="group"
      aria-label={`filter by ${label}`}
      className="flex items-center gap-1"
    >
      <span className="mr-1 text-[11px] uppercase tracking-wide text-ink-faint">
        {label}
      </span>
      <button
        type="button"
        className={chip(value === "all")}
        onClick={() => onChange("all")}
      >
        all
      </button>
      {options.map((option) => (
        <button
          key={String(option.value)}
          type="button"
          className={chip(value === option.value)}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function withHexPrefix(value: string): string {
  return value.startsWith("0x") ? value : `0x${value}`;
}
