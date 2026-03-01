import type { Project, ProjectPayload, RunDetail, RunListItem, RunStart } from "../types/api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function readErrorMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail ?? fallback;
  } catch {
    return fallback;
  }
}

async function request<T>(token: string, path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);

  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Request failed"));
  }

  return (await response.json()) as T;
}

export const apiClient = {
  listProjects(token: string) {
    return request<Project[]>(token, "/projects");
  },
  createProject(token: string, payload: ProjectPayload) {
    return request<Project>(token, "/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  startRun(token: string, projectId: string, ref?: string) {
    return request<RunStart>(token, `/projects/${projectId}/runs`, {
      method: "POST",
      body: JSON.stringify({ ref }),
    });
  },
  listRuns(token: string) {
    return request<RunListItem[]>(token, "/runs");
  },
  getRun(token: string, runId: string) {
    return request<RunDetail>(token, `/runs/${runId}`);
  },
};
