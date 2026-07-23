import {
  createHash,
  createHmac,
  timingSafeEqual,
} from "node:crypto";
import process from "node:process";

export const EVIDENCE_ATTESTATION_SCHEMA = "creator_os.evidence_attestation.v1";
export const EVIDENCE_ATTESTATION_ALGORITHM = "hmac-sha256";
export const EVIDENCE_SECRET_ENV = "CREATOR_OS_EVIDENCE_AUTH_SECRET";
export const EVIDENCE_KEY_ID_ENV = "CREATOR_OS_EVIDENCE_AUTH_KEY_ID";

const RFC3339_WITH_ZONE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const ATTESTATION_FIELDS = Object.freeze([
  "algorithm",
  "issuedAt",
  "issuer",
  "keyId",
  "payloadFingerprint",
  "schema",
  "signature",
]);

function validRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Canonical recursive JSON shared by Creator OS evidence signatures. */
export function canonicalJsonDeep(value) {
  if (value === null) return "null";
  if (typeof value === "string" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("evidence_attestation_payload_invalid");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return "[" + value.map(canonicalJsonDeep).join(",") + "]";
  }
  if (validRecord(value)) {
    var keys = Object.keys(value).sort();
    return "{" + keys.map(function (key) {
      if (value[key] === undefined) throw new Error("evidence_attestation_payload_invalid");
      return JSON.stringify(key) + ":" + canonicalJsonDeep(value[key]);
    }).join(",") + "}";
  }
  throw new Error("evidence_attestation_payload_invalid");
}

export function evidencePayloadFingerprint(payload) {
  if (!validRecord(payload)) throw new Error("evidence_attestation_payload_invalid");
  return createHash("sha256").update(canonicalJsonDeep(payload)).digest("hex");
}

export function loadEvidenceSecret(environ = process.env) {
  var secret = String(environ[EVIDENCE_SECRET_ENV] || "");
  if (Buffer.byteLength(secret, "utf8") < 32) {
    throw new Error(`${EVIDENCE_SECRET_ENV} must contain at least 32 bytes`);
  }
  return secret;
}

export function evidenceKeyId(secret, environ = process.env) {
  var configured = String(environ[EVIDENCE_KEY_ID_ENV] || "").trim();
  if (configured) {
    if (configured.length > 128) throw new Error("evidence_attestation_key_id_invalid");
    return configured;
  }
  return `local-${createHash("sha256").update(secret).digest("hex").slice(0, 16)}`;
}

function requireTimestamp(value, code, now = Date.now()) {
  if (typeof value !== "string" || !RFC3339_WITH_ZONE.test(value) || Number.isNaN(Date.parse(value))) {
    throw new Error(`${code}_invalid`);
  }
  if (Date.parse(value) > now) throw new Error(`${code}_from_future`);
}

function signatureFor(core, secret) {
  return createHmac("sha256", secret).update(canonicalJsonDeep(core)).digest("hex");
}

export function signEvidenceAttestation(payload, {
  issuer,
  issuedAt,
  environ = process.env,
} = {}) {
  if (!validRecord(payload)) throw new Error("evidence_attestation_payload_invalid");
  var secret = loadEvidenceSecret(environ);
  var normalizedIssuer = String(issuer || "").trim();
  if (!normalizedIssuer) throw new Error("evidence_attestation_issuer_missing");
  requireTimestamp(issuedAt, "evidence_attestation_issued_at");
  var core = {
    schema: EVIDENCE_ATTESTATION_SCHEMA,
    algorithm: EVIDENCE_ATTESTATION_ALGORITHM,
    issuer: normalizedIssuer,
    keyId: evidenceKeyId(secret, environ),
    issuedAt,
    payloadFingerprint: evidencePayloadFingerprint(payload),
  };
  return { ...core, signature: signatureFor(core, secret) };
}

export function verifyEvidenceAttestation(attestation, payload, {
  expectedIssuer,
  expectedIssuedAt = null,
  environ = process.env,
  now = Date.now(),
} = {}) {
  if (!validRecord(attestation) || !validRecord(payload)) {
    throw new Error("evidence_attestation_shape_invalid");
  }
  var fields = Object.keys(attestation).sort();
  if (canonicalJsonDeep(fields) !== canonicalJsonDeep(ATTESTATION_FIELDS)) {
    throw new Error("evidence_attestation_shape_invalid");
  }
  var secret = loadEvidenceSecret(environ);
  if (attestation.schema !== EVIDENCE_ATTESTATION_SCHEMA
    || attestation.algorithm !== EVIDENCE_ATTESTATION_ALGORITHM
    || attestation.issuer !== expectedIssuer) {
    throw new Error("evidence_attestation_identity_mismatch");
  }
  if (attestation.keyId !== evidenceKeyId(secret, environ)) {
    throw new Error("evidence_attestation_key_mismatch");
  }
  requireTimestamp(attestation.issuedAt, "evidence_attestation_issued_at", now);
  if (expectedIssuedAt !== null && attestation.issuedAt !== expectedIssuedAt) {
    throw new Error("evidence_attestation_issued_at_mismatch");
  }
  if (attestation.payloadFingerprint !== evidencePayloadFingerprint(payload)) {
    throw new Error("evidence_attestation_payload_mismatch");
  }
  if (!/^[a-f0-9]{64}$/.test(attestation.signature)) {
    throw new Error("evidence_attestation_signature_invalid");
  }
  var unsigned = { ...attestation };
  delete unsigned.signature;
  var expected = signatureFor(unsigned, secret);
  if (!timingSafeEqual(Buffer.from(attestation.signature, "hex"), Buffer.from(expected, "hex"))) {
    throw new Error("evidence_attestation_signature_invalid");
  }
  return { ...attestation };
}
