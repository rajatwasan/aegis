import { cn } from "../../lib/format";
import { toneFor, type Tone } from "../../lib/tone";

const TONE_CLASSES: Record<Tone, string> = {
  ok: "bg-ok-dim text-ok border-ok/30",
  warn: "bg-warn-dim text-warn border-warn/30",
  danger: "bg-danger-dim text-danger border-danger/30",
  info: "bg-info-dim text-info border-info/30",
  neutral: "bg-panel-2 text-ink-dim border-edge",
};

export function Badge({
  tone = "neutral",
  children,
  className,
}: {
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-px",
        "text-[11px] font-medium uppercase tracking-wide leading-4",
        TONE_CLASSES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function StatusBadge({ value }: { value: string }) {
  return <Badge tone={toneFor(value)}>{value.replace(/_/g, " ")}</Badge>;
}

export function Dot({ tone, pulse }: { tone: Tone; pulse?: boolean }) {
  const colors: Record<Tone, string> = {
    ok: "bg-ok",
    warn: "bg-warn",
    danger: "bg-danger",
    info: "bg-info",
    neutral: "bg-ink-faint",
  };
  return (
    <span
      className={cn(
        "inline-block size-2 rounded-full",
        colors[tone],
        pulse && "pulse-dot",
      )}
      aria-hidden="true"
    />
  );
}
