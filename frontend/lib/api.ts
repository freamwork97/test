const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

type FetchOptions = RequestInit & { withCredentials?: boolean };

async function apiFetch<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail ?? "Request failed");
  }

  return res.json() as Promise<T>;
}

export const authApi = {
  register: (email: string, password: string) =>
    apiFetch("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  login: (email: string, password: string) =>
    apiFetch("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  refresh: () =>
    apiFetch("/auth/refresh", { method: "POST" }),

  logout: (allSessions = false) =>
    apiFetch(`/auth/logout?all_sessions=${allSessions}`, { method: "POST" }),

  me: () =>
    apiFetch<{ id: string; email: string; is_active: boolean }>("/auth/me"),
};
