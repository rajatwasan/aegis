import { useEffect, useState } from "react";
import { absoluteTime, countdown, relativeTime } from "../../lib/format";
import { cn } from "../../lib/format";

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** Relative time, absolute on hover. */
export function TimeAgo({ value }: { value: string | number }) {
  const now = useNow(10_000);
  return (
    <time title={absoluteTime(value)} className="text-ink-dim whitespace-nowrap">
      {relativeTime(value, now)}
    </time>
  );
}

/** Live TTL countdown against an epoch-seconds deadline. */
export function Countdown({ expiresAt }: { expiresAt: number }) {
  const now = useNow(1_000);
  const text = countdown(expiresAt, now);
  const remaining = expiresAt - now / 1000;
  const urgent = remaining > 0 && remaining < 60;
  return (
    <span
      title={absoluteTime(expiresAt)}
      className={cn(
        "mono tabular-nums",
        text === "expired" ? "text-danger" : urgent ? "text-warn" : "text-ink-dim",
      )}
    >
      {text}
    </span>
  );
}
