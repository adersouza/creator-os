# Offline prompt regressions

`pnpm check:prompts` renders the production Gemini prompt builder, the captured
offline Soul-reference prompt surface, and one captured caption-bank fixture.
The small local Python runner validates the prompt digest, captured schema, and
caption metadata directly.

The human rubric strings are intentionally retained for manual review and are
not model-graded. The runner contains no network or provider client and writes
no state. No provider key, generation endpoint, or paid grader is configured.
