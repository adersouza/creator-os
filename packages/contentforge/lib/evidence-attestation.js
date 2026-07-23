import {
  createHash,
  createHmac,
  timingSafeEqual,
} from "node:crypto";
import {
  closeSync,
  constants,
  fstatSync,
  lstatSync,
  openSync,
  readFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import process from "node:process";

export const EVIDENCE_ATTESTATION_SCHEMA = "creator_os.evidence_attestation.v1";
export const EVIDENCE_ATTESTATION_ALGORITHM = "hmac-sha256";
export const EVIDENCE_SECRET_ENV = "CREATOR_OS_EVIDENCE_AUTH_SECRET";
export const EVIDENCE_SECRET_FILE_ENV = "CREATOR_OS_EVIDENCE_AUTH_SECRET_FILE";
export const EVIDENCE_KEY_ID_ENV = "CREATOR_OS_EVIDENCE_AUTH_KEY_ID";
export const EVIDENCE_KEY_FILE_SCHEMA = "creator_os.evidence_key.v1";

const MINIMUM_SECRET_BYTES = 32;
const MAXIMUM_KEY_FILE_BYTES = 4096;

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

function validateSecret(secret) {
  if (Buffer.byteLength(secret, "utf8") < MINIMUM_SECRET_BYTES) {
    throw new Error("evidence_attestation_secret_too_short");
  }
  return secret;
}

function derivedEvidenceKeyId(secret) {
  return `local-${createHash("sha256").update(secret).digest("hex").slice(0, 16)}`;
}

export function evidenceSecretPath(environ = process.env) {
  var home = String(environ.HOME || homedir());
  var configured = String(environ[EVIDENCE_SECRET_FILE_ENV] || "").trim();
  if (configured === "~" || configured.startsWith("~/")) {
    configured = home + configured.slice(1);
  }
  if (configured && !isAbsolute(configured)) {
    throw new Error("evidence_attestation_key_path_not_absolute");
  }
  return resolve(configured || join(home, ".creator-os", "credentials", "evidence-auth-key.json"));
}

function validateKeyFileStat(fileStat) {
  if (!fileStat.isFile()) throw new Error("evidence_attestation_key_file_not_regular");
  if ((fileStat.mode & 0o077) !== 0) {
    throw new Error("evidence_attestation_key_file_permissions_unsafe");
  }
  if (typeof process.geteuid === "function" && fileStat.uid !== process.geteuid()) {
    throw new Error("evidence_attestation_key_file_owner_mismatch");
  }
  if (fileStat.size > MAXIMUM_KEY_FILE_BYTES) {
    throw new Error("evidence_attestation_key_file_too_large");
  }
}

function decodeKeyFile(raw) {
  var decoded;
  try {
    decoded = JSON.parse(raw.toString("utf8"));
  } catch {
    throw new Error("evidence_attestation_key_file_invalid");
  }
  if (!validRecord(decoded)
    || canonicalJsonDeep(Object.keys(decoded).sort()) !== canonicalJsonDeep(["keyId", "schema", "secret"])) {
    throw new Error("evidence_attestation_key_file_invalid");
  }
  if (decoded.schema !== EVIDENCE_KEY_FILE_SCHEMA) {
    throw new Error("evidence_attestation_key_file_version_invalid");
  }
  var secret = validateSecret(String(decoded.secret || ""));
  var derived = derivedEvidenceKeyId(secret);
  if (decoded.keyId !== derived) throw new Error("evidence_attestation_key_drift");
  return { secret, keyId: derived };
}

function loadEvidenceKeyFile(path) {
  var pathStat;
  try {
    pathStat = lstatSync(path);
  } catch (error) {
    if (error?.code === "ENOENT") throw new Error("evidence_attestation_key_file_missing");
    throw new Error("evidence_attestation_key_file_unreadable");
  }
  if (pathStat.isSymbolicLink()) throw new Error("evidence_attestation_key_file_symlink");
  validateKeyFileStat(pathStat);
  var descriptor;
  try {
    descriptor = openSync(path, constants.O_RDONLY | (constants.O_NOFOLLOW || 0));
  } catch {
    throw new Error("evidence_attestation_key_file_unreadable");
  }
  try {
    var openedStat = fstatSync(descriptor);
    validateKeyFileStat(openedStat);
    if (openedStat.dev !== pathStat.dev || openedStat.ino !== pathStat.ino) {
      throw new Error("evidence_attestation_key_file_changed");
    }
    return decodeKeyFile(readFileSync(descriptor));
  } finally {
    closeSync(descriptor);
  }
}

export function loadEvidenceSecret(environ = process.env) {
  if (Object.prototype.hasOwnProperty.call(environ, EVIDENCE_SECRET_ENV)) {
    return validateSecret(String(environ[EVIDENCE_SECRET_ENV] || ""));
  }
  return loadEvidenceKeyFile(evidenceSecretPath(environ)).secret;
}

export function evidenceKeyId(secret, environ = process.env) {
  validateSecret(secret);
  var derived = derivedEvidenceKeyId(secret);
  var configured = String(environ[EVIDENCE_KEY_ID_ENV] || "").trim();
  if (configured) {
    if (configured.length > 128) throw new Error("evidence_attestation_key_id_invalid");
    if (configured !== derived) throw new Error("evidence_attestation_key_drift");
  }
  return derived;
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
