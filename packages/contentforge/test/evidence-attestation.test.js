import assert from "node:assert/strict";
import { createHash, createHmac } from "node:crypto";
import test from "node:test";

import {
  canonicalJsonDeep,
  evidenceKeyId,
  evidencePayloadFingerprint,
  signEvidenceAttestation,
  verifyEvidenceAttestation,
} from "../lib/evidence-attestation.js";

const SECRET = "contentforge-attestation-test-secret-0123456789";
const ISSUED_AT = "2026-01-02T03:04:05Z";
const ENVIRONMENT = {
  CREATOR_OS_EVIDENCE_AUTH_SECRET: SECRET,
  CREATOR_OS_EVIDENCE_AUTH_KEY_ID: "test-contentforge-key",
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
  assert.equal(attestation.keyId, "test-contentforge-key");
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
    /must contain at least 32 bytes/,
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
