import { useEffect, useState } from "react";
import {
  useApproveProposal,
  usePartyStatus,
  usePolicy,
  useProposal,
  useRejectProposal,
} from "../../api/queries";
import { asProposalRow, type ProposalRow } from "../../api/types";
import { Badge, StatusBadge } from "../../components/ui/Badge";
import { Amount, HashChip } from "../../components/ui/Mono";
import { Countdown, TimeAgo } from "../../components/ui/Time";
import { ErrorState, Skeleton } from "../../components/ui/States";
import { cn, operationName } from "../../lib/format";

/**
 * The decision surface: everything a guardian needs to act on one proposal —
 * the full payload, WHY it escalated (matched rules + policyHash), both
 * parties' on-chain standing, and approve/reject with a required comment.
 */
export function ProposalDrawer({
  decisionId,
  token,
  intent = null,
  onClose,
}: {
  decisionId: string;
  token: string;
  /** Set by the a/r shortcuts: focuses the comment and arms Enter-to-act. */
  intent?: "approve" | "reject" | null;
  onClose: () => void;
}) {
  const detail = useProposal(decisionId);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button
        type="button"
        aria-label="close drawer"
        onClick={onClose}
        className="flex-1 bg-black/50"
      />
      <aside
        role="dialog"
        aria-label="proposal detail"
        className="flex w-[30rem] max-w-full flex-col overflow-y-auto border-l border-edge bg-panel shadow-2xl"
      >
        {detail.isPending ? (
          <div className="space-y-3 p-5">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </div>
        ) : detail.isError ? (
          <ErrorState
            message={detail.error.message}
            onRetry={() => void detail.refetch()}
          />
        ) : (
          <DrawerBody
            row={detail.data}
            token={token}
            intent={intent}
            onClose={onClose}
          />
        )}
      </aside>
    </div>
  );
}

