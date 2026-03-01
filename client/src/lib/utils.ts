export function cn(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function formatDateTime(value?: string | null) {
  if (!value) {
    return "Not available";
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatBytes(value?: number | null) {
  if (value == null) {
    return "Not available";
  }

  if (value === 0) {
    return "0 B";
  }

  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const size = value / 1024 ** exponent;
  return `${size.toFixed(size >= 10 || exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

export function repoNameFromUrl(repoUrl: string) {
  return repoUrl.replace(/\/+$/, "").split("/").slice(-1)[0]?.replace(/\.git$/, "") || "project";
}

export function validateGitHubUrl(value: string) {
  return /^https:\/\/github\.com\/[^/]+\/[^/]+(?:\.git)?\/?$/i.test(value.trim());
}
