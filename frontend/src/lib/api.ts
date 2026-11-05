export type Profile = {
  user: { id: string; name: string; email: string };
  role: { id: string; name: string };
  categories: { id: string; name: string }[];
  permissions: string[];
  csrf_token: string;
};
export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};
export type Citation = {
  source_id: string;
  document_id: string;
  chunk_id: string;
  document_title: string;
  filename: string;
  page_number: number;
  download_url: string;
};
export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  withheld: boolean;
  sources: Citation[];
};
export type Document = {
  id: string;
  title: string;
  original_filename: string;
  category_id: string;
  created_at: string;
};
export type Answer = {
  conversation_id: string;
  question: Message;
  answer: Message;
  model: string;
  routing_reason: string;
};
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    csrf?: string;
    signal?: AbortSignal;
    form?: FormData;
  } = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method: options.method ?? "GET",
      credentials: "same-origin",
      cache: "no-store",
      signal: options.signal,
      headers: {
        ...(options.body !== undefined && !options.form
          ? { "Content-Type": "application/json" }
          : {}),
        ...(options.csrf ? { "X-CSRF-Token": options.csrf } : {}),
      },
      body:
        options.form ??
        (options.body !== undefined ? JSON.stringify(options.body) : undefined),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      0,
      "Cannot reach the server. Refresh to check whether your change was saved before retrying.",
    );
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    let message =
      typeof payload?.detail === "string"
        ? payload.detail
        : "The request could not be completed. Refresh the current view to check whether the change was saved before retrying.";
    if (response.status === 422)
      message = "Check the required fields and their limits, then try again.";
    if (response.status === 429)
      message = path.startsWith("/auth/")
        ? "Too many sign-in attempts. Please wait a minute and try again."
        : `AI capacity is busy. Try again in ${response.headers.get("Retry-After") ?? "a few"} seconds.`;
    throw new ApiError(response.status, message);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export async function allPages<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T[]> {
  const result: T[] = [];
  for (let offset = 0; ; offset += 100) {
    const page = await api<T[]>(`${path}?offset=${offset}&limit=100`, {
      signal,
    });
    result.push(...page);
    if (page.length < 100) return result;
  }
}
