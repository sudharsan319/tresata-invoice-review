export async function api<T>(url: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api" + url, options);
  } catch {
    throw new Error(
      "Cannot reach the backend. Start the app with ./run.sh and try again.",
    );
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : body.detail
          ? JSON.stringify(body.detail)
          : `Request failed (${response.status}).`,
    );
  }
  return response.json();
}
