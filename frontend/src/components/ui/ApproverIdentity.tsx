import { useApproverMe } from "../../api/queries";
import { cn } from "../../lib/format";
import { Badge } from "./Badge";

/**
 * Sign in as an approver with the token `aegis approver add` printed. The
 * server says who the token belongs to (/approvers/me); the name shown here is
 * its answer, never something typed. A rejected token is said out loud, and
 * the approve and reject controls stay disabled until a token resolves (W2).
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
    </div>
  );
}
