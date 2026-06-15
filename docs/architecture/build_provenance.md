# Creator OS Build Provenance

Creator OS records provenance for CI-generated artifacts without changing
deployment routing or runtime behavior.

## Current Attested Artifacts

- `creator-os-sbom`: CycloneDX JavaScript dependency snapshot plus exported
  Python requirements.
- `dashboard-dist`: Dashboard build output produced by `pnpm --filter juno33
  build`.

Both artifacts are uploaded by GitHub Actions and attested with GitHub Artifact
Attestations. Attestation is provenance only. It does not mean the artifact is
approved for deployment, published, or promoted to production runtime.

## Required Workflow Permissions

Jobs that generate attestations must use:

```yaml
permissions:
  contents: read
  attestations: write
  id-token: write
```

## Verification

After a workflow run completes:

```bash
gh run download <run-id> --name creator-os-sbom
gh run download <run-id> --name dashboard-dist
gh attestation verify --repo adersouza/creator-os artifacts/sbom/js.cdx.json
```

Use the run SHA and artifact digest as evidence in promotion notes. Do not use
attestation as a replacement for tests, code review, environment approvals, or
staged operational dry-runs.
