import { useState } from "react";
import { cn, truncateMiddle } from "../../lib/format";

/**
 * A hash/address/id: JetBrains Mono, middle-truncated, click-to-copy, full
 * value in the tooltip. Everything hex in the console renders through this.
 */
export function HashChip({
  value,
  head = 6,
  tail = 4,
  className,
}: {
  value: string;
  head?: number;
  tail?: number;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    void navigator.clipboard?.writeText(value).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    });
  };

  return (
    <button
      type="button"
      onClick={copy}
      title={value}
      aria-label={`copy ${value}`}
      className={cn(
        "mono cursor-copy rounded px-0.5 text-left transition-colors",
        copied ? "text-accent" : "hover:text-ink",
        className,
      )}
    >
      {copied ? "copied" : truncateMiddle(value, head, tail)}
    </button>
  );
}

export function Amount({ value }: { value: number | string }) {
  const n = typeof value === "string" ? Number(value) : value;
  return (
    <span className="mono tabular-nums">
      {Number.isFinite(n) ? n.toLocaleString("en-US") : String(value)}
    </span>
  );
}
