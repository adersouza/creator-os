# Harden-Runner Egress Baseline

StepSecurity Harden-Runner currently runs in audit mode. Use this file as the
review checklist before moving any job to block mode.

## Expected CI Hosts

- `github.com`
- `api.github.com`
- `objects.githubusercontent.com`
- `release-assets.githubusercontent.com`
- `registry.npmjs.org`
- `pypi.org`
- `files.pythonhosted.org`
- `astral.sh`
- `get.pnpm.io`
- `ghcr.io`
- `pkg-containers.githubusercontent.com`
- `aquasecurity.github.io`
- `mirror.gcr.io`

## Hosts That Should Not Appear In Test Jobs

- production Supabase project hosts
- production QStash endpoints
- Instagram or Meta Graph API hosts
- Vercel production deployment hooks
- creator inventory or publishing webhook endpoints

If any forbidden host appears in a test or lint job, treat it as an operational
boundary bug before changing Harden-Runner to block mode.
