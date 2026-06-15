#!/usr/bin/env node

console.log(`
CodeQL runs in GitHub Actions via .github/workflows/security.yml.

Local command:
  pnpm security:secrets

CodeQL is intentionally not run as a local default because GitHub Actions owns
database setup, language analysis, and alert upload for this repository.
`);

