import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchInboxSuggestionsBatch } from './inbox';

const apiFetchMock = vi.hoisted(() => vi.fn());
const getSessionMock = vi.hoisted(() => vi.fn());

vi.mock('@/lib/apiFetch', () => ({
  apiFetch: apiFetchMock,
}));

vi.mock('@/services/supabase', () => ({
  supabase: {
    auth: {
      getSession: getSessionMock,
    },
  },
}));

describe('inbox API service', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    getSessionMock.mockReset();
    getSessionMock.mockResolvedValue({ data: { session: { access_token: 'token' } } });
    apiFetchMock.mockResolvedValue({ success: true, suggestions: [] });
  });

  it('fetches suggestion batches with a compact POST body instead of query-string key lists', async () => {
    const conversationKeys = Array.from({ length: 80 }, (_, index) => `threads:comment:${index}`);

    await fetchInboxSuggestionsBatch(conversationKeys);

    expect(apiFetchMock).toHaveBeenCalledTimes(1);
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/inbox?action=suggestions',
      expect.anything(),
      {
        method: 'POST',
        json: { conversation_keys: conversationKeys },
      },
    );
  });
});
