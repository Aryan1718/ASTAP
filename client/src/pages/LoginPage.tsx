import { FormEvent, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";

import { AuthCard } from "../components/ui/AuthCard";
import { Button } from "../components/ui/Button";
import { Checkbox } from "../components/ui/Checkbox";
import { Input } from "../components/ui/Input";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../hooks/useToast";

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { loading, rememberSession, session, signIn } = useAuth();
  const { notify } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(rememberSession);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!loading && session) {
    const nextRoute = (location.state as { from?: string } | null)?.from ?? "/app/projects";
    return <Navigate to={nextRoute} replace />;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      await signIn(email, password, remember);
      notify({ title: "Session restored", description: "You are signed in to the workspace.", tone: "success" });
      navigate("/app/projects", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to log in");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthCard
      eyebrow="Login"
      title="Log in to ASTAP"
      description="Sign in to add a repository, start a run, and review analysis."
      alternateText="Need an account?"
      alternateLabel="Create one"
      alternateLink="/signup"
    >
      <form className="grid gap-5" onSubmit={handleSubmit}>
        <Input label="Email" type="email" placeholder="you@company.com" value={email} onChange={(event) => setEmail(event.target.value)} required />
        <Input
          label="Password"
          type="password"
          placeholder="Enter your password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
          error={error ?? undefined}
        />
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <Checkbox
            checked={remember}
            onChange={(event) => setRemember(event.target.checked)}
            label="Remember session"
            hint="Choose whether this device should persist your Supabase session."
          />
          <Link to="/signup" className="text-sm font-semibold text-accent-700">
            Create account
          </Link>
        </div>
        <Button type="submit" disabled={submitting}>
          {submitting ? "Signing in..." : "Login"}
        </Button>
      </form>
    </AuthCard>
  );
}
