import { Link } from "react-router-dom";
import { useAnchorRecords, useMetrics } from "../../api/queries";
import type { AnchorInfo, ChainStatus, Metrics } from "../../api/types";
import { Page } from "../../components/layout/Page";
import { Badge } from "../../components/ui/Badge";
import { ExplorerLink, TxLink } from "../../components/ui/ExplorerLink";
import { HashChip } from "../../components/ui/Mono";
import { ErrorState, Skeleton } from "../../components/ui/States";
import { cn, relativeTime } from "../../lib/format";
import type { Tone } from "../../lib/tone";

/** The landing view: the runtime's vital signs at a glance. */
export function DashboardPage() {
  const metrics = useMetrics();

  if (metrics.isError) {
    return (
      <Page title="Dashboard">
        <ErrorState
          message={metrics.error.message}
          onRetry={() => void metrics.refetch()}
        />
      </Page>
    );
  }

  const data = metrics.data;
  return (
    <Page title="Dashboard" subtitle="the runtime at a glance">
      <div className="space-y-5 p-5">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <StatCard
            label="total decisions"
            value={data?.total_decisions}
            hint="policy-gated proposals"
          />
          <StatCard
            label="escalation rate"
            value={
              data === undefined
                ? undefined
                : `${(data.escalation_rate * 100).toFixed(1)}%`
            }
            tone="warn"
            hint="sent to a human"
          />
          <StatCard
            label="denials"
            value={data?.counts_by_effect.deny ?? 0}
            tone="danger"
            hint="stopped dead by policy"
          />
          <StatCard
            label="pending"
            value={data?.pending_count}
            tone={(data?.pending_count ?? 0) > 0 ? "warn" : "neutral"}
            hint={
              (data?.pending_count ?? 0) > 0 ? (
                <Link to="/approvals" className="text-accent hover:underline">
                  review now &rarr;
                </Link>
              ) : (
                "queue clear"
              )
            }
          />
          {/* A past eval run, not a live count (AGENTS.md R13): label it and
              date it, and show "n/a" rather than a skeleton when no report exists. */}
          <StatCard
            label="injections blocked, last eval run"
            value={
              data === undefined
                ? undefined
                : data.injections
                  ? data.injections.blocked
                  : "n/a"
            }
            tone={data?.injections ? "ok" : "neutral"}
            hint={
              data?.injections
                ? `${data.injections.bypasses}/${data.injections.attacks} bypasses · run ${relativeTime(data.injections.generated_at)}`
                : "no eval report · run make evals"
            }
          />
        </div>

        <section className="rounded border border-edge bg-panel p-4">
          <h2 className="mb-3 text-[11px] font-medium uppercase tracking-wide text-ink-faint">
            Decisions by effect
          </h2>
          {data === undefined ? (
            <Skeleton className="h-8" />
          ) : (
            <EffectBar counts={data.counts_by_effect} />
          )}
        </section>

        <AnchorCard
          anchor={data?.last_anchor ?? null}
          chain={data?.chain}
          loading={data === undefined}
        />
      </div>
    </Page>
  );
}

/**
 * Anchoring, end to end: seal the unanchored records and then track the
 * resulting transaction on a block explorer. The explorer link is what makes
 * the audit log checkable by someone who does not trust this server, so when
 * the chain is a local dev chain we say so instead of implying otherwise.
 */
