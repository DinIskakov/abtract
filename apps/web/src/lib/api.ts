import type { Experiment, ExperimentOptions, ExperimentRequest } from "./types";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { cache: "no-store", ...options });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data
      ? data.detail : null;
    const message = typeof detail === "string" ? detail
      : response.status === 502 || response.status === 503
        ? "The experiment service is unavailable. Check that the API is running."
        : `Request failed (${response.status}). Please try again.`;
    throw new Error(message);
  }
  return data as T;
}

export function fetchOptions(signal?: AbortSignal): Promise<ExperimentOptions> {
  return request("/api/experiments/options", { signal });
}

export function startExperiment(
  input: ExperimentRequest,
  signal?: AbortSignal,
): Promise<Experiment> {
  return request("/api/experiments", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    signal,
  });
}

export function fetchExperiment(id: string, signal?: AbortSignal): Promise<Experiment> {
  return request(`/api/experiments/${encodeURIComponent(id)}`, { signal });
}
