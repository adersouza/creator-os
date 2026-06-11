import type { ChatTurn } from './types';

export function contradictionWarning(text: string, turns: ChatTurn[]): string | null {
  const outgoing = text.trim();
  if (!outgoing) return null;
  const recent = turns.slice(-3).map((turn) => turn.text).join(' ');
  const outgoingSentiment = simpleSentiment(outgoing);
  const recentSentiment = simpleSentiment(recent);
  if (outgoingSentiment && recentSentiment && outgoingSentiment !== recentSentiment) {
    return 'The draft reads as the opposite sentiment from the recent thread. Send anyway?';
  }
  const verb = mainVerb(recent);
  if (verb && new RegExp(`\\b(no|not|never|cannot|can't|won't|don't|doesn't|isn't)\\b.{0,24}\\b${verb}\\b`, 'i').test(outgoing)) {
    return `The draft appears to negate "${verb}" from the recent conversation. Send anyway?`;
  }
  return null;
}

function simpleSentiment(text: string): 'positive' | 'negative' | null {
  const lower = text.toLowerCase();
  const positive = /\b(thanks|thank you|great|good|love|appreciate|happy|yes|absolutely|glad)\b/.test(lower);
  const negative = /\b(bad|hate|angry|upset|wrong|no|never|can't|cannot|won't|sorry|problem|issue)\b/.test(lower);
  if (positive === negative) return null;
  return positive ? 'positive' : 'negative';
}

function mainVerb(text: string): string | null {
  const match = text.toLowerCase().match(/\b(send|ship|post|publish|refund|cancel|fix|remove|add|approve|schedule)\b/);
  return match?.[1] ?? null;
}
