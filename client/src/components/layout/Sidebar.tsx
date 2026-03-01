import { NavLink } from "react-router-dom";

const items = [
  { to: "/app/projects", label: "GitHub Projects" },
  { to: "/app/runs", label: "Runs" },
];

export function Sidebar() {
  return (
    <aside className="surface-muted hidden h-fit w-64 shrink-0 p-4 lg:block">
      <nav className="grid gap-2">
        {items.map((item) => {
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `rounded-2xl border px-4 py-4 text-base font-semibold transition ${
                  isActive ? "border-accent/20 bg-accent-50/70 text-accent-800" : "border-transparent text-ink hover:border-line hover:bg-white"
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
