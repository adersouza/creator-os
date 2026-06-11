/**
 * Client-side AI helpers — currently a minimal stub. Real image-tagging
 * support will land when Juno33 ports its `/api/ai/tag-image`
 * endpoint. Kept as a named export so feature flags can swap the impl.
 */

export async function getAIService() {
  return {
    tagImage: async () => ({ tags: [], description: '' }),
  };
}
