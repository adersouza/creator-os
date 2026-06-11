export type FailureClass =
  | 'OAuth expired'
  | 'Rate limited'
  | 'Content rejected'
  | 'Network'
  | 'Duplicate'
  | 'Other';

const ID_OR_TIMESTAMP_PATTERNS = [
  /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/gi,
  /\b\d{4}-\d{2}-\d{2}[t\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?z?\b/gi,
  /\b(?:post|account|container|media|request|trace|run|job|id)[_-]?[=:]\s*[\w.-]+\b/gi,
  /\b\d{10,}\b/g,
];

export function normalizeFailureReason(reason: string | null | undefined): string {
  const source = reason?.trim() || 'No error detail recorded.';
  return ID_OR_TIMESTAMP_PATTERNS.reduce(
    (current, pattern) => current.replace(pattern, '[id]'),
    source,
  )
    .replace(/\s+/g, ' ')
    .trim();
}

export function classifyFailureReason(reason: string | null | undefined): FailureClass {
  const normalized = normalizeFailureReason(reason);
  if (/oauth|token|expired|invalid_token/i.test(normalized)) return 'OAuth expired';
  if (/rate.?limit|429/i.test(normalized)) return 'Rate limited';
  if (/content.?policy|moderation|rejected/i.test(normalized)) return 'Content rejected';
  if (/network|timeout|ECONNRESET/i.test(normalized)) return 'Network';
  if (/duplicate/i.test(normalized)) return 'Duplicate';
  return 'Other';
}
