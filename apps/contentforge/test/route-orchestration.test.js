import test from "node:test";
import assert from "node:assert/strict";
import { createForgePostHandler } from "../app/api/forge/route.js";
import { createVariantPackPostHandler } from "../app/api/variant-pack/route.js";

function jsonRequest(url, body) {
  return new Request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function textRequest(url, body) {
  return new Request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}

function lockStub(acquired = true) {
  var calls = { acquire: 0, release: 0 };
  return {
    calls,
    acquireProcessLockImpl: async function () {
      calls.acquire += 1;
      return {
        acquired,
        release: async function () {
          calls.release += 1;
        },
      };
    },
  };
}

test("forge route validates input before invoking video pipeline", async function () {
  var lock = lockStub();
  var pipelineCalls = [];
  var handler = createForgePostHandler({
    acquireProcessLockImpl: lock.acquireProcessLockImpl,
    existsSyncImpl: () => true,
    runPipelineImpl: async function (config, sendEvent) {
      pipelineCalls.push(config);
      sendEvent({ type: "complete", runId: "stub-video" });
    },
  });

  var response = await handler(jsonRequest("http://localhost/api/forge", {
    inputFile: "clip.mp4",
    numEdits: 1,
    spinsPerEdit: 1,
    outputProfile: "organic",
  }));
  var body = await response.text();

  assert.equal(response.status, 200);
  assert.match(body, /stub-video/);
  assert.equal(pipelineCalls.length, 1);
  assert.deepEqual(pipelineCalls[0], {
    inputFile: "uploads/clip.mp4",
    numEdits: 1,
    spinsPerEdit: 1,
    level: undefined,
    flip: false,
    vertical: true,
    outputProfile: "organic",
    variantPreset: "quality",
    variantOptions: {},
    qualityGate: undefined,
  });
  assert.equal(lock.calls.release, 1);
});

test("forge route rejects bad requests and releases the local process lock", async function () {
  var lock = lockStub();
  var handler = createForgePostHandler({
    acquireProcessLockImpl: lock.acquireProcessLockImpl,
  });

  var response = await handler(textRequest("http://localhost/api/forge", "{not json"));

  assert.equal(response.status, 400);
  assert.equal(await response.text(), "Invalid JSON");
  assert.equal(lock.calls.acquire, 1);
  assert.equal(lock.calls.release, 1);
});

test("forge route does not start a second local run while lock is active", async function () {
  var lock = lockStub(false);
  var handler = createForgePostHandler({
    acquireProcessLockImpl: lock.acquireProcessLockImpl,
  });

  var response = await handler(jsonRequest("http://localhost/api/forge", {
    inputFile: "clip.mp4",
    numEdits: 1,
    spinsPerEdit: 1,
  }));

  assert.equal(response.status, 429);
  assert.equal(lock.calls.acquire, 1);
  assert.equal(lock.calls.release, 0);
});

test("variant-pack route runs orchestration through an injectable subprocess boundary", async function () {
  var lock = lockStub();
  var calls = [];
  var handler = createVariantPackPostHandler({
    acquireProcessLockImpl: lock.acquireProcessLockImpl,
    existsSyncImpl: () => true,
    runVariantPackImpl: async function (body) {
      calls.push(body);
      return { runId: "variant-stub", variants: [] };
    },
  });

  var request = jsonRequest("http://localhost/api/variant-pack", {
    source: "source.mp4",
    count: 2,
  });
  var response = await handler(request);
  var body = await response.json();

  assert.equal(response.status, 200);
  assert.deepEqual(body, { runId: "variant-stub", variants: [] });
  assert.equal(calls[0].signal, request.signal);
  delete calls[0].signal;
  assert.deepEqual(calls, [{ source: "source.mp4", count: 2 }]);
  assert.equal(lock.calls.release, 1);
});

test("variant-pack route forwards an aborted request signal to orchestration", async function () {
  var lock = lockStub();
  var seenSignal;
  var handler = createVariantPackPostHandler({
    acquireProcessLockImpl: lock.acquireProcessLockImpl,
    existsSyncImpl: () => true,
    runVariantPackImpl: async function (body) {
      seenSignal = body.signal;
      controller.abort();
      return { runId: "variant-abort-stub", variants: [] };
    },
  });
  var controller = new AbortController();
  var request = new Request("http://localhost/api/variant-pack", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source: "source.mp4" }),
    signal: controller.signal,
  });

  await handler(request);

  assert.equal(seenSignal.aborted, true);
  assert.equal(lock.calls.release, 1);
});

test("variant-pack route reports pipeline failures and still releases the lock", async function () {
  var lock = lockStub();
  var handler = createVariantPackPostHandler({
    acquireProcessLockImpl: lock.acquireProcessLockImpl,
    existsSyncImpl: () => true,
    runVariantPackImpl: async function () {
      throw new Error("ffmpeg failed");
    },
  });

  var response = await handler(jsonRequest("http://localhost/api/variant-pack", {
    source: "source.mp4",
  }));
  var body = await response.json();

  assert.equal(response.status, 500);
  assert.deepEqual(body, { error: "ffmpeg failed" });
  assert.equal(lock.calls.release, 1);
});

test("variant-pack route rejects missing uploads before acquiring the process lock", async function () {
  var lock = lockStub();
  var handler = createVariantPackPostHandler({
    acquireProcessLockImpl: lock.acquireProcessLockImpl,
    existsSyncImpl: () => false,
  });

  var response = await handler(jsonRequest("http://localhost/api/variant-pack", {
    source: "missing.mp4",
  }));
  var body = await response.json();

  assert.equal(response.status, 404);
  assert.deepEqual(body, { error: "Source upload not found" });
  assert.equal(lock.calls.acquire, 0);
});
