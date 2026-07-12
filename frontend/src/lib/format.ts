/** Formatting helpers shared by every screen. */

/** 0x1234...abcd — hashes and addresses always truncate in the middle. */
export function truncateMiddle(value: string, head = 6, tail = 4): string {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}...${value.slice(-tail)}`;
}

export function formatAmount(value: number | string): string {
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return String(value);
  return n.toLocaleString("en-US");
}

/** Seconds/minutes/hours ago; timestamps always pair this with an absolute title. */
export function relativeTime(iso: string | number, now: number = Date.now()): string {
  const then = typeof iso === "number" ? iso * 1000 : Date.parse(iso);
  if (Number.isNaN(then)) return "unknown";
  const delta = Math.max(0, Math.round((now - then) / 1000));
  if (delta < 5) return "just now";
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

export function absoluteTime(iso: string | number): string {
  const then = typeof iso === "number" ? new Date(iso * 1000) : new Date(iso);
  return then.toISOString().replace("T", " ").replace(/\.\d+.*$/, " UTC");
}

/** mm:ss (or h:mm:ss) until an epoch-seconds deadline; negative -> "expired". */
export function countdown(expiresAtSeconds: number, now: number = Date.now()): string {
  const remaining = Math.floor(expiresAtSeconds - now / 1000);
  if (remaining <= 0) return "expired";
  const h = Math.floor(remaining / 3600);
  const m = Math.floor((remaining % 3600) / 60);
  const s = remaining % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export const OPERATION_NAMES: Record<number, string> = {
  1: "transfer",
  2: "mint",
  3: "burn",
  4: "freeze",
};

export function operationName(op: number): string {
  return OPERATION_NAMES[op] ?? `op ${op}`;
}

/** Tiny class-joiner (no external dep). */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
