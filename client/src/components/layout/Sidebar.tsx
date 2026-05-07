import { NavLink } from "react-router-dom";

const items = [
  { to: "/app/projects", label: "GitHub Projects" },
  { to: "/app/runs", label: "Runs" },
];

export function Sidebar() {
  return (
    <aside className="surface-muted hidden h-fit w-72 shrink-0 p-4 lg:block">
      <div className="border-b border-line/80 px-2 pb-4">
        <p className="section-eyebrow">Workspace</p>
        <h2 className="mt-2 font-display text-3xl uppercase leading-none text-ink" style={{ fontWeight: 460 }}>
          Control
        </h2>
        <p className="mt-3 text-sm leading-6 text-muted">Move between registered repositories and long-running execution history.</p>
      </div>
      <nav className="mt-4 grid gap-2">
        {items.map((item) => {
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `rounded-2xl border px-4 py-4 text-base transition ${
                  isActive
                    ? "border-line bg-[#f7f3ee] text-ink"
                    : "border-transparent text-muted hover:border-line hover:bg-[#fbf8f5] hover:text-ink"
                }`
              }
            >
              {item.label}
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
}
