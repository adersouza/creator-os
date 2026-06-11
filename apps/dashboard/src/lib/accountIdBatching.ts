export const MAX_ACCOUNT_IDS_PER_POSTGREST_BATCH = 20;

export function chunkAccountIds(
  accountIds: readonly string[],
  maxPerBatch = MAX_ACCOUNT_IDS_PER_POSTGREST_BATCH,
): string[][] {
  const uniqueIds = Array.from(new Set(accountIds.filter(Boolean)));
  if (maxPerBatch < 1) return uniqueIds.length > 0 ? [uniqueIds] : [];

  const chunks: string[][] = [];
  for (let i = 0; i < uniqueIds.length; i += maxPerBatch) {
    chunks.push(uniqueIds.slice(i, i + maxPerBatch));
  }
  return chunks;
}
