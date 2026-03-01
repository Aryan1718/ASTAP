import type { ReactElement } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "../hooks/useAuth";

export function ProtectedRoute({ children }: { children: ReactElement }) {
  const { loading, session } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
        <div className="surface w-full max-w-md p-8 text-center">
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-accent/20 border-t-accent" />
          <p className="mt-4 text-sm text-muted">Restoring your workspace session.</p>
        </div>
      </div>
    );
  }

  if (!session) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return children;
}
