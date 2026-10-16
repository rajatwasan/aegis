import { useCallback, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { usePendingProposals } from "../../api/queries";
import type { ProposalRow } from "../../api/types";
import { Amount, HashChip } from "../../components/ui/Mono";
import { Badge } from "../../components/ui/Badge";
import { Countdown } from "../../components/ui/Time";
import { EmptyState, ErrorState, SkeletonRows } from "../../components/ui/States";
import { useConnectionStatus, useBusSubscription } from "../../lib/EventsProvider";
import type { BusEvent } from "../../lib/events";
import { cn, operationName } from "../../lib/format";
import { useNow } from "../../lib/useNow";
import { notifyNewProposal, primeAudio } from "./notify";
import { describeWebAuthnError, loadPairing, type PairingState } from "./pairing";
import { requestAssertion, useGuardianDecide, usePairDevice } from "./queries";

/**
 * The phone screen: pair once with a passkey, then approve or reject
 * escalations with Face ID. Mobile-first, single column, thumb-sized
 * targets; the passkey signs the exact decision server-side.
 */
export function GuardianPage() {
  const [pairing, setPairing] = useState<PairingState | null>(loadPairing);

  const onBusEvent = useCallback((event: BusEvent) => {
    if (event.type === "proposal.created") notifyNewProposal();
  }, []);
  useBusSubscription(onBusEvent);

  return (
    <div
      onPointerDown={primeAudio}
      className="mx-auto flex min-h-full w-full max-w-md flex-col px-4 pb-10 pt-5"
    >
      <Header paired={pairing !== null} />
      {pairing === null ? (
        <PairScreen onPaired={setPairing} />
      ) : (
        <Queue pairing={pairing} />
      )}
    </div>
  );
}

function Header({ paired }: { paired: boolean }) {
  const status = useConnectionStatus();
  return (
    <header className="mb-5 flex items-center gap-2.5">
      <span className="grid size-8 place-items-center rounded bg-accent-dim font-bold text-accent">
        Æ
      </span>
      <div className="leading-tight">
        <div className="font-semibold tracking-tight">Aegis Guardian</div>
        <div className="text-[10px] uppercase tracking-[0.2em] text-ink-faint">
          {paired ? "passkey paired" : "not paired"}
        </div>
      </div>
      <span
        title={`stream ${status}`}
        className={cn(
          "ml-auto size-2 rounded-full",
          status === "open" ? "pulse-dot bg-ok" : "bg-warn",
        )}
      />
    </header>
  );
}

// ------------------------------------------------------------------ pairing

function PairScreen({ onPaired }: { onPaired: (state: PairingState) => void }) {
  const [code, setCode] = useState("");
  const pair = usePairDevice();
  const ready = code.length === 6 && !pair.isPending;

  return (
    <section className="flex flex-1 flex-col justify-center gap-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">
          Pair this phone
        </h1>
        <p className="text-sm text-ink-dim">
          Sign in on the console and press &ldquo;pair phone&rdquo;, enter the
          6-character code here, then confirm with Face ID. This device&apos;s
          passkey will sign every decision you make, as that approver.
        </p>
      </div>
      <input
        value={code}
        onChange={(e) =>
          setCode(e.target.value.toUpperCase().replace(/\s/g, "").slice(0, 6))
        }
        aria-label="pairing code"
        placeholder="ABC123"
        autoCapitalize="characters"
        autoComplete="one-time-code"
        autoCorrect="off"
        spellCheck={false}
        className={cn(
          "mono h-16 w-full rounded-xl border border-edge bg-panel text-center",
          "text-3xl tracking-[0.35em] text-ink placeholder:text-ink-faint",
          "focus:border-edge-2 focus:outline-none",
        )}
      />
      <button
        type="button"
        disabled={!ready}
        onClick={() => pair.mutate(code, { onSuccess: onPaired })}
        className={cn(
          "h-14 w-full rounded-xl bg-accent-dim text-lg font-semibold text-accent",
          "active:bg-accent/25 disabled:opacity-40",
        )}
      >
        {pair.isPending ? "Waiting for passkey…" : "Pair with passkey"}
      </button>
      {pair.isError && (
        <ErrorState message={describeWebAuthnError(pair.error)} />
      )}
    </section>
  );
}

// -------------------------------------------------------------------- queue

function Queue({ pairing }: { pairing: PairingState }) {
  const proposals = usePendingProposals();
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (toast === null) return;
    const id = window.setTimeout(() => setToast(null), 6_000);
    return () => window.clearTimeout(id);
  }, [toast]);

  const rows = [...(proposals.data ?? [])].sort(
    (a, b) => b.created_at - a.created_at,
  );

  return (
    <section aria-label="pending escalations" className="flex flex-col gap-4">
      {toast !== null && (
        <div
          role="alert"
          className="rounded-xl border border-danger/40 bg-danger-dim px-4 py-3 text-sm text-danger"
        >
          {toast}
        </div>
      )}

      {proposals.isPending ? (
        <SkeletonRows rows={3} />
      ) : proposals.isError ? (
        <ErrorState
          message={proposals.error.message}
          onRetry={() => void proposals.refetch()}
        />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No proposals waiting."
          hint="You'll feel a buzz when the agent escalates."
        />
      ) : (
        rows.map((row) => (
          <ProposalCard key={row.decision_id} row={row} onError={setToast} />
        ))
      )}

      <p
        data-testid="guardian-identity"
        className="mt-2 text-center text-[11px] text-ink-faint"
      >
        signing as {pairing.displayName} (passkey{" "}
        <span className="mono">{pairing.credentialId.slice(0, 8)}</span>)
      </p>
    </section>
  );
}

