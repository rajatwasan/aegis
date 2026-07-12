import { NavLink, Outlet } from "react-router-dom";
import { cn } from "../../lib/format";
import { StatusBar } from "./StatusBar";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/approvals", label: "Approvals" },
  { to: "/activity", label: "Activity" },
  { to: "/audit", label: "Audit" },
  { to: "/policy", label: "Policy" },
  { to: "/console", label: "Console" },
];

export function Shell() {
  return (
    <div className="grid h-full grid-cols-[13rem_1fr]">
      <nav
        aria-label="primary"
        className="flex flex-col border-r border-edge bg-panel"
      >
        <div className="flex items-center gap-2.5 px-4 py-4">
          <span className="grid size-7 place-items-center rounded bg-accent-dim text-accent font-bold">
            Æ
          </span>
          <div className="leading-tight">
            <div className="font-semibold tracking-tight">Aegis</div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-ink-faint">
              guardian console
            </div>
          </div>
        </div>
        <ul className="mt-2 space-y-0.5 px-2">
          {NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "block rounded px-3 py-1.5 text-[13px] transition-colors",
                    isActive
                      ? "bg-panel-2 text-ink border-l-2 border-accent -ml-px"
                      : "text-ink-dim hover:bg-panel-2 hover:text-ink",
                  )
                }
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="mt-auto px-4 py-3 text-[10px] text-ink-faint">
          cryptographically enforced HITL
        </div>
      </nav>

      <div className="flex min-w-0 flex-col">
        <StatusBar />
        <main className="min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
