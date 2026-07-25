import type { HumanPresence } from "../../api/types";
import { truncateMiddle } from "../../lib/format";
import { Badge } from "./Badge";

/**
 * Proof-of-human marker: this decision carries a passkey assertion that was
 * verified at decide time and is hash-chained into the audit record.
 */
export function HumanPresenceBadge({ presence }: { presence: HumanPresence }) {
  return (
    <span
      data-testid="human-presence"
      className="inline-flex items-center gap-2"
    >
      <Badge tone="ok">human presence: passkey verified</Badge>
      <span className="mono text-xs text-ink-dim" title={presence.credential_id}>
        {truncateMiddle(presence.credential_id, 8, 4)}
      </span>
    </span>
  );
}
