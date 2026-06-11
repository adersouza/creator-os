# Slideshow / AI UGC Research Prompt

Use this prompt with a research agent when we want a current outside view on
the slideshow/carousel format before expanding the implementation:

```text
Research 2026 best practices for high-volume Instagram Reels slideshow/carousel
content made from AI-generated or model-shot still images.

Context:
- We are building a local pipeline that turns finished source images/videos
  into vertical slideshow slides, a stitched reel preview, and draft-only post
  payloads.
- We can use Higgsfield, Gemini/Kling-style prompt generation, or local tools
  like ComfyUI later, but the current goal is fast production of simple
  carousel/slideshow content.
- We are not using Arcads.ai.

Please focus on:
1. Common winning slideshow structures: number of slides, pacing, first-slide
   hook style, grid-preview format, and whether a stitched MP4 performs
   differently from native carousel uploads.
2. Visual patterns used in AI UGC/e-com slideshow posts: mirror selfies,
   phone-covering-face shots, product-in-hand shots, fitness/lifestyle shots,
   bedroom/gym/kitchen settings, and how much visual variety matters.
3. Caption-on-image patterns: top text, centered text, small quote text,
   view-count overlays, carousel icons, and readability/safe-zone rules.
4. What metadata should be stored per generated slideshow: source prompt,
   model/persona, image prompt, caption formula, slide hook, style tag,
   reference pattern, account target, and performance metrics.
5. How to use a reference corpus to learn slide formulas without blindly
   copying: caption archetypes, pose/setting tags, pacing, visual composition,
   and account-specific fit.
6. Recommended local implementation approach using Python/Pillow/FFmpeg today,
   plus when ComfyUI, Higgsfield, or Gemini/Kling prompt JSON generation would
   become useful.
7. Risks or practical constraints for high-volume production: visual sameness,
   weak hooks, low-quality AI hands/faces, repeated captions, operator review
   bottlenecks, and how to keep the workflow human-approved and draft-only.

Output:
- A practical architecture recommendation.
- A list of winning slideshow templates to implement.
- Suggested scoring signals for choosing the best slideshow variants.
- A compact JSON schema for a slideshow manifest that can feed Campaign Factory.

Avoid recommending autonomous publishing, engagement manipulation, or platform
enforcement bypass. Keep the focus on creative operations, QA, draft workflows,
and performance learning.
```
