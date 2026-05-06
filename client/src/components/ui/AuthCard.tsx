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
      <div className="relative hidden overflow-hidden bg-hero-gradient px-10 py-12 text-white lg:block">
        <div className="relative flex h-full max-w-xl flex-col justify-between">
          <div>
            <p className="font-display text-sm uppercase tracking-[0.32em] text-white">ASTAP</p>
            <h1 className="mt-6 font-display text-5xl leading-[0.96] text-white" style={{ fontWeight: 540 }}>
              Run tests and get clear analysis from your repository.
            </h1>
            <p className="mt-6 max-w-lg text-base leading-7 text-white/80">
              Add your GitHub repository, choose a branch, start a run, and review analysis about failures, flaky behavior, and broken APIs.
            </p>
          </div>
          <div className="grid gap-4">
            <div className="hero-panel p-6">
              <p className="m-0 text-sm text-white">Simple flow</p>
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
              className="inline-flex items-center justify-center rounded-lg border border-line px-3 py-2 font-display text-sm uppercase tracking-[0.1em] text-ink transition duration-200 hover:bg-[#f7f3ee]"
            >
              Home
            </Link>
            <p className="m-0 font-display text-sm uppercase tracking-[0.12em] text-ink">ASTAP</p>
          </div>
          <p className="text-xs uppercase tracking-[0.24em] text-muted">{eyebrow}</p>
          <h2 className="mt-3 font-display text-3xl tracking-tight text-ink" style={{ fontWeight: 460 }}>
            {title}
          </h2>
          <p className="mt-3 text-sm leading-6 text-muted">{description}</p>
          <div className="mt-8">{children}</div>
          <p className="mt-6 text-sm text-muted">
            {alternateText}{" "}
            <Link to={alternateLink} className="text-link underline underline-offset-4">
              {alternateLabel}
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
