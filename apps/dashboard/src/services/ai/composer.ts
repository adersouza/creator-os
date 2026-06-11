import { generateAiText, type AiGenerateOptions } from './generate.js';

export type ComposerAction = 'rephrase' | 'shorten' | 'expand' | 'spin' | 'translate' | 'matchVoice';

interface Args {
  action: ComposerAction;
  caption: string;
  selectedText?: string | undefined;
  /** Passed through so the backend can inject the account's voice_profile. */
  accountId?: string | null | undefined;
  platform?: 'threads' | 'instagram' | undefined;
  /** Used by translate. Defaults to Spanish when not provided. */
  targetLanguage?: string | undefined;
  /** Tone-critical flag — backend routes hero posts to Claude Haiku 4.5. */
  isHeroPost?: boolean | undefined;
}

const ACTION_PROMPT: Record<ComposerAction, (caption: string, targetLanguage?: string) => string> = {
  rephrase: (caption) => [
    'Rewrite this social post with the SAME meaning but fresh phrasing.',
    'Keep it at the same length. Preserve any handles, hashtags, links, and emoji as-is.',
    'Return only the rewritten post — no prefix, no commentary, no quotes around it.',
    '',
    'POST:',
    caption,
  ].join('\n'),
  shorten: (caption) => [
    'Shorten this social post to about 60% of its current length.',
    'Keep the core hook, the voice, any handles, hashtags, links, and emoji.',
    'Cut filler and redundancy. Return only the shortened post — no prefix, no commentary.',
    '',
    'POST:',
    caption,
  ].join('\n'),
  expand: (caption) => [
    'Expand this social post to be about 40% longer while keeping the same voice.',
    'Add specificity or a concrete example — do NOT add fluff, hedges, or lead-in phrases.',
    'Preserve handles, hashtags, links, emoji. Return only the expanded post.',
    '',
    'POST:',
    caption,
  ].join('\n'),
  spin: (caption) => [
    'Produce a different angle on this post — same subject, different framing or hook.',
    'Keep the same approximate length. Preserve handles, hashtags, links, emoji.',
    'Return only the new version — no commentary, no prefix.',
    '',
    'POST:',
    caption,
  ].join('\n'),
  translate: (caption, targetLanguage = 'Spanish') => [
    `Translate this social post to ${targetLanguage}.`,
    'Preserve handles (@mentions), hashtags, URLs, and emoji unchanged.',
    'Match the original tone — casual stays casual, formal stays formal.',
    'Return only the translation — no commentary, no prefix.',
    '',
    'POST:',
    caption,
  ].join('\n'),
  matchVoice: (caption) => [
    "Rewrite this post in the account's established voice.",
    "The account's voice profile is injected in context — mirror its diction, sentence rhythm, and opener style.",
    'Keep the meaning and approximate length. Preserve handles, hashtags, links, emoji.',
    'Return only the rewritten post — no prefix, no commentary.',
    '',
    'POST:',
    caption,
  ].join('\n'),
};

const FEATURE_TAG: Record<ComposerAction, string> = {
  rephrase: 'composer-rephrase',
  shorten: 'composer-shorten',
  expand: 'composer-expand',
  spin: 'composer-spin',
  translate: 'composer-translate',
  matchVoice: 'composer-match-voice',
};

function cleanupOutput(raw: string): string {
  return raw
    .trim()
    .replace(/^```[a-z]*\s*/i, '')
    .replace(/```\s*$/, '')
    .replace(/^"|"$/g, '')
    .replace(/^'|'$/g, '')
    .trim();
}

/**
 * Run a composer AI rewrite via the backend `/api/ai?action=generate`
 * endpoint. When `accountId` is provided the server injects that account's
 * voice_profile into the system prompt so the output stays on-brand.
 */
export async function runComposerAction(args: Args): Promise<string> {
  const trimmed = (args.selectedText ?? args.caption).trim();
  if (!trimmed) throw new Error('Write something first, then run an AI action.');

  const prompt = ACTION_PROMPT[args.action](trimmed, args.targetLanguage);
  const options: AiGenerateOptions = {
    feature: FEATURE_TAG[args.action],
    temperature: args.action === 'translate' ? 0.2 : 0.6,
    maxTokens: 600,
    accountId: args.accountId ?? undefined,
    platform: args.platform,
    isHeroPost: args.isHeroPost,
  };

  const raw = await generateAiText(prompt, options);
  const cleaned = cleanupOutput(raw);
  if (!cleaned) throw new Error('AI returned an empty response. Try again.');
  return cleaned;
}
