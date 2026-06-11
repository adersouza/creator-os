import { useCallback, useRef, useState } from 'react';
import { supabase } from '@/services/supabase';

export type InvestigateMetric =
  | 'reach'
  | 'followers'
  | 'engagement'
  | 'views'
  | 'conversion';

export interface InvestigationSection {
  title: string;
  body: string;
}

export interface InvestigationResult {
  metric: InvestigateMetric;
  periodDays: number;
  accountUsername: string | null;
  sections: InvestigationSection[];
  rawTranscript: string;
  dataUsed: string[];
}

export interface InvestigateParams {
  accountId: string;
  metric: InvestigateMetric;
  periodDays?: number | undefined;
  focusDate?: string | undefined;
  hypothesis?: string | undefined;
}

interface StreamState {
  streamingText: string;
  data: InvestigationResult | null;
  isPending: boolean;
  isError: boolean;
  error: Error | null;
}

const INITIAL_STATE: StreamState = {
  streamingText: '',
  data: null,
  isPending: false,
  isError: false,
  error: null,
};

/**
 * SSE-consuming investigation hook. Streams tokens as they arrive (visible via
 * `streamingText`) and swaps to the parsed `data` once the `done` event lands.
 * The UI can render `streamingText` during generation and the structured
 * `data.sections` after completion without a flicker — both are available.
 *
 * Uses fetch + ReadableStream instead of EventSource because EventSource
 * can't send POST bodies or auth headers.
 */
export function useInvestigate() {
  const [state, setState] = useState<StreamState>(INITIAL_STATE);
  const abortRef = useRef<AbortController | null>(null);

  const mutate = useCallback((params: InvestigateParams) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setState({ ...INITIAL_STATE, isPending: true });

    (async () => {
      try {
        const session = (await supabase.auth.getSession()).data.session;
        const response = await fetch('/api/ai?action=investigate&stream=true', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'text/event-stream',
            ...(session?.access_token
              ? { Authorization: `Bearer ${session.access_token}` }
              : {}),
          },
          body: JSON.stringify(params),
          signal: controller.signal,
        });

        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          const code = (body as { code?: string | undefined }).code;
          if (code === 'RATE_LIMITED') {
            throw new Error('You have hit the hourly investigation limit.');
          }
          if (code === 'NO_API_KEY') {
            throw new Error(
              'Add a Gemini API key in Settings to run investigations.',
            );
          }
          throw new Error(
            (body as { error?: string | undefined }).error ?? 'Investigation failed',
          );
        }

        if (!response.body) throw new Error('No response stream');

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let accumulated = '';

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // SSE frames are separated by blank lines. Each frame is a set of
          // `field: value` lines; we only care about `data:` frames.
          let splitAt: number;
          // biome-ignore lint/suspicious/noAssignInExpressions: idiomatic frame loop
          while ((splitAt = buffer.indexOf('\n\n')) >= 0) {
            const frame = buffer.slice(0, splitAt);
            buffer = buffer.slice(splitAt + 2);
            const line = frame
              .split('\n')
              .find((l) => l.startsWith('data:'));
            if (!line) continue;
            const payload = line.slice(5).trim();
            if (payload === '[DONE]') continue;
            try {
              const parsed = JSON.parse(payload) as Record<string, unknown>;
              if (typeof parsed.text === 'string') {
                accumulated += parsed.text;
                setState((prev) => ({
                  ...prev,
                  streamingText: accumulated,
                }));
              } else if (parsed.done === true) {
                setState({
                  streamingText: accumulated,
                  data: parsed as unknown as InvestigationResult,
                  isPending: false,
                  isError: false,
                  error: null,
                });
              } else if (typeof parsed.error === 'string') {
                throw new Error(parsed.error);
              }
            } catch (parseErr) {
              if (parseErr instanceof Error) throw parseErr;
            }
          }
        }
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        setState((prev) => ({
          ...prev,
          isPending: false,
          isError: true,
          error: err instanceof Error ? err : new Error(String(err)),
        }));
      }
    })();
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setState(INITIAL_STATE);
  }, []);

  return {
    mutate,
    reset,
    streamingText: state.streamingText,
    data: state.data,
    isPending: state.isPending,
    isError: state.isError,
    error: state.error,
  };
}
