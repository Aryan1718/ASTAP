import { FormEvent, useMemo, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { AuthCard } from "../components/ui/AuthCard";
import { Button } from "../components/ui/Button";
import { Checkbox } from "../components/ui/Checkbox";
import { Input } from "../components/ui/Input";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../hooks/useToast";

export function SignupPage() {
  const navigate = useNavigate();
  const { loading, rememberSession, session, signUp } = useAuth();
  const { notify } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [remember, setRemember] = useState(rememberSession);
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirmError = useMemo(() => {
    if (!confirmPassword) {
      return undefined;
    }
    return password === confirmPassword ? undefined : "Passwords do not match";
  }, [confirmPassword, password]);

  if (!loading && session) {
    return <Navigate to="/app/projects" replace />;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (!acceptedTerms) {
      setError("Accept the terms to continue");
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      const result = await signUp(email, password, remember);
      if (result.requiresEmailConfirmation) {
        notify({
          title: "Account created",
          description: "Confirm your email if required by your Supabase project, then sign in.",
          tone: "info",
        });
        navigate("/login", { replace: true });
      } else {
        notify({ title: "Workspace ready", description: "Your account is active.", tone: "success" });
        navigate("/app/projects", { replace: true });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to sign up");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthCard
      eyebrow="Signup"
      title="Create your ASTAP account"
      description="Sign up to connect a repository, run tests, and get analysis."
      alternateText="Already registered?"
      alternateLabel="Login"
      alternateLink="/login"
    >
      <form className="grid gap-5" onSubmit={handleSubmit}>
        <Input label="Email" type="email" placeholder="you@company.com" value={email} onChange={(event) => setEmail(event.target.value)} required />
        <Input label="Password" type="password" placeholder="Create a password" value={password} onChange={(event) => setPassword(event.target.value)} required />
        <Input
          label="Confirm password"
          type="password"
          placeholder="Repeat the password"
          value={confirmPassword}
          onChange={(event) => setConfirmPassword(event.target.value)}
          required
          error={confirmError ?? error ?? undefined}
        />
        <Checkbox
          checked={remember}
          onChange={(event) => setRemember(event.target.checked)}
          label="Remember session"
          hint="Persist the session on this device using Supabase's browser storage."
        />
        <Checkbox
          checked={acceptedTerms}
          onChange={(event) => setAcceptedTerms(event.target.checked)}
          label="I accept the terms"
          hint="Required to continue."
        />
        {error && !confirmError ? <p className="m-0 text-sm text-red-600">{error}</p> : null}
        <Button type="submit" disabled={submitting}>
          {submitting ? "Creating account..." : "Create account"}
        </Button>
      </form>
    </AuthCard>
  );
}
