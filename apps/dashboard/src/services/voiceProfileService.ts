/**
 * Voice profile service — reads/writes `ai_config` on Threads `accounts`
 * and `instagram_accounts`, and proxies the AI-powered style-bible
 * extractor at `/api/ai?action=style-bible`.
 *
 * The backend's `/api/ai?action=generate` endpoint reads `ai_config` and
 * injects VOICE/PERSONA/FOCUS TOPICS/etc. into the system prompt when the
 * Composer passes `accountId`, so every field we write here is something
 * the AI will respect at generation time.
 */

import { supabase } from './supabase';
import {
  AiNotConfiguredError,
  AiRateLimitedError,
} from './ai';
import type { AccountPlatform } from '@/hooks/useFleetAccounts';
import type { ExtractedStyle, VoiceProfile } from '@/types/voice';
import { accountTableFor } from '@/lib/socialPlatform';

function normalizeProfile(raw: unknown): VoiceProfile {
  if (!raw || typeof raw !== 'object') return {};
  return raw as VoiceProfile;
}

function asConfigObject(raw: unknown): Record<string, unknown> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  return raw as Record<string, unknown>;
}

export async function fetchVoiceProfile(
  accountId: string,
  platform: AccountPlatform,
): Promise<VoiceProfile> {
  const { data, error } = await supabase
    .from(accountTableFor(platform))
    .select('ai_config')
    .eq('id', accountId)
    .maybeSingle();

  if (error) throw error;
  return normalizeProfile(data?.ai_config);
}

export async function saveVoiceProfile(
  accountId: string,
  platform: AccountPlatform,
  profile: VoiceProfile,
): Promise<void> {
  const table = accountTableFor(platform);
  const { data: existing, error: fetchError } = await supabase
    .from(table)
    .select('ai_config')
    .eq('id', accountId)
    .maybeSingle();
  if (fetchError) throw fetchError;

  const mergedConfig = {
    ...asConfigObject(existing?.ai_config),
    ...profile,
  };

  const { error } = await supabase
    .from(table)
    // Supabase update requires cast for JSONB columns.
    .update({ ai_config: mergedConfig as never })
    .eq('id', accountId);
  if (error) throw error;
}

/**
 * Backend extracted-profile shape — mirrors the POST response from
 * `/api/ai?action=style-bible` (see Juno33
 * api/_lib/handlers/ai/style-bible.ts).
 */
export interface ExtractedStyleBible {
  avgLength: number;
  toneWords: string[];
  emojiUsage: 'heavy' | 'moderate' | 'minimal' | 'none';
  hashtagStyle: 'inline' | 'block' | 'none';
  ctaPatterns: string[];
  sentenceStyle: 'short' | 'mixed' | 'long';
  personality: string;
}

export class StyleBibleTierLockedError extends Error {
  constructor() {
    super('Style Bible extraction requires the Pro plan or higher.');
    this.name = 'StyleBibleTierLockedError';
  }
}

/**
 * Call the backend AI extractor. The server runs rule-based + Gemini
 * analysis in parallel, upserts a `style_bibles` row, and returns the
 * merged profile. The UI folds this back into `ai_config.extracted_style`
 * so the generate endpoint picks it up on the next Composer run.
 */
export async function extractStyleBible(
  captions: string[],
  accountId: string,
): Promise<ExtractedStyleBible> {
  const { data: { session } } = await supabase.auth.getSession();
  if (!session?.access_token) throw new Error('Not authenticated');

  const response = await fetch('/api/ai?action=style-bible', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${session.access_token}`,
    },
    body: JSON.stringify({ captions, accountId }),
  });

  if (response.status === 402 || response.status === 403) {
    throw new StyleBibleTierLockedError();
  }
  if (response.status === 429) throw new AiRateLimitedError();
  if (response.status === 503) {
    const body = await response.json().catch(() => ({}));
    if (body?.code === 'NO_API_KEY' || body?.code === 'AI_UNAVAILABLE') {
      throw new AiNotConfiguredError();
    }
  }
  if (!response.ok) {
    let message = `Style extraction failed (${response.status})`;
    try {
      const body = await response.json();
      if (body?.error) message = String(body.error);
    } catch {
      /* keep default */
    }
    throw new Error(message);
  }

  const body = await response.json();
  const profile = body?.data?.profile ?? body?.profile;
  if (!profile || typeof profile !== 'object') {
    throw new Error('Extractor returned an empty profile.');
  }
  return profile as ExtractedStyleBible;
}

/**
 * Merge the rule/AI extraction into the richer `extracted_style` shape
 * the backend's `generate` handler actually looks at (see #418 in
 * generate.ts in the Juno33 backend). Fields we don't have stay undefined —
 * the prompt-builder skips missing keys.
 */
export function toExtractedStyle(
  extracted: ExtractedStyleBible,
): ExtractedStyle {
  const lengthPreference: ExtractedStyle['length']['preference'] =
    extracted.avgLength < 80
      ? 'very-short'
      : extracted.avgLength < 180
        ? 'short'
        : extracted.avgLength < 400
          ? 'medium'
          : 'long';

  const emojiFrequency: ExtractedStyle['emoji_usage']['frequency'] =
    extracted.emojiUsage === 'heavy'
      ? 'heavy'
      : extracted.emojiUsage === 'moderate'
        ? 'moderate'
        : extracted.emojiUsage === 'minimal'
          ? 'rare'
          : 'none';

  return {
    sentence_patterns: {
      avg_length:
        extracted.sentenceStyle === 'short'
          ? 'short'
          : extracted.sentenceStyle === 'long'
            ? 'long'
            : 'medium',
      structure: 'mixed',
      rhythm: extracted.personality || '',
    },
    hooks: { patterns: [], examples: [] },
    closings: {
      patterns: extracted.ctaPatterns,
      cta_style: extracted.ctaPatterns.length > 0 ? 'soft' : 'none',
    },
    emoji_usage: {
      frequency: emojiFrequency,
      placement: 'end',
      favorites: [],
    },
    vocabulary: {
      signature_words: extracted.toneWords,
      avoid_words: [],
      tone_markers: extracted.toneWords,
    },
    formatting: {
      line_breaks: 'moderate',
      lists: false,
      caps_usage: 'none',
    },
    tone: {
      vibe: extracted.personality,
      energy: 'moderate',
    },
    length: {
      typical_chars: String(extracted.avgLength),
      preference: lengthPreference,
    },
    punctuation: { quirks: [], question_frequency: 'rare' },
    extracted_at: new Date().toISOString(),
  };
}
