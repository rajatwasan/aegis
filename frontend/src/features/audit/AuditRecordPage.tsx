import { Link, useParams } from "react-router-dom";
import { useAuditRecord, useVerifyDecision } from "../../api/queries";
import {
  asHumanPresence,
  type AuditRecordItem,
  type VerifyResponse,
} from "../../api/types";
import { Page } from "../../components/layout/Page";
import { Badge } from "../../components/ui/Badge";
import { ExplorerLink, TxLink } from "../../components/ui/ExplorerLink";
import { HumanPresenceBadge } from "../../components/ui/HumanPresence";
import { HashChip } from "../../components/ui/Mono";
import { ErrorState, Skeleton } from "../../components/ui/States";
import { cn, relativeTime } from "../../lib/format";

/**
 * One record in its chain neighborhood: canonical JSON, the
 * prev_hash -> record_hash links around it, the signature, and one-click
 * cryptographic verification against the on-chain Merkle root.
 */
export function AuditRecordPage() {
  const { decisionId } = useParams<{ decisionId: string }>();
  const detail = useAuditRecord(decisionId ?? null);
  const verify = useVerifyDecision();

  if (detail.isPending) {
    return (
      <Page title="Audit record">
        <div className="space-y-3 p-5">
          <Skeleton className="h-6 w-1/2" />
          <Skeleton className="h-40" />
        </div>
      </Page>
    );
  }
  if (detail.isError) {
    return (
      <Page title="Audit record">
        <ErrorState
          message={detail.error.message}
          onRetry={() => void detail.refetch()}
        />
      </Page>
    );
  }

  const { record, neighbors, total } = detail.data;
  const presence = asHumanPresence(record.human_presence);

  return (
    <Page
      title="Audit record"
      subtitle={`#${record.index} of ${total} in the chain`}
      actions={
        <div className="flex items-center gap-3">
          <Link to="/audit" className="text-xs text-ink-dim hover:text-ink">
            &larr; all records
          </Link>
          <button
            type="button"
            onClick={() => verify.mutate(record.decision_id)}
            disabled={verify.isPending}
            className={cn(
              "rounded border border-info/40 bg-info-dim px-3 py-1 text-[13px] font-medium text-info",
              "hover:bg-info/15 disabled:cursor-not-allowed disabled:opacity-40",
            )}
          >
            {verify.isPending ? "verifying…" : "Verify against chain"}
          </button>
        </div>
      }
    >
      <div className="grid gap-5 p-5 xl:grid-cols-[minmax(0,1fr)_26rem]">
        <div className="min-w-0 space-y-5">
          {verify.isError && <ErrorState message={verify.error.message} />}
          {verify.data !== undefined && <VerifyPanel result={verify.data} />}

          {presence !== null && <HumanPresenceBadge presence={presence} />}

          <section>
            <SectionTitle>Chain neighborhood</SectionTitle>
            <ChainView neighbors={neighbors} selected={record.record_hash} />
          </section>

          <section>
            <SectionTitle>Canonical record</SectionTitle>
            <pre className="mono overflow-x-auto rounded border border-edge bg-panel p-3 text-xs leading-relaxed text-ink-dim">
              {JSON.stringify(sortKeys(record), null, 2)}
            </pre>
          </section>
        </div>

        <aside className="space-y-3">
          <SectionTitle>Integrity fields</SectionTitle>
          <HashField label="prev_hash" value={record.prev_hash} />
          <HashField label="record_hash" value={record.record_hash} />
          <HashField label="signature (Ed25519)" value={record.signature} />
        </aside>
      </div>
    </Page>
  );
}

