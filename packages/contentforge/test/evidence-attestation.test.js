import assert from "node:assert/strict";
import { createHash, createHmac } from "node:crypto";
import { chmodSync, mkdtempSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  canonicalJsonDeep,
  evidenceKeyId,
  evidenceSecretPath,
  evidencePayloadFingerprint,
  loadEvidenceSecret,
  signEvidenceAttestation,
  verifyEvidenceAttestation,
} from "../lib/evidence-attestation.js";

const SECRET = "contentforge-attestation-test-secret-0123456789";
const ISSUED_AT = "2026-01-02T03:04:05Z";
const KEY_ID = `local-${createHash("sha256").update(SECRET).digest("hex").slice(0, 16)}`;
const ENVIRONMENT = {
  CREATOR_OS_EVIDENCE_AUTH_SECRET: SECRET,
  CREATOR_OS_EVIDENCE_AUTH_KEY_ID: KEY_ID,
};

test("signs deterministic canonical authenticated evidence", function () {
  var payload = {
    z: [true, null, 0.75],
    a: { unicode: "Larissa ✨", integer: 2 },
  };
  var attestation = signEvidenceAttestation(payload, {
    issuer: "contentforge.test",
    issuedAt: ISSUED_AT,
    environ: ENVIRONMENT,
  });
  var expectedPayloadFingerprint = createHash("sha256")
    .update(canonicalJsonDeep(payload))
    .digest("hex");
  var unsigned = { ...attestation };
  delete unsigned.signature;
  var expectedSignature = createHmac("sha256", SECRET)
    .update(canonicalJsonDeep(unsigned))
    .digest("hex");

  assert.equal(attestation.schema, "creator_os.evidence_attestation.v1");
  assert.equal(attestation.algorithm, "hmac-sha256");
  assert.equal(attestation.keyId, KEY_ID);
  assert.equal(attestation.payloadFingerprint, expectedPayloadFingerprint);
  assert.equal(attestation.signature, expectedSignature);
  assert.equal(evidencePayloadFingerprint(payload), expectedPayloadFingerprint);
  assert.deepEqual(
    verifyEvidenceAttestation(attestation, payload, {
      expectedIssuer: "contentforge.test",
      expectedIssuedAt: ISSUED_AT,
      environ: ENVIRONMENT,
      now: Date.parse("2026-01-02T03:05:00Z"),
    }),
    attestation,
  );
});

test("derives a stable local key identity when no ID is configured", function () {
  var expected = createHash("sha256").update(SECRET).digest("hex").slice(0, 16);
  assert.equal(
    evidenceKeyId(SECRET, { CREATOR_OS_EVIDENCE_AUTH_SECRET: SECRET }),
    `local-${expected}`,
  );
});

test("rejects missing secrets, tampered payloads, signatures, and future evidence", function () {
  var payload = { evidence: "measured" };
  assert.throws(
    function () {
      signEvidenceAttestation(payload, {
        issuer: "contentforge.test",
        issuedAt: ISSUED_AT,
        environ: { CREATOR_OS_EVIDENCE_AUTH_SECRET: "short" },
      });
    },
    /evidence_attestation_secret_too_short/,
  );
  var attestation = signEvidenceAttestation(payload, {
    issuer: "contentforge.test",
    issuedAt: ISSUED_AT,
    environ: ENVIRONMENT,
  });
  assert.throws(
    function () {
      verifyEvidenceAttestation(attestation, { evidence: "invented" }, {
        expectedIssuer: "contentforge.test",
        environ: ENVIRONMENT,
      });
    },
    /evidence_attestation_payload_mismatch/,
  );
  assert.throws(
    function () {
      verifyEvidenceAttestation({ ...attestation, signature: "0".repeat(64) }, payload, {
        expectedIssuer: "contentforge.test",
        environ: ENVIRONMENT,
      });
    },
    /evidence_attestation_signature_invalid/,
  );
  assert.throws(
    function () {
      verifyEvidenceAttestation(attestation, payload, {
        expectedIssuer: "contentforge.test",
        environ: ENVIRONMENT,
        now: Date.parse("2026-01-02T03:00:00Z"),
      });
    },
    /evidence_attestation_issued_at_from_future/,
  );
});

test("canonical JSON fails closed on non-JSON numbers and undefined", function () {
  assert.throws(function () { canonicalJsonDeep({ score: Number.NaN }); }, /payload_invalid/);
  assert.throws(function () { canonicalJsonDeep({ missing: undefined }); }, /payload_invalid/);
});

function writeKeyFile(root, { secret = SECRET, keyId = KEY_ID, mode = 0o600 } = {}) {
  var path = join(root, "evidence-auth-key.json");
  writeFileSync(path, JSON.stringify({
    schema: "creator_os.evidence_key.v1",
    keyId,
    secret,
  }) + "\n", { mode });
  chmodSync(path, mode);
  return path;
}

test("loads the private key file while preserving environment precedence", function () {
  var root = mkdtempSync(join(tmpdir(), "creator-os-evidence-"));
  var path = writeKeyFile(root);
  var fileEnvironment = { CREATOR_OS_EVIDENCE_AUTH_SECRET_FILE: path };

  assert.equal(loadEvidenceSecret(fileEnvironment), SECRET);
  assert.equal(evidenceSecretPath(fileEnvironment), path);
  assert.equal(loadEvidenceSecret({
    CREATOR_OS_EVIDENCE_AUTH_SECRET: "environment-secret-that-is-at-least-thirty-two-bytes",
    CREATOR_OS_EVIDENCE_AUTH_SECRET_FILE: join(root, "missing.json"),
  }), "environment-secret-that-is-at-least-thirty-two-bytes");
});

test("rejects unsafe, symlinked, and drifted key files", function () {
  var unsafeRoot = mkdtempSync(join(tmpdir(), "creator-os-evidence-"));
  var unsafe = writeKeyFile(unsafeRoot, { mode: 0o640 });
  assert.throws(
    function () { loadEvidenceSecret({ CREATOR_OS_EVIDENCE_AUTH_SECRET_FILE: unsafe }); },
    /permissions_unsafe/,
  );

  var realRoot = mkdtempSync(join(tmpdir(), "creator-os-evidence-"));
  var real = writeKeyFile(realRoot);
  var symlinkRoot = mkdtempSync(join(tmpdir(), "creator-os-evidence-"));
  var symlink = join(symlinkRoot, "key.json");
  symlinkSync(real, symlink);
  assert.throws(
    function () { loadEvidenceSecret({ CREATOR_OS_EVIDENCE_AUTH_SECRET_FILE: symlink }); },
    /key_file_symlink/,
  );

  var driftRoot = mkdtempSync(join(tmpdir(), "creator-os-evidence-"));
  var drift = writeKeyFile(driftRoot, { keyId: "local-0000000000000000" });
  assert.throws(
    function () { loadEvidenceSecret({ CREATOR_OS_EVIDENCE_AUTH_SECRET_FILE: drift }); },
    /key_drift/,
  );
});
