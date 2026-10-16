import { useApproverMe, usePairingCode } from "../../api/queries";
import { cn } from "../../lib/format";
import { Badge } from "./Badge";
import { Countdown } from "./Time";

/**
 * Sign in as an approver with the token `aegis approver add` printed. The
 * server says who the token belongs to (/approvers/me); the name shown here is
 * its answer, never something typed. A rejected token is said out loud, and
 * the approve and reject controls stay disabled until a token resolves (W2).
 *
 * A signed in approver can also pair a phone: the code minted here enrolls a
 * passkey on /guardian that is bound to this same approver id (W10).
 */
export function ApproverIdentity({
  token,
  onChange,
}: {
  token: string;
  onChange: (token: string) => void;
}) {
  const me = useApproverMe(token);

  return (
    <div className="flex items-center gap-2 text-xs text-ink-dim">
      <label className="flex items-center gap-2">
        approver token
        <input
          type="password"
          value={token}
          placeholder="paste token"
          autoComplete="off"
          onChange={(e) => onChange(e.target.value)}
          aria-label="approver token"
          className={cn(
            "w-44 rounded border border-edge bg-panel px-2 py-1 text-xs text-ink",
            "placeholder:text-ink-faint focus:border-edge-2 focus:outline-none",
          )}
        />
      </label>
      <span data-testid="approver-status">
        {token === "" ? (
          <Badge tone="neutral">not signed in</Badge>
        ) : me.isPending ? (
          <Badge tone="neutral">checking…</Badge>
        ) : me.isError ? (
          <Badge tone="danger">token rejected</Badge>
        ) : (
          <Badge tone="ok">{me.data.display_name}</Badge>
        )}
      </span>
      {me.data !== undefined && <PairPhone />}
    </div>
  );
}

function PairPhone() {
  const pairing = usePairingCode();

  if (pairing.data !== undefined) {
    return (
      <span
        data-testid="pairing-code"
        className="inline-flex items-center gap-2 rounded border border-edge bg-panel px-2 py-1"
      >
        <span className="text-ink-faint">on the phone, open /guardian and enter</span>
        <span
          data-testid="pairing-code-value"
          className="mono text-sm font-semibold tracking-[0.25em] text-ink"
        >
          {pairing.data.code}
        </span>
        <Countdown expiresAt={pairing.data.expires_at} />
        <button
          type="button"
          aria-label="dismiss pairing code"
          onClick={() => pairing.reset()}
          className="text-ink-faint hover:text-ink"
        >
          ×
        </button>
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        disabled={pairing.isPending}
        onClick={() => pairing.mutate()}
        className={cn(
          "rounded border border-edge bg-panel px-2 py-1 text-xs text-ink-dim",
          "hover:border-edge-2 hover:text-ink disabled:opacity-40",
        )}
      >
        pair phone
      </button>
      {pairing.isError && (
        <span role="alert" className="text-danger">
          {pairing.error.message}
        </span>
      )}
    </span>
  );
}
