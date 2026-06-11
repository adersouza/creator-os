# Voice Profile Audit

## Summary
Audit of voice profile consistency across all AI features. Updated 2026-02-18.

## Modular AI Services (`services/ai/`)

### ✅ Fully Integrated
| File | Functions | Notes |
|------|-----------|-------|
| `voiceHelpers.ts` | `loadVoiceProfile()`, `buildVoiceContext()` | **NEW** — shared helpers for all files |
| `ideas.ts` | `generatePostIdeas()` | Accepts `voiceProfile` in `PostIdeasInput`, builds context inline |
| `competitor.ts` | `adaptCompetitorPost()` | Auto-loads via `loadVoiceProfile()` |
| `replies.ts` | `generateReplySuggestions()`, `analyzeSentiment()`, `generateSmartReply()`, `generateDMResponse()` | Auto-loads voice; DM response also accepts explicit param |
| `calendar.ts` | `generateWeeklyContentPlan()`, `generateCalendarFill()` | Both accept optional `voiceProfile` param |
| `media.ts` | `generateCaptionFromImage()` | Accepts `voiceProfile` param |
| `content.ts` | `generatePostContent()`, `improvePostContent()`, `addStrongHook()`, `makeShorter()`, `makePunchier()`, `addEmojiFormatting()`, `optimizeForVirality()`, `generateContentVariations()`, `rephraseVariations()`, `generateBatchDrafts()` | All auto-load voice profile |
| `ab-testing.ts` | `generateABVariations()`, `generateABTestVariants()` | Auto-load voice profile |
| `repurpose.ts` | `repurposeContent()`, `repurposeToCarousel()`, `expandToThread()`, `generateThreadFromTopic()`, + others | Accept optional `voiceProfile` param |
| `inspiration.ts` | `generateInspirationIdea()`, `generateInspirationVariants()` | Accept `voiceProfile` param; falls back to `loadVoiceProfile()` when no `extractedStyle` |
| `growth.ts` | `generateDiagnosisDraft()` | Accepts optional `voiceProfile` param, auto-loads |

### ⚪ No Voice Profile Needed
| File | Functions | Reason |
|------|-----------|--------|
| `core.ts` | `generateContent()`, `testAIConnection()`, `loadUserAIPrefs()` | Infrastructure, not content generation |
| `analytics.ts` | `calculateSimilarity()`, `calculateViralScore()` | Pure computation, no text generation |
| `hashtags.ts` | `suggestHashtags()`, `generateHashtagSets()`, `analyzeHashtagPerformance()` | Hashtags don't reflect voice; performance analysis is data-only |
| `voice.ts` | `extractStyleDNA()`, `saveExtractedStyleToAccount()` | Extraction tool itself, not content generation |
| `growth.ts` | `generateGrowthPlan()`, `generateGrowthSimulation()`, `generateGoalCoaching()` | Analytical/strategic output, not user-facing posts |

---

## Legacy `services/aiService.ts` (NOT refactored)

This ~5800-line file duplicates many functions from `services/ai/`. The following functions generate user-facing content **without voice profile support**:

| Line | Function | Issue |
|------|----------|-------|
| ~560 | `generatePostContent()` | Uses tone string only, no voice profile |
| ~600 | `improvePostContent()` | Uses tone string only, no voice profile |
| ~640 | `addStrongHook()` | No voice context |
| ~660 | `makeShorter()` | No voice context |
| ~670 | `makePunchier()` | No voice context |
| ~680 | `addEmojiFormatting()` | No voice context |
| ~690 | `optimizeForVirality()` | No voice context |
| ~760 | `generateContentVariations()` | No voice context |
| ~840 | `rephraseVariations()` | No voice context |
| ~910 | `adaptMediaIdea()` | No voice context |
| ~970 | `generateBatchDrafts()` | No voice context |

**Note:** `adaptCompetitorPost()` at ~799 DOES call `loadVoiceProfile()`/`buildVoiceContext()` but these functions are **not defined or imported** in the file — this is a runtime error waiting to happen.

### Recommendation
The legacy `aiService.ts` should be fully migrated to use `services/ai/` modules. Until then, callers should import from `services/ai/` (via `services/ai/index.ts`) instead of `services/aiService.ts`.