/** The surrounding slice of the log with prev->hash links drawn between rows. */
function ChainView({
  neighbors,
  selected,
}: {
  neighbors: AuditRecordItem[];
  selected: string;
}) {
  return (
    <ol data-testid="chain-view" className="space-y-0">
      {neighbors.map((record, i) => {
        const previous = neighbors[i - 1];
        const linked =
          previous !== undefined && record.prev_hash === previous.record_hash;
        return (
          <li key={record.record_hash}>
            {i > 0 && (
              <div
                className={cn(
                  "ml-6 flex items-center gap-2 py-0.5 text-[11px]",
                  linked ? "text-ok" : "text-ink-faint",
                )}
              >
                <span aria-hidden="true">&darr;</span>
                <span className="mono">prev_hash</span>
                {linked && <span>links</span>}
              </div>
            )}
            <div
              className={cn(
                "flex items-center gap-3 rounded border px-3 py-2",
                record.record_hash === selected
                  ? "border-accent/50 bg-panel-2"
                  : "border-edge bg-panel",
              )}
            >
              <span className="mono text-xs text-ink-faint">
                #{record.index}
              </span>
              <Link
                to={`/audit/${record.decision_id}`}
                className="mono text-[12px] text-accent hover:underline"
              >
                {record.decision_id.slice(0, 8)}…
              </Link>
              <span className="text-xs text-ink-dim">{record.actor}</span>
              <span className="ml-auto text-xs text-ink-faint">
                <HashChip value={record.record_hash} />
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function VerifyPanel({ result }: { result: VerifyResponse }) {
  const ok = result.PROOF_OK;
  // where this record's root actually landed on-chain — the link a third
  // party follows to check the root themselves
  const anchor = result.anchor;
  return (
    <section
      data-testid="verify-panel"
      className={cn(
        "rounded border p-4",
        ok ? "border-ok/40 bg-ok-dim/40" : "border-danger/40 bg-danger-dim/40",
      )}
    >
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={cn(
            "rounded border px-3 py-1 text-lg font-bold tracking-wide",
            ok
              ? "border-ok/50 bg-ok-dim text-ok"
              : "border-danger/50 bg-danger-dim text-danger",
          )}
        >
          {ok ? "PROOF OK" : "PROOF FAIL"}
        </span>
        {result.batch_id !== null && result.batch_id !== undefined && (
          <Badge tone="info">anchor batch #{result.batch_id}</Badge>
        )}
        {typeof result.reason === "string" && (
          <span className="text-[13px] text-danger">{result.reason}</span>
        )}
      </div>

      {anchor !== null && anchor !== undefined && (
        <div
          data-testid="anchor-provenance"
          className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-faint"
        >
          <span>
            anchored on{" "}
            <span className="text-ink-dim">{anchor.chain_name}</span>
          </span>
          {anchor.block_number !== null &&
            anchor.block_number !== undefined && (
              <span>
                block{" "}
                <span className="mono text-ink-dim">{anchor.block_number}</span>
              </span>
            )}
          {typeof anchor.anchored_at === "string" && (
            <span title={anchor.anchored_at}>
              {relativeTime(anchor.anchored_at)}
            </span>
          )}
          <TxLink
            txHash={anchor.tx_hash}
            txUrl={anchor.tx_url}
            label="anchor tx"
          />
          <ExplorerLink url={anchor.anchor_url}>
            AuditAnchor contract
          </ExplorerLink>
        </div>
      )}

      {result.merkle_path !== null && result.merkle_path !== undefined && (
        <div className="mt-3">
          <SectionTitle>Merkle path (leaf &rarr; root)</SectionTitle>
          <ol className="space-y-1">
            {result.merkle_path.map((sibling, i) => (
              <li key={sibling} className="flex items-center gap-2 text-xs">
                <span className="mono w-14 text-ink-faint">level {i}</span>
                <HashChip value={sibling} head={10} tail={8} />
              </li>
            ))}
          </ol>
        </div>
      )}

      <dl className="mt-3 grid grid-cols-[8rem_1fr] gap-y-1 text-xs">
        {result.local_root !== null && result.local_root !== undefined && (
          <>
            <dt className="text-ink-faint">local root</dt>
            <dd>
              <HashChip value={result.local_root} head={10} tail={8} />
            </dd>
          </>
        )}
        {result.onchain_root !== null && result.onchain_root !== undefined && (
          <>
            <dt className="text-ink-faint">on-chain root</dt>
            <dd className="flex items-center gap-2">
              <HashChip value={result.onchain_root} head={10} tail={8} />
              <Badge tone={ok ? "ok" : "danger"}>
                {ok ? "roots match" : "mismatch"}
              </Badge>
            </dd>
          </>
        )}
      </dl>
    </section>
  );
}

function HashField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-edge bg-panel px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-ink-faint">
        {label}
      </div>
      <HashChip value={value} head={16} tail={12} className="text-[12px]" />
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink-faint">
      {children}
    </h2>
  );
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([k, v]) => [k, sortKeys(v)]),
    );
  }
  return value;
}
