/**
 * AI config cache control. Today this is a no-op — the real provider cache
 * will land when `resolveProvider` is wired up on the browser side. Exposed
 * as a function so `useAIProviderStore` can invalidate on provider change
 * without reaching into internals.
 */

// eslint-disable-next-line @typescript-eslint/no-empty-function
export function clearAIConfigCache() {}
