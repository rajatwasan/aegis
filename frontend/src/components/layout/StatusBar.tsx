import { useMetrics } from "../../api/queries";
import { useConnectionStatus } from "../../lib/EventsProvider";
import { Badge, Dot } from "../ui/Badge";
import { HashChip } from "../ui/Mono";
import { Skeleton } from "../ui/States";

/**
 * Always-visible operational truth: chain connection, event stream health,
 * last anchor, live pending count. Fed by /metrics and kept fresh by SSE.
 */
export function StatusBar() {
  const metrics = useMetrics();
  const streamStatus = useConnectionStatus();

  const chain = metrics.data?.chain;
  const anchor = metrics.data?.last_anchor;

  return (
    <header className="flex h-11 items-center gap-5 border-b border-edge bg-panel px-4">
      <div className="flex items-center gap-2" data-testid="chain-status">
        <Dot
          tone={chain?.connected ? "ok" : chain?.configured ? "danger" : "neutral"}
          pulse={chain?.connected}
        />
        <span className="text-xs text-ink-dim">
          {chain === undefined
            ? "chain"
            : chain.connected
              ? `chain ${chain.chain_id ?? ""}`
              : chain.configured
                ? "chain unreachable"
                : "chain not configured"}
        </span>
      </div>

      <div className="flex items-center gap-2" data-testid="stream-status">
        <Dot
          tone={streamStatus === "open" ? "ok" : "warn"}
          pulse={streamStatus !== "open"}
        />
        <span className="text-xs text-ink-dim">
          {streamStatus === "open" ? "live" : streamStatus}
        </span>
      </div>

      <div className="ml-auto flex items-center gap-5">
        <div className="flex items-center gap-2 text-xs text-ink-dim">
          <span>last anchor</span>
          {metrics.isPending ? (
            <Skeleton className="h-3 w-24" />
          ) : anchor ? (
            <span className="flex items-center gap-1.5 text-info">
              <span className="mono">#{anchor.batch_id}</span>
              <HashChip value={`0x${anchor.root}`} />
            </span>
          ) : (
            <span className="text-ink-faint">none</span>
          )}
        </div>

        <div className="flex items-center gap-2 text-xs text-ink-dim">
          <span>pending</span>
          {metrics.isPending ? (
            <Skeleton className="h-3 w-6" />
          ) : (
            <Badge
              tone={(metrics.data?.pending_count ?? 0) > 0 ? "warn" : "neutral"}
            >
              <span data-testid="pending-count">
                {metrics.data?.pending_count ?? 0}
              </span>
            </Badge>
          )}
        </div>
      </div>
    </header>
  );
}