function ProposalCard({
  row,
  onError,
}: {
  row: ProposalRow;
  onError: (message: string) => void;
}) {
  const queryClient = useQueryClient();
  const decide = useGuardianDecide();
  const [comment, setComment] = useState("");
  const [confirming, setConfirming] = useState(false);
  const now = useNow(1_000);
  const expired = now / 1000 >= row.expires_at;
  const busy = confirming || decide.isPending;

  const act = async (action: "approve" | "reject") => {
    setConfirming(true);
    try {
      // Face ID happens here; the card stays visible until it succeeds.
      const credential = await requestAssertion(row.decision_id);
      decide.mutate(
        { decisionId: row.decision_id, action, comment, credential },
        { onError: (error) => onError(error.message) },
      );
    } catch (error) {
      onError(describeWebAuthnError(error));
    } finally {
      setConfirming(false);
    }
  };

  return (
    <article
      data-testid={`guardian-${row.decision_id}`}
      onAnimationEnd={
        expired
          ? () =>
              void queryClient.invalidateQueries({
                queryKey: ["proposals", "pending"],
              })
          : undefined
      }
      className={cn(
        "rounded-2xl border border-edge bg-panel p-4",
        expired && "decay-out pointer-events-none",
      )}
    >
      <div className="flex items-center justify-between">
        <Badge tone="warn">{operationName(row.proposal.operation)}</Badge>
        <Countdown expiresAt={row.expires_at} />
      </div>

      <div className="mt-3 text-3xl font-semibold">
        <Amount value={row.proposal.amount} />
      </div>
      <div className="mt-1 flex items-center gap-1.5 text-sm text-ink-dim">
        to
        <HashChip value={row.proposal.to} className="text-ink" />
      </div>

      <input
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        aria-label={`comment for ${row.decision_id}`}
        placeholder="comment (optional)"
        className={cn(
          "mt-4 w-full rounded-lg border border-edge bg-panel-2 px-3 py-2.5",
          "text-sm text-ink placeholder:text-ink-faint",
          "focus:border-edge-2 focus:outline-none",
        )}
      />

      <div className="mt-3 grid grid-cols-2 gap-3">
        <button
          type="button"
          disabled={busy || expired}
          onClick={() => void act("approve")}
          className={cn(
            "h-14 rounded-xl border border-ok/30 bg-ok-dim text-lg font-semibold text-ok",
            "active:bg-ok/20 disabled:opacity-40",
          )}
        >
          Approve
        </button>
        <button
          type="button"
          disabled={busy || expired}
          onClick={() => void act("reject")}
          className={cn(
            "h-14 rounded-xl border border-danger/30 bg-danger-dim text-lg font-semibold text-danger",
            "active:bg-danger/20 disabled:opacity-40",
          )}
        >
          Reject
        </button>
      </div>
      {busy && (
        <p className="mt-2 text-center text-xs text-ink-dim" role="status">
          Confirm with Face ID&hellip;
        </p>
      )}
    </article>
  );
}
