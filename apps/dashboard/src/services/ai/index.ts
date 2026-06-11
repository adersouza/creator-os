/**
 * AI services — unified entry point.
 *
 * Replaces the four overlapping modules (aiService, aiServiceClient,
 * aiInsightsService, aiComposerActions) with a single public surface.
 * Submodules under this folder stay focused on one concern each
 * (generate/composer/client/config); consumers should import from here.
 *
 * Usage:
 *   import { generateAiText, runComposerAction } from '@/services/ai';
 *   // or, for a grouped call style:
 *   import { ai } from '@/services/ai';
 *   await ai.generate(prompt);
 *   await ai.compose({ action: 'shorten', caption });
 */

export {
  generateAiText,
  AiNotConfiguredError,
  AiRateLimitedError,
  type AiGenerateOptions,
} from './generate.js';
export { runComposerAction, type ComposerAction } from './composer.js';
export { getAIService } from './client.js';
export { clearAIConfigCache } from './config.js';

import { generateAiText } from './generate.js';
import { runComposerAction } from './composer.js';
import { getAIService } from './client.js';
import { clearAIConfigCache } from './config.js';

export const ai = {
  generate: generateAiText,
  compose: runComposerAction,
  client: getAIService,
  clearCache: clearAIConfigCache,
} as const;