function AnchorCard({
  anchor,
  chain,
  loading,
}: {
  anchor: AnchorInfo | null;
  chain: ChainStatus | undefined;
  loading: boolean;
}) {
  const anchorNow = useAnchorRecords();
  // the POST answers with the batch it just sealed; /metrics catches up after
  const latest = anchorNow.data?.batch ?? anchor;
  const isPublic = chain?.public === true;

  return (
    <section className="rounded border border-edge bg-panel p-4" data-testid="anchor-card">
      <div className="mb-2 flex items-center gap-3">
        <h2 className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">
          Anchoring
        </h2>
        {chain !== undefined && (
          <Badge tone={isPublic ? "info" : "neutral"}>
            {`${chain.chain_name ?? `chain ${chain.chain_id ?? "?"}`}${
              isPublic ? "" : " · local"
            }`}
          </Badge>
        )}
        <button
          type="button"
          onClick={() => anchorNow.mutate()}
          disabled={anchorNow.isPending}
          className={cn(
            "ml-auto rounded border border-info/40 bg-info-dim px-3 py-1 text-[13px]",
            "font-medium text-info hover:bg-info/15",
            "disabled:cursor-not-allowed disabled:opacity-40",
          )}
        >
          {anchorNow.isPending ? "anchoring…" : "Anchor now"}
        </button>
      </div>

      {anchorNow.isError && (
        <p className="mb-2 text-[13px] text-danger">{anchorNow.error.message}</p>
      )}
      {anchorNow.data?.anchored === false && (
        <p className="mb-2 text-xs text-ink-faint">
          Nothing new to anchor — every record is already sealed.
        </p>
      )}

      {loading ? (
        <Skeleton className="h-5 w-64" />
      ) : latest ? (
        <div className="flex flex-wrap items-center gap-3 text-[13px]">
          <Badge tone="info">batch #{latest.batch_id}</Badge>
          <span className="text-ink-dim">
            root <HashChip value={`0x${latest.root}`} />
          </span>
          <TxLink txHash={latest.tx_hash} txUrl={latest.tx_url} />
          {latest.block_number !== null && latest.block_number !== undefined && (
            <span className="text-xs text-ink-faint">
              block <span className="mono">{latest.block_number}</span>
            </span>
          )}
          <span className="text-xs text-ink-faint">
            {latest.record_count} records sealed
          </span>
          {latest.tx_url === null && latest.tx_hash !== null && (
            <span className="text-xs text-ink-faint">
              (dev chain — no public explorer)
            </span>
          )}
          <ExplorerLink url={latest.anchor_url} className="text-xs">
            AuditAnchor contract
          </ExplorerLink>
        </div>
      ) : (
        <p className="text-[13px] text-ink-faint">
          Nothing anchored yet — press Anchor now to seal the current records.
        </p>
      )}
    </section>
  );
}

/** Decisions by effect, in the status color language, with counts inline. */
function EffectBar({ counts }: { counts: Metrics["counts_by_effect"] }) {
  const segments = [
    { key: "allow", tone: "bg-ok", text: "text-ok", count: counts.allow ?? 0 },
    { key: "escalate", tone: "bg-warn", text: "text-warn", count: counts.escalate ?? 0 },
    { key: "deny", tone: "bg-danger", text: "text-danger", count: counts.deny ?? 0 },
  ];
  const total = segments.reduce((sum, s) => sum + s.count, 0);
  if (total === 0) {
    return <p className="text-[13px] text-ink-faint">No decisions yet.</p>;
  }
  return (
    <div data-testid="effect-bar">
      <div className="flex h-3 overflow-hidden rounded-full bg-panel-2">
        {segments.map(
          (s) =>
            s.count > 0 && (
              <div
                key={s.key}
                className={s.tone}
                style={{ width: `${(s.count / total) * 100}%` }}
                role="img"
                aria-label={`${s.key}: ${s.count}`}
              />
            ),
        )}
      </div>
      <div className="mt-2 flex gap-4 text-xs">
        {segments.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5">
            <span className={cn("size-2 rounded-full", s.tone)} aria-hidden="true" />
            <span className={s.text}>{s.key}</span>
            <span className="mono text-ink-dim">{s.count}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  tone = "neutral",
  hint,
}: {
  label: string;
  value: number | string | undefined;
  tone?: Tone;
  hint?: React.ReactNode;
}) {
  const valueColor: Record<Tone, string> = {
    ok: "text-ok",
    warn: "text-warn",
    danger: "text-danger",
    info: "text-info",
    neutral: "text-ink",
  };
  return (
    <div className="rounded border border-edge bg-panel px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-ink-faint">
        {label}
      </div>
      {value === undefined ? (
        <Skeleton className="mt-1 h-7 w-16" />
      ) : (
        <div className={cn("mono mt-0.5 text-2xl font-semibold", valueColor[tone])}>
          {value}
        </div>
      )}
      {hint !== undefined && (
        <div className="mt-0.5 text-xs text-ink-faint">{hint}</div>
      )}
    </div>
  );
}
