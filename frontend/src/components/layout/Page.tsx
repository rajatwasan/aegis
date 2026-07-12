import type { ReactNode } from "react";

export function Page({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-baseline gap-3 border-b border-edge px-5 py-3">
        <h1 className="text-[15px] font-semibold tracking-tight">{title}</h1>
        {subtitle !== undefined && (
          <p className="text-xs text-ink-faint">{subtitle}</p>
        )}
        {actions !== undefined && <div className="ml-auto">{actions}</div>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
    </div>
  );
}
