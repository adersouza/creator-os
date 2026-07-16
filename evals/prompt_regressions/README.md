# Offline prompt regressions

`pnpm check:prompts` renders the production Gemini prompt builder, the captured
offline Soul-reference prompt surface, and one captured caption-bank fixture. A
local Python provider echoes the prompt beside captured contract output;
deterministic assertions validate the prompt digest, schema, and caption
metadata.

The human rubric strings are intentionally retained for manual review and are
not model-graded. The runner disables telemetry, updates, remote generation,
sharing, and caching, and writes Promptfoo state only to a temporary directory.
No provider key, generation endpoint, or paid grader is configured.