function DrawerBody({
  row,
  token,
  intent,
  onClose,
}: {
  row: ProposalRow;
  token: string;
  intent: "approve" | "reject" | null;
  onClose: () => void;
}) {
  const policyResult = row.proposal.policy_result;

  return (
    <>
      <header className="flex items-center gap-3 border-b border-edge px-5 py-4">
        <StatusBadge value={row.status} />
        <HashChip value={row.decision_id} head={8} tail={6} className="text-ink-dim" />
        <span className="ml-auto text-xs text-ink-dim">
          expires <Countdown expiresAt={row.expires_at} />
        </span>
      </header>

      <Section title="Proposal">
        <dl className="grid grid-cols-[7rem_1fr] gap-y-1.5 text-[13px]">
          <Field label="operation">
            <Badge tone="warn">{operationName(row.proposal.operation)}</Badge>
          </Field>
          <Field label="amount">
            <Amount value={row.proposal.amount} />
            <span className="ml-2 text-xs text-ink-faint">
              class {row.proposal.asset_class}
            </span>
          </Field>
          <Field label="token">
            <HashChip value={row.proposal.token} />
          </Field>
          <Field label="requester">
            <span className="mono text-ink-dim">
              {row.proposal.requester ?? "agent"}
            </span>
          </Field>
          <Field label="created">
            <TimeAgo value={row.created_at} />
          </Field>
        </dl>
      </Section>

      <Section title="Parties">
        <PartyLine label="from" address={row.proposal.from} />
        <PartyLine label="to" address={row.proposal.to} />
      </Section>

      <Section title="Policy decision">
        <div className="mb-2 flex items-center gap-2">
          <StatusBadge value={policyResult?.effect ?? "escalate"} />
          {policyResult?.policy_hash !== undefined && (
            <span className="text-xs text-ink-faint">
              policy <HashChip value={policyResult.policy_hash} />
            </span>
          )}
        </div>
        <MatchedRules ruleIds={policyResult?.matched_rules ?? []} />
      </Section>

      {row.approvals.length > 0 && (
        <Section title="Approvals so far">
          <p className="mb-2 text-xs text-warn">
            dual control: {row.approvals.length} of 2 recorded, awaiting a
            second approver
          </p>
          <ul className="space-y-1.5">
            {row.approvals.map((a) => (
              <li key={a.approver} className="flex items-baseline gap-2 text-[13px]">
                <span className="font-medium">{a.approver}</span>
                <span className="text-[11px] text-ink-faint">via {a.auth}</span>
                <span className="text-ink-dim">{a.comment}</span>
                <span className="ml-auto">
                  <TimeAgo value={a.ts} />
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {row.status === "pending" && (
        <ActionForm
          row={row}
          token={token}
          intent={intent}
          onClose={onClose}
        />
      )}
    </>
  );
}

function MatchedRules({ ruleIds }: { ruleIds: string[] }) {
  const policy = usePolicy();
  if (ruleIds.length === 0) {
    return <p className="text-xs text-ink-faint">no rules matched (policy default)</p>;
  }
  return (
    <ul className="space-y-1.5">
      {ruleIds.map((id) => {
        const rule = policy.data?.rules.find((r) => r.id === id);
        return (
          <li key={id} className="rounded border border-edge bg-panel-2 px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="mono text-[12px] text-ink">{id}</span>
              {rule !== undefined && <StatusBadge value={rule.effect} />}
            </div>
            <p className="mt-0.5 text-xs text-ink-dim">
              {rule?.condition ?? "condition unavailable"}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

function PartyLine({ label, address }: { label: string; address: string }) {
  const status = usePartyStatus(address);
  const data = status.data;
  return (
    <div className="flex items-center gap-2 py-1 text-[13px]">
      <span className="w-10 text-xs text-ink-faint">{label}</span>
      <HashChip value={address} />
      <span className="ml-auto flex items-center gap-1.5">
        {status.isPending ? (
          <Skeleton className="h-4 w-24" />
        ) : data === undefined || !data.known ? (
          <Badge tone="neutral">standing unknown</Badge>
        ) : (
          <>
            <Badge tone={data.compliant ? "ok" : "danger"}>
              {data.compliant ? "compliant" : "non-compliant"}
            </Badge>
            {data.frozen === true && <Badge tone="danger">frozen</Badge>}
          </>
        )}
      </span>
    </div>
  );
}

function ActionForm({
  row,
  token,
  intent,
  onClose,
}: {
  row: ProposalRow;
  token: string;
  intent: "approve" | "reject" | null;
  onClose: () => void;
}) {
  const approve = useApproveProposal();
  const reject = useRejectProposal();
  const [comment, setComment] = useState("");

  const busy = approve.isPending || reject.isPending;
  const disabled = busy || token.trim() === "" || comment.trim() === "";
  const error = approve.error ?? reject.error;

  const act = (action: "approve" | "reject") => {
    const mutation = action === "approve" ? approve : reject;
    mutation.mutate(
      { decisionId: row.decision_id, token: token.trim(), comment: comment.trim() },
      {
        onSuccess: (data) => {
          // dual control: the first approval leaves it pending for a second
          if (asProposalRow(data).status !== "pending") onClose();
        },
      },
    );
  };

  return (
    <div className="mt-auto border-t border-edge px-5 py-4">
      {error !== null && <ErrorState message={error.message} />}
      {token.trim() === "" && (
        <p className="mb-2 text-xs text-warn">
          paste your approver token above to act on proposals
        </p>
      )}
      <label className="block text-xs text-ink-dim" htmlFor="decision-comment">
        comment (required)
      </label>
      <textarea
        id="decision-comment"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        rows={2}
        autoFocus={intent !== null}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && intent !== null && !disabled) {
            e.preventDefault();
            act(intent);
          }
        }}
        placeholder="why you are approving or rejecting"
        className={cn(
          "mt-1 w-full rounded border border-edge bg-panel-2 px-2 py-1.5 text-[13px]",
          "placeholder:text-ink-faint focus:border-edge-2 focus:outline-none",
        )}
      />
      {intent !== null && (
        <p className="mt-1 text-[11px] text-ink-faint">
          enter &#9166; to {intent} &middot; shift+enter for a new line
        </p>
      )}
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={() => act("approve")}
          className={cn(
            "flex-1 rounded border border-ok/40 bg-ok-dim px-3 py-1.5 text-[13px] font-medium text-ok",
            "hover:bg-ok/15 disabled:cursor-not-allowed disabled:opacity-40",
          )}
        >
          {approve.isPending ? "approving…" : "Approve"}
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={() => act("reject")}
          className={cn(
            "flex-1 rounded border border-danger/40 bg-danger-dim px-3 py-1.5 text-[13px] font-medium text-danger",
            "hover:bg-danger/15 disabled:cursor-not-allowed disabled:opacity-40",
          )}
        >
          {reject.isPending ? "rejecting…" : "Reject"}
        </button>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-edge px-5 py-4">
      <h2 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink-faint">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-ink-faint">{label}</dt>
      <dd className="flex items-center">{children}</dd>
    </>
  );
}
