import { FormEvent, useMemo, useState } from "react";

import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Input } from "../ui/Input";
import { validateGitHubUrl } from "../../lib/utils";

type CreateProjectFormProps = {
  onSubmit: (payload: { name: string; repo_url: string; default_branch: string }) => Promise<void>;
  loading?: boolean;
};

export function CreateProjectForm({ onSubmit, loading }: CreateProjectFormProps) {
  const [name, setName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [error, setError] = useState<string | null>(null);

  const repoError = useMemo(() => {
    if (!repoUrl) {
      return undefined;
    }
    return validateGitHubUrl(repoUrl) ? undefined : "Use a full GitHub URL such as https://github.com/org/repo";
  }, [repoUrl]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (repoError) {
      setError(repoError);
      return;
    }

    try {
      setError(null);
      await onSubmit({
        name: name.trim(),
        repo_url: repoUrl.trim(),
        default_branch: branch.trim() || "main",
      });
      setName("");
      setRepoUrl("");
      setBranch("main");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create project");
    }
  }

  return (
    <Card className="p-6 md:p-8">
      <div className="flex flex-col gap-2 pb-2">
        <p className="m-0 text-xs font-semibold uppercase tracking-[0.24em] text-accent">Add GitHub project</p>
        <h2 className="m-0 text-2xl font-semibold text-ink">Register a repository for pipeline runs</h2>
        <p className="m-0 text-sm leading-6 text-muted">Create the project once, then launch new runs from the larger project list.</p>
      </div>
      <form className="mt-6 grid gap-4 lg:grid-cols-[1fr_1.35fr_220px_auto] lg:items-end" onSubmit={handleSubmit}>
        <Input label="Project name" placeholder="acme-monorepo" value={name} onChange={(event) => setName(event.target.value)} required />
        <Input
          label="GitHub link"
          placeholder="https://github.com/org/repo"
          value={repoUrl}
          onChange={(event) => setRepoUrl(event.target.value)}
          required
          error={repoError ?? undefined}
        />
        <Input label="Branch" placeholder="main" value={branch} onChange={(event) => setBranch(event.target.value)} required />
        <div className="flex justify-start lg:justify-end">
          <Button type="submit" disabled={loading} className="min-w-32">
            {loading ? "Adding..." : "Add Project"}
          </Button>
        </div>
        {error && !repoError ? <p className="m-0 text-sm text-red-600 lg:col-span-4">{error}</p> : null}
      </form>
    </Card>
  );
}
