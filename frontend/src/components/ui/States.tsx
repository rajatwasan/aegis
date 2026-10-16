import { cn } from "../../lib/format";

/** Loading / empty / error building blocks — every screen uses all three. */

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      data-testid="skeleton"
      className={cn("skeleton rounded", className ?? "h-4 w-full")}
      aria-hidden="true"
    />
  );
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-3" role="status" aria-label="loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-9" />
      ))}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center gap-1 px-6 py-14 text-center">
      <p className="text-ink-dim">{title}</p>
      {hint !== undefined && <p className="text-xs text-ink-faint">{hint}</p>}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="m-3 rounded border border-danger/30 bg-danger-dim px-4 py-3"
    >
      <p className="text-danger">{message}</p>
      {onRetry !== undefined && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded border border-danger/40 px-2 py-0.5 text-xs text-danger hover:bg-danger/10"
        >
          retry
        </button>
      )}
    </div>
  );
}
