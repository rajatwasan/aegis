/**
 * The status color language, used identically on every screen:
 * green = allow/executed, amber = escalate/pending, red = deny/frozen/
 * rejected/expired/failed, blue = info/anchored.
 */
export type Tone = "ok" | "warn" | "danger" | "info" | "neutral";

export function toneFor(value: string | null | undefined): Tone {
  switch (value) {
    case "allow":
    case "executed":
    case "approved":
    case "finished":
      return "ok";
    case "escalate":
    case "pending":
    case "pending_approval":
    case "awaiting_approval":
    case "running":
      return "warn";
    case "deny":
    case "denied":
    case "rejected":
    case "expired":
    case "frozen":
    case "refused":
    case "failed":
      return "danger";
    case "anchored":
    case "info":
      return "info";
    default:
      return "neutral";
  }
}
