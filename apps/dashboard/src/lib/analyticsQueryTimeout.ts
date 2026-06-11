export const ANALYTICS_QUERY_TIMEOUT_MS = 8_000;

export function withAnalyticsQueryTimeout<T>(
  promise: Promise<T>,
  label: string,
  timeoutMs = ANALYTICS_QUERY_TIMEOUT_MS,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;

  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      reject(new Error(`${label} timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  });

  return Promise.race([promise, timeout]).finally(() => {
    if (timer !== undefined) clearTimeout(timer);
  });
}
