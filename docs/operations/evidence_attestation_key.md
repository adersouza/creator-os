# Evidence attestation key

Creator OS evidence producers and verifiers share one machine-local HMAC key.
The key authenticates evidence; it does not authorize providers, publishing,
scheduling, databases, or runtime promotion.

Initialize it explicitly after reviewing the target path:

```bash
scripts/creator-os advanced evidence-key init --dry-run
scripts/creator-os advanced evidence-key init --apply
```

The default is `~/.creator-os/credentials/evidence-auth-key.json`. The apply
command creates a private directory and an atomic `0600` key file. It is
idempotent and prints only `keyId`, `path`, and whether it created the file; it
never prints the secret. A dry run does not create the directory or file.

`CREATOR_OS_EVIDENCE_AUTH_SECRET` remains the highest-priority source for
ephemeral and test environments. Set
`CREATOR_OS_EVIDENCE_AUTH_SECRET_FILE=/absolute/path/to/key.json` to override
the machine-local file location. `CREATOR_OS_EVIDENCE_AUTH_KEY_ID`, when set,
is a pin and must equal the ID derived from the loaded secret.

Both Creator OS Python and ContentForge Node loaders reject a symlink,
non-regular file, non-owner file, group/world-readable mode, oversized or short
secret, unsupported key-file version, and a stored or configured key ID that
does not match the secret. Do not copy the key into the repository, evidence
records, logs, or operator output. Existing attestations intentionally stop
verifying after a real key rotation; rotate only with an explicit migration and
evidence-retention plan.
