# Meta Compliance Verification 2026

Last checked: 2026-05-22

This note records the official-source baseline for Juno33's Instagram and Threads enforcement rules. Product policy should stay conservative when Meta docs are ambiguous or gated behind app review.

## Official Sources To Treat As Canonical

- Instagram Platform Content Publishing: https://developers.facebook.com/docs/instagram-platform/content-publishing/
- Instagram Platform API with Instagram Login: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/
- Instagram API with Facebook Login: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/
- Instagram comments/reference family: https://developers.facebook.com/docs/instagram-api/reference/media/comments/
- Instagram Messaging API: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api/
- Threads API overview: https://developers.facebook.com/docs/threads/
- Threads publishing reference: https://developers.facebook.com/docs/threads/posts/
- Graph API rate limiting and errors: https://developers.facebook.com/docs/graph-api/overview/rate-limiting/
- Meta Platform Terms: https://developers.facebook.com/terms/

## Product Rules Verified Enough To Enforce

- Use official Meta APIs only for publishing, replying, messaging, insights, and account sync. Do not add browser automation, scraping, reverse-engineered mobile endpoints, or UI-simulated engagement.
- Keep publish preflight strict before queue insertion and again before publish: token health, account ownership, account active state, media URL accessibility, platform limits, captions, collaborators, branded content fields, and idempotency.
- Threads publishing remains a container/publish workflow; Juno33 should keep scheduling as an internal queue/QStash concern rather than assuming a native Threads scheduled publish endpoint.
- Instagram content publishing creates media containers and then publishes them. Container expiry and processing state should stay part of the retry/failure model.
- Instagram comment/reply and messaging workflows require the relevant reviewed permissions and should remain human-supervised for risky or high-volume actions.
- Like/unlike media or comments, if enabled, must require `instagram_manage_engagement`, exact approval, rate limits, and anti-bot policy gates.
- Paid partnership/branded content fields should be allowed only when the connected account, permissions, and sponsor IDs are validated. If validation cannot prove the post is permitted, route to review.

## Claims Not Yet Safe To Hard-Code

- Non-official claims about exact 2026 duplicate-comment thresholds, reach penalties, or "authentic engagement" percentages should stay advisory only unless Meta publishes them in official developer policy.
- Competitor-derived content rules should be enforced through Juno33's own plagiarism/brand-safety policy, not because of an unverified Meta-specific numeric threshold.
- Any new April 2026 fields or endpoints should be encoded behind capability detection and API-version-safe error handling until verified in the app's approved Meta surface.

## Follow-Up

- Re-check this note before each Meta API version bump.
- Add the exact official doc URL to code comments or tests only when a rule is directly encoded in product policy.
- Keep approval-required behavior as the fallback for ambiguous posting, reply, like, paid partnership, and fleet-wide actions.
