// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Viral Potential Score Calculator
 *
 * Non-AI algorithm to estimate a post's viral potential (0-100)
 * based on content patterns, formatting, and best practices.
 */

// Hook words that tend to increase engagement
const HOOK_WORDS = [
  'unpopular opinion',
  'hot take',
  'controversial',
  "here's why",
  'the truth',
  'nobody talks about',
  'stop doing',
  "don't",
  'never',
  'always',
  'secret',
  'hack',
  'mistake',
  'revealed',
  'finally',
  'breaking',
  'just found out',
  'reminder',
  'thread',
  'a thread',
  'story time',
  'pov',
  'unpopular',
  'confession',
  'honest',
  'real talk',
];

// Patterns that indicate engaging content
const VIRAL_PATTERNS = [
  /^unpopular opinion:/i,
  /^hot take:/i,
  /^controversial:/i,
  /^here'?s why/i,
  /^the truth (about|is)/i,
  /^stop [a-z]+ing/i,
  /\?$/,  // Ends with question
  /^i (just|finally)/i,
  /^reminder:/i,
  /^pov:/i,
  /^nobody:?\s*\n/i,  // Nobody meme format
];

// Emoji detection regex (covers most common emoji ranges)
const EMOJI_REGEX = /[\u{1F300}-\u{1F9FF}]|[\u{2600}-\u{26FF}]|[\u{2700}-\u{27BF}]/u;

export interface ViralScoreBreakdown {
  score: number;
  factors: {
    contentLength: number;
    hasQuestion: boolean;
    hasHookWords: boolean;
    hasMedia: boolean;
    hasEmoji: boolean;
    hasLineBreaks: boolean;
    hasStrongOpening: boolean;
    hasPersonalPronoun: boolean;
  };
}

/**
 * Calculate viral potential score (0-100)
 *
 * Factors considered:
 * - Content length (optimal: 100-280 chars)
 * - Question marks (drive replies)
 * - Hook words (attention grabbers)
 * - Media presence (images/videos)
 * - Emoji usage (engagement boost)
 * - Line breaks (readability)
 * - Strong opening (capital letter, short first line)
 * - Personal pronouns (relatability)
 */
export const calculateViralPotential = (content: string, hasMedia: boolean): number => {
  if (!content || content.trim().length === 0) return 0;

  let score = 20; // Base score

  // Content length scoring (optimal: 100-280 chars)
  const len = content.length;
  if (len >= 100 && len <= 280) {
    score += 20; // Sweet spot
  } else if (len >= 50 && len <= 400) {
    score += 12; // Good range
  } else if (len > 400) {
    score += 5; // Long but still valid
  } else {
    score += 3; // Very short
  }

  // Question mark - drives engagement and replies
  if (content.includes('?')) {
    score += 15;
  }

  // Hook words - attention grabbers
  const lowerContent = content.toLowerCase();
  const hasHookWord = HOOK_WORDS.some(hook => lowerContent.includes(hook));
  if (hasHookWord) {
    score += 18;
  }

  // Viral patterns - specific high-engagement formats
  const hasViralPattern = VIRAL_PATTERNS.some(pattern => pattern.test(content));
  if (hasViralPattern) {
    score += 8;
  }

  // Media presence - significant engagement boost
  if (hasMedia) {
    score += 15;
  }

  // Emoji usage - moderate engagement boost
  if (EMOJI_REGEX.test(content)) {
    score += 5;
  }

  // Line breaks - improves readability
  if (content.includes('\n')) {
    score += 5;
  }

  // Strong opening - short first sentence, starts with capital
  const lines = content.split('\n');
  const firstLine = lines[0]!.trim();
  if (firstLine.length > 0 && firstLine.length < 60 && /^[A-Z]/.test(firstLine)) {
    score += 8;
  }

  // Personal pronouns - relatability
  if (/^(i |my |we |our )/i.test(content)) {
    score += 5;
  }

  // List format - organized content performs well
  if (/^\d+[.)]/m.test(content) || /^[-*]/m.test(content)) {
    score += 5;
  }

  // Cap score at 100
  return Math.min(Math.max(Math.round(score), 0), 100);
};

/**
 * Get detailed breakdown of viral score factors
 */
export const getViralScoreBreakdown = (content: string, hasMedia: boolean): ViralScoreBreakdown => {
  const lowerContent = content.toLowerCase();
  const firstLine = content.split('\n')[0]!.trim();

  return {
    score: calculateViralPotential(content, hasMedia),
    factors: {
      contentLength: content.length,
      hasQuestion: content.includes('?'),
      hasHookWords: HOOK_WORDS.some(hook => lowerContent.includes(hook)),
      hasMedia,
      hasEmoji: EMOJI_REGEX.test(content),
      hasLineBreaks: content.includes('\n'),
      hasStrongOpening: firstLine.length > 0 && firstLine.length < 60 && /^[A-Z]/.test(firstLine),
      hasPersonalPronoun: /^(i |my |we |our )/i.test(content),
    },
  };
};

/**
 * Get color for viral score display
 * Good (muted sage) · Warn (warm gold) · Idle (neutral grey) —
 * CLAUDE.md editorial health palette, not stoplight.
 */
export const getViralScoreColor = (score: number): string => {
  if (score >= 70) return 'var(--color-health-good)';
  if (score >= 40) return 'var(--color-health-warn)';
  return 'var(--color-health-idle)';
};

/**
 * Get label for viral score tier
 */
export const getViralScoreTier = (score: number): 'high' | 'medium' | 'low' => {
  if (score >= 70) return 'high';
  if (score >= 40) return 'medium';
  return 'low';
};

/**
 * Format viral score for display
 */
export const formatViralScore = (score: number): string => {
  return `${score}`;
};
