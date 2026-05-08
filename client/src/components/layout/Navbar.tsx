import { Link, NavLink, useLocation } from "react-router-dom";

import { Button } from "../ui/Button";
import { useAuth } from "../../hooks/useAuth";
import { useToast } from "../../hooks/useToast";

const mobileItems = [
  { to: "/app/projects", label: "GitHub Projects" },
  { to: "/app/runs", label: "Runs" },
];

export function Navbar() {
  const location = useLocation();
  const { signOut, userEmail } = useAuth();
  const { notify } = useToast();
  const isDetailWorkspaceRoute = location.pathname.includes("/generated-tests") || location.pathname.includes("/analysis");

  async function handleLogout() {
    try {
      await signOut();
      notify({ title: "Signed out", description: "Your workspace session has ended.", tone: "success" });
    } catch (err) {
      notify({
        title: "Logout failed",
        description: err instanceof Error ? err.message : "Unable to close the session.",
        tone: "error",
      });
    }
  }

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-white/95 backdrop-blur-sm">
      <div className="page-shell flex h-20 items-center justify-between gap-4">
        <div className="flex items-center gap-6">
          <Link to="/app/projects" className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-line bg-[#f7f3ee] text-sm font-display uppercase tracking-[0.12em] text-ink">
              AT
            </div>
            <div>
              <p className="m-0 font-display text-sm uppercase tracking-[0.12em] text-ink">ASTAP</p>
              <p className="m-0 text-xs text-muted">GitHub project delivery</p>
            </div>
          </Link>
          <nav className="hidden items-center gap-1 md:flex">
            <NavLink
              to="/app/projects"
              className={({ isActive }) =>
                `rounded-lg border px-4 py-2 text-sm ${isActive ? "border-line bg-[#f7f3ee] text-ink" : "border-transparent text-muted hover:border-line hover:text-ink"}`
              }
            >
              GitHub Projects
            </NavLink>
            <NavLink
              to="/app/runs"
              className={({ isActive }) =>
                `rounded-lg border px-4 py-2 text-sm ${isActive ? "border-line bg-[#f7f3ee] text-ink" : "border-transparent text-muted hover:border-line hover:text-ink"}`
              }
            >
              Runs
            </NavLink>
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden rounded-2xl border border-line px-4 py-2 text-right md:block">
            <p className="m-0 text-xs uppercase tracking-[0.16em] text-muted">Signed in</p>
            <p className="m-0 text-sm text-ink">{userEmail ?? "Unknown user"}</p>
          </div>
          <Button variant="ghost" onClick={() => void handleLogout()}>
            Logout
          </Button>
        </div>
      </div>
      {isDetailWorkspaceRoute ? null : (
        <div className="page-shell flex gap-2 overflow-x-auto pb-4 md:hidden">
          {mobileItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-lg border px-4 py-2 text-sm ${
                  isActive ? "border-line bg-[#f7f3ee] text-ink" : "border-line bg-transparent text-muted"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      )}
    </header>
  );
}
