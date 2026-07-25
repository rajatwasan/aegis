import { cn, truncateMiddle } from "../../lib/format";

/**
 * A link out to a block explorer. Rendered only when the server supplied a
 * url — on a dev chain (anvil) there is nothing to link to, and a dead link
 * would imply the anchor is publicly verifiable when it is not.
 */
export function ExplorerLink({
  url,
  children,
  className,
}: {
  url: string | null | undefined;
  children: React.ReactNode;
  className?: string;
}) {
  if (url === null || url === undefined || url === "") return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer noopener"
      className={cn(
        "inline-flex items-center gap-1 rounded text-info underline decoration-info/40",
        "underline-offset-2 hover:decoration-info focus-visible:outline focus-visible:outline-1",
        className,
      )}
    >
      {children}
      <span aria-hidden="true">&#8599;</span>
    </a>
  );
}

/**
 * The canonical "here is the anchoring transaction" affordance: the truncated
 * tx hash, linked to the explorer. Falls back to a plain mono hash when the
 * chain has no explorer, so the hash is always visible/copyable somewhere.
 */
export function TxLink({
  txHash,
  txUrl,
  label = "tx",
}: {
  txHash: string | null | undefined;
  txUrl?: string | null;
  label?: string;
}) {
  if (txHash === null || txHash === undefined || txHash === "") return null;
  const short = truncateMiddle(txHash, 10, 8);
  if (txUrl === null || txUrl === undefined || txUrl === "") {
    return (
      <span className="text-xs text-ink-faint">
        {label} <span className="mono">{short}</span>
      </span>
    );
  }
  return (
    <ExplorerLink url={txUrl} className="text-xs">
      {label} <span className="mono">{short}</span>
    </ExplorerLink>
  );
}
