import { describe, expect, it } from 'vitest';
import { MAX_ACCOUNT_IDS_PER_POSTGREST_BATCH, chunkAccountIds } from './accountIdBatching';

describe('chunkAccountIds', () => {
  it('deduplicates and splits account ids into bounded PostgREST batches', () => {
    const ids = Array.from({ length: 45 }, (_, index) => `acct-${index}`);
    const chunks = chunkAccountIds([...ids, 'acct-0', '', 'acct-1']);

    expect(chunks).toHaveLength(3);
    expect(chunks.every((chunk) => chunk.length <= MAX_ACCOUNT_IDS_PER_POSTGREST_BATCH)).toBe(true);
    expect(chunks.flat()).toEqual(ids);
  });

  it('returns no batches for an empty scope', () => {
    expect(chunkAccountIds([])).toEqual([]);
    expect(chunkAccountIds(['', ''])).toEqual([]);
  });
});
