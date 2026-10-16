import { usePolicy } from "../../api/queries";
import { Page } from "../../components/layout/Page";
import { StatusBadge } from "../../components/ui/Badge";
import { HashChip } from "../../components/ui/Mono";
import { ErrorState, SkeletonRows } from "../../components/ui/States";

/** The active policy: what the gate enforces, in rule order, plus raw yaml. */
export function PolicyPage() {
  const policy = usePolicy();

  if (policy.isPending) {
    return (
      <Page title="Policy">
        <SkeletonRows rows={4} />
      </Page>
    );
  }
  if (policy.isError) {
    return (
      <Page title="Policy">
        <ErrorState
          message={policy.error.message}
          onRetry={() => void policy.refetch()}
        />
      </Page>
    );
  }

  const data = policy.data;
  return (
    <Page
      title="Policy"
      subtitle={`version ${data.version} — first match wins, default ${data.default}`}
      actions={
        <span className="text-xs text-ink-dim">
          hash <HashChip value={data.policy_hash} />
        </span>
      }
    >
      <div className="grid gap-5 p-5 lg:grid-cols-[1fr_22rem]">
        <section>
          <h2 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink-faint">
            Rules (evaluated in order)
          </h2>
          <ol className="space-y-2">
            {data.rules.map((rule, i) => (
              <li
                key={rule.id}
                className="flex items-start gap-3 rounded border border-edge bg-panel px-3 py-2.5"
              >
                <span className="mono mt-0.5 text-xs text-ink-faint">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="mono text-[12px]">{rule.id}</span>
                    <StatusBadge value={rule.effect} />
                  </div>
                  <p className="mt-0.5 text-xs text-ink-dim">
                    {rule.condition}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          {data.allowlist.length > 0 && (
            <>
              <h2 className="mb-2 mt-5 text-[11px] font-medium uppercase tracking-wide text-ink-faint">
                Allowlist
              </h2>
              <ul className="space-y-1">
                {data.allowlist.map((address) => (
                  <li key={address}>
                    <HashChip value={address} head={10} tail={8} />
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
        <section>
          <h2 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink-faint">
            Raw yaml (hashed into every authorization)
          </h2>
          <pre className="mono overflow-x-auto rounded border border-edge bg-panel p-3 text-xs leading-relaxed text-ink-dim">
            {data.yaml}
          </pre>
        </section>
      </div>
    </Page>
  );
}
