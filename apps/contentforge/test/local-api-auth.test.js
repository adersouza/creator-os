import test from "node:test";
import assert from "node:assert/strict";
import { authorizeContentForgeRequest } from "../lib/local-api-auth.js";

function request(url, headers = {}) {
  return { url, headers: new Headers(headers) };
}

test("ContentForge API auth rejects missing token by default", function () {
  var result = authorizeContentForgeRequest(
    request("http://127.0.0.1:3002/api/runs"),
    {}
  );

  assert.equal(result.ok, false);
  assert.equal(result.status, 401);
});

test("ContentForge API auth accepts bearer token", function () {
  var result = authorizeContentForgeRequest(
    request("http://contentforge.local/api/runs", {
      authorization: "Bearer test-token",
    }),
    { CREATOR_OS_API_TOKEN: "test-token" }
  );

  assert.equal(result.ok, true);
});

test("ContentForge API auth accepts explicit loopback dev mode only locally", function () {
  assert.equal(
    authorizeContentForgeRequest(
      request("http://127.0.0.1:3002/api/runs", {
        host: "127.0.0.1:3002",
        origin: "http://127.0.0.1:3002",
      }),
      { ALLOW_INSECURE_LOCAL: "1" }
    ).ok,
    true
  );
  assert.equal(
    authorizeContentForgeRequest(
      request("http://evil.test/api/runs", {
        host: "evil.test",
        origin: "http://evil.test",
      }),
      { ALLOW_INSECURE_LOCAL: "1" }
    ).ok,
    false
  );
});
