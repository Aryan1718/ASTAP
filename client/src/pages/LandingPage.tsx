import { Link } from "react-router-dom";

import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";

const features = [
  {
    title: "Find broken tests faster",
    description: "ASTAP helps you run your project checks and quickly see where failures are happening.",
  },
  {
    title: "Spot flaky behavior",
    description: "Review analysis that helps surface unstable test behavior and inconsistent results.",
  },
  {
    title: "Catch API issues",
    description: "See when an API is not responding as expected or when an endpoint is causing failures.",
  },
  {
    title: "Read useful analysis",
    description: "Get a clearer summary of what happened instead of digging through raw output alone.",
  },
  {
    title: "Stay focused",
    description: "The app keeps the workflow simple: connect repo, start run, wait a bit, review results.",
  },
];

const steps = [
  { title: "Create your account", description: "Sign up or log in to your ASTAP workspace." },
  { title: "Add your GitHub repo and branch", description: "Create a project with the repository URL and the branch you want to run." },
  { title: "Start a run and review analysis", description: "Wait for the run to finish, then inspect progress, status, and analysis details." },
];

export function LandingPage() {
  return (
    <div className="min-h-screen bg-white">
      <header className="border-b border-line/80 bg-white/90 backdrop-blur">
        <div className="page-shell flex h-20 items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-accent text-sm font-bold text-white shadow-soft">AT</div>
            <div>
              <p className="m-0 text-sm font-semibold text-ink">ASTAP</p>
              <p className="m-0 text-xs text-muted">Automated Testing and Analysis Platform</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Link to="/login">
              <Button variant="ghost">Login</Button>
            </Link>
            <Link to="/signup">
              <Button>Get Started</Button>
            </Link>
          </div>
        </div>
      </header>

      <main>
        <section className="relative overflow-hidden border-b border-line/70">
          <div className="absolute inset-0 bg-hero-grid bg-[size:42px_42px] opacity-40" />
          <div className="page-shell relative grid gap-12 py-20 lg:grid-cols-[1.1fr_0.9fr] lg:py-28">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.32em] text-accent">Test runs and analysis</p>
              <h1 className="mt-6 max-w-4xl font-display text-5xl leading-tight text-ink md:text-6xl">
                ASTAP helps you run tests and understand what is failing.
              </h1>
              <p className="mt-6 max-w-2xl text-lg leading-8 text-muted text-balance">
                Connect your GitHub repository, choose a branch, start a run, and get analysis that helps you find flaky tests, broken APIs, and failure patterns.
              </p>
              <div className="mt-10 flex flex-wrap gap-4">
                <Link to="/signup">
                  <Button className="px-6 py-3">Get Started</Button>
                </Link>
                <Link to="/login">
                  <Button variant="ghost" className="px-6 py-3">
                    Login
                  </Button>
                </Link>
              </div>
            </div>
            <Card className="relative overflow-hidden p-8">
              <div className="absolute right-0 top-0 h-40 w-40 rounded-full bg-accent/10 blur-3xl" />
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-accent">How to use ASTAP</p>
              <h2 className="mt-3 text-2xl font-semibold text-ink">A simple workflow for your team.</h2>
              <div className="mt-8 grid gap-4">
                {["Create account", "Add repo", "Choose branch", "Start run", "Review analysis"].map((stage, index) => (
                  <div
                    key={stage}
                    className="rounded-2xl border border-line bg-white px-4 py-4"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="m-0 text-sm font-semibold tracking-[0.02em] text-ink">{stage}</p>
                      <span className="rounded-full bg-accent-50 px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-accent-700">
                        {index + 1}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </section>

        <section className="page-shell py-16 lg:py-20">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-accent">Why teams use ASTAP</p>
              <h2 className="mt-3 text-3xl font-semibold text-ink">Focus on what failed and why.</h2>
            </div>
          </div>
          <div className="mt-10 grid gap-5 md:grid-cols-2 xl:grid-cols-5">
            {features.map((feature) => (
              <Card key={feature.title} className="p-6">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-accent-50 text-sm font-semibold text-accent-700">
                  0{features.indexOf(feature) + 1}
                </div>
                <h3 className="mt-5 text-lg font-semibold text-ink">{feature.title}</h3>
                <p className="mt-3 text-sm leading-6 text-muted">{feature.description}</p>
              </Card>
            ))}
          </div>
        </section>

        <section className="border-y border-line/70 bg-canvas py-16 lg:py-20">
          <div className="page-shell">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-accent">How it works</p>
            <div className="mt-8 grid gap-6 lg:grid-cols-3">
              {steps.map((step, index) => (
                <Card key={step.title} className="p-8">
                  <p className="m-0 text-sm font-semibold uppercase tracking-[0.18em] text-accent">Step {index + 1}</p>
                  <h3 className="mt-3 text-2xl font-semibold text-ink">{step.title}</h3>
                  <p className="mt-4 text-sm leading-7 text-muted">{step.description}</p>
                </Card>
              ))}
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-line/80 bg-white">
        <div className="page-shell flex flex-col gap-4 py-8 text-sm text-muted sm:flex-row sm:items-center sm:justify-between">
          <p className="m-0">ASTAP</p>
          <div className="flex items-center gap-6">
            <a href="#" aria-disabled="true">
              Docs
            </a>
            <a href="#" aria-disabled="true">
              Status
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
