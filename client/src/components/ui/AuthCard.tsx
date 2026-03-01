import { ReactNode } from "react";
import { Link } from "react-router-dom";

export function AuthCard({
  eyebrow,
  title,
  description,
  alternateLabel,
  alternateLink,
  alternateText,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  alternateLabel: string;
  alternateLink: string;
  alternateText: string;
  children: ReactNode;
}) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_0.9fr]">
      <div className="relative hidden overflow-hidden bg-ink px-10 py-12 text-white lg:block">
        <div className="absolute inset-0 bg-hero-grid bg-[size:40px_40px] opacity-20" />
        <div className="absolute left-0 top-0 h-72 w-72 rounded-full bg-accent/30 blur-3xl" />
        <div className="relative flex h-full max-w-xl flex-col justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.32em] text-accent-200">ASTAP</p>
            <h1 className="mt-6 font-display text-5xl leading-tight">Run tests and get clear analysis from your repository.</h1>
            <p className="mt-6 max-w-lg text-base leading-7 text-white/75">
              Add your GitHub repository, choose a branch, start a run, and review analysis about failures, flaky behavior, and broken APIs.
            </p>
          </div>
          <div className="grid gap-4">
            <div className="rounded-3xl border border-white/10 bg-white/5 p-6">
              <p className="m-0 text-sm font-semibold text-accent-100">Simple flow</p>
              <p className="mt-2 text-sm leading-6 text-white/70">Create an account, connect a repo, run it, and come back for the results.</p>
            </div>
          </div>
        </div>
      </div>
      <div className="flex items-center justify-center px-4 py-10 sm:px-6 lg:px-10">
        <div className="surface w-full max-w-md p-8 sm:p-10">
          <div className="mb-6 flex items-center justify-between gap-3">
            <Link
              to="/"
              className="inline-flex items-center justify-center rounded-full border border-line bg-white px-3 py-2 text-sm font-semibold text-ink transition duration-200 hover:border-accent/40 hover:text-accent-700"
            >
              Home
            </Link>
            <p className="m-0 text-sm font-semibold text-ink">ASTAP</p>
          </div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-accent">{eyebrow}</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight text-ink">{title}</h2>
          <p className="mt-3 text-sm leading-6 text-muted">{description}</p>
          <div className="mt-8">{children}</div>
          <p className="mt-6 text-sm text-muted">
            {alternateText}{" "}
            <Link to={alternateLink} className="font-semibold text-accent-700">
              {alternateLabel}
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
