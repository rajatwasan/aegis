import { cn } from "../../lib/format";

/**
 * Where the approver pastes the bearer token the operator issued them. A
 * password field so the value is never shown after entry; stored client side
 * and sent only as an Authorization header (AGENTS.md R33).
 */
export function ApproverTokenField({
  value,
  onChange,
}: {
  value: string;
  onChange: (token: string) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-ink-dim">
      approver token
      <input
        type="password"
        autoComplete="off"
        value={value}
        placeholder="paste your approver token"
        aria-label="approver token"
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "w-48 rounded border border-edge bg-panel px-2 py-1 text-xs text-ink",
          "placeholder:text-ink-faint focus:border-edge-2 focus:outline-none",
        )}
      />
    </label>
  );
}
