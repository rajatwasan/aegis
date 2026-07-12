import { Link } from "react-router-dom";
import { useMetrics } from "../../api/queries";
import type { Metrics } from "../../api/types";
import { Page } from "../../components/layout/Page";
import { Badge } from "../../components/ui/Badge";
import { HashChip } from "../../components/ui/Mono";
import { ErrorState, Skeleton } from "../../components/ui/States";
import { cn } from "../../lib/format";
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
          <StatCard
            label="injections blocked"
            value={data?.injections?.blocked}
            tone="ok"
            hint={
              data?.injections
                ? `${data.injections.bypasses}/${data.injections.attacks} bypasses in evals`
                : "run make evals"
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

        <section className="rounded border border-edge bg-panel p-4">
          <h2 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink-faint">
            Last anchor
          </h2>
          {data === undefined ? (
            <Skeleton className="h-5 w-64" />
          ) : data.last_anchor ? (
            <div className="flex flex-wrap items-center gap-3 text-[13px]">
              <Badge tone="info">batch #{data.last_anchor.batch_id}</Badge>
              <span className="text-ink-dim">
                root <HashChip value={`0x${data.last_anchor.root}`} />
              </span>
              {data.last_anchor.tx_hash !== null &&
                data.last_anchor.tx_hash !== undefined && (
                  <span className="text-ink-dim">
                    tx <HashChip value={withHexPrefix(data.last_anchor.tx_hash)} />
                  </span>
                )}
              <span className="text-xs text-ink-faint">
                {data.last_anchor.record_count} records sealed
              </span>
            </div>
          ) : (
            <p className="text-[13px] text-ink-faint">
              Nothing anchored yet — run the demo or anchor from the CLI.
            </p>
          )}
        </section>
      </div>
    </Page>
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

function withHexPrefix(value: string): string {
  return value.startsWith("0x") ? value : `0x${value}`;
}
