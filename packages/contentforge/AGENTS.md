# ContentForge Agent Notes

ContentForge owns variant generation, FFmpeg processing, similarity/readiness/forensics/compression audits, and resumable variant-pack jobs.

## Current Cross-Repo Truth

- Campaign Factory calls ContentForge for audit and variant-pack workflows.
- Reel Factory active still generation is direct Higgsfield reference-image generation; ContentForge should not own prompt or Soul ID logic.
- ThreadsDashboard owns platform posts/schedules/publishing state.

## Do Not Do

- Do not schedule or publish.
- Do not mutate Campaign Factory inventory or ThreadsDashboard posts directly.
- Do not bypass upload-ready filters, similarity checks, or quality gates to force variants through.
- Do not reintroduce fake placeholder variant paths; generated outputs must exist or fail clearly.
