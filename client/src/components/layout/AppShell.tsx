import { Outlet, useLocation } from "react-router-dom";

import { Navbar } from "./Navbar";
import { Sidebar } from "./Sidebar";

export function AppShell() {
  const location = useLocation();
  const isDetailWorkspaceRoute =
    location.pathname.includes("/generated-tests") ||
    location.pathname.includes("/analysis") ||
    location.pathname.includes("/execution");

  return (
    <div className="min-h-screen bg-canvas">
      <Navbar />
      <div className={isDetailWorkspaceRoute ? "flex px-0 py-4" : "page-shell flex gap-8 py-8 lg:py-10"}>
        {isDetailWorkspaceRoute ? null : <Sidebar />}
        <main className={isDetailWorkspaceRoute ? "min-w-0 flex-1 px-4 lg:px-6" : "min-w-0 flex-1"}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
