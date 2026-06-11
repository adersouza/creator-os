import { describe, it, expect, vi, beforeEach } from "vitest";

// ============================================================================
// Setup mocks
// ============================================================================

const mockDecrypt = vi.fn();
vi.mock("../../api/_lib/encryption.js", () => ({
  decrypt: (...args: any[]) => mockDecrypt(...args),
}));

vi.mock("../../api/_lib/logger.js", () => ({
  logger: {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

const mockSanitizeHtml = vi.fn((s: string) => s); // pass-through by default
vi.mock("../../api/_lib/sanitize.js", () => ({
  sanitizeHtml: (s: string) => mockSanitizeHtml(s),
}));

// Mock global fetch
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

const { publishThreadChain } = await import(
  "../../api/_lib/threadPublisher.js"
);

// ============================================================================
// Helpers
// ============================================================================

function okResponse(data: any) {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(data),
  });
}

function errorResponse(status: number, data: any) {
  return Promise.resolve({
    ok: false,
    status,
    json: () => Promise.resolve(data),
  });
}

// ============================================================================
// Input Validation
// ============================================================================

describe("publishThreadChain — input validation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDecrypt.mockReturnValue("decrypted-token");
    mockSanitizeHtml.mockImplementation((s: string) => s);
  });

  it("returns error when parts is empty", async () => {
    const result = await publishThreadChain("enc-token", "user-1", []);
    expect(result.success).toBe(false);
    expect(result.error).toContain("No parts provided");
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("returns error when parts is undefined-like", async () => {
    const result = await publishThreadChain("enc-token", "user-1", null as any);
    expect(result.success).toBe(false);
    expect(result.error).toContain("No parts");
  });

  it("returns error when token decrypt fails", async () => {
    mockDecrypt.mockImplementation(() => {
      throw new Error("Invalid ciphertext");
    });

    const result = await publishThreadChain("bad-token", "user-1", [
      "Hello world",
    ]);
    expect(result.success).toBe(false);
    expect(result.error).toContain("Token decrypt failed");
    expect(result.error).toContain("Invalid ciphertext");
    expect(mockFetch).not.toHaveBeenCalled();
  });
});

// ============================================================================
// Successful Publishing
// ============================================================================

describe("publishThreadChain — successful flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDecrypt.mockReturnValue("decrypted-token");
    mockSanitizeHtml.mockImplementation((s: string) => s);
  });

  it("publishes a single-part thread", async () => {
    // Create container → returns ID
    mockFetch
      .mockReturnValueOnce(okResponse({ id: "container-1" }))
      // Publish → returns ID
      .mockReturnValueOnce(okResponse({ id: "post-1" }));

    const result = await publishThreadChain("enc", "user-1", ["Hello world"]);

    expect(result.success).toBe(true);
    expect(result.rootThreadId).toBe("post-1");
    expect(result.allPostIds).toEqual(["post-1"]);
    expect(result.error).toBeUndefined();
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("publishes a multi-part thread chain with reply_to_id", async () => {
    mockFetch
      // Part 1: container + publish
      .mockReturnValueOnce(okResponse({ id: "c-1" }))
      .mockReturnValueOnce(okResponse({ id: "post-1" }))
      // Part 2: container + publish
      .mockReturnValueOnce(okResponse({ id: "c-2" }))
      .mockReturnValueOnce(okResponse({ id: "post-2" }))
      // Part 3: container + publish
      .mockReturnValueOnce(okResponse({ id: "c-3" }))
      .mockReturnValueOnce(okResponse({ id: "post-3" }));

    const result = await publishThreadChain("enc", "user-1", [
      "Part 1",
      "Part 2",
      "Part 3",
    ]);

    expect(result.success).toBe(true);
    expect(result.rootThreadId).toBe("post-1");
    expect(result.allPostIds).toEqual(["post-1", "post-2", "post-3"]);

    // Verify first container does NOT have reply_to_id
    const firstCreateCall = mockFetch.mock.calls[0];
    const firstBody = firstCreateCall[1].body as URLSearchParams;
    expect(firstBody.get("reply_to_id")).toBeNull();

    // Verify second container HAS reply_to_id pointing to first post
    const secondCreateCall = mockFetch.mock.calls[2];
    const secondBody = secondCreateCall[1].body as URLSearchParams;
    expect(secondBody.get("reply_to_id")).toBe("post-1");

    // Third container chains to second post
    const thirdCreateCall = mockFetch.mock.calls[4];
    const thirdBody = thirdCreateCall[1].body as URLSearchParams;
    expect(thirdBody.get("reply_to_id")).toBe("post-2");
  });

  it("sets topic_tag only on the root post", async () => {
    mockFetch
      .mockReturnValueOnce(okResponse({ id: "c-1" }))
      .mockReturnValueOnce(okResponse({ id: "post-1" }))
      .mockReturnValueOnce(okResponse({ id: "c-2" }))
      .mockReturnValueOnce(okResponse({ id: "post-2" }));

    await publishThreadChain("enc", "user-1", ["Part 1", "Part 2"], "tech");

    // Root has topic_tag
    const rootBody = mockFetch.mock.calls[0][1].body as URLSearchParams;
    expect(rootBody.get("topic_tag")).toBe("tech");

    // Child does NOT have topic_tag
    const childBody = mockFetch.mock.calls[2][1].body as URLSearchParams;
    expect(childBody.get("topic_tag")).toBeNull();
  });

  it("sends correct API URLs", async () => {
    mockFetch
      .mockReturnValueOnce(okResponse({ id: "c-1" }))
      .mockReturnValueOnce(okResponse({ id: "post-1" }));

    await publishThreadChain("enc", "user-42", ["Hello"]);

    // Container creation URL
    expect(mockFetch.mock.calls[0][0]).toBe(
      "https://graph.threads.net/v1.0/user-42/threads"
    );

    // Publish URL
    expect(mockFetch.mock.calls[1][0]).toBe(
      "https://graph.threads.net/v1.0/user-42/threads_publish"
    );
  });

  it("uses Bearer token in Authorization header", async () => {
    mockDecrypt.mockReturnValue("my-secret-token");
    mockFetch
      .mockReturnValueOnce(okResponse({ id: "c-1" }))
      .mockReturnValueOnce(okResponse({ id: "post-1" }));

    await publishThreadChain("enc", "user-1", ["Hello"]);

    const headers = mockFetch.mock.calls[0][1].headers;
    expect(headers.Authorization).toBe("Bearer my-secret-token");
  });

  it("sanitizes HTML from all parts", async () => {
    mockSanitizeHtml.mockImplementation((s: string) =>
      s.replace(/<[^>]+>/g, "")
    );
    mockFetch
      .mockReturnValueOnce(okResponse({ id: "c-1" }))
      .mockReturnValueOnce(okResponse({ id: "post-1" }));

    await publishThreadChain("enc", "user-1", ["<b>Bold</b> text"]);

    expect(mockSanitizeHtml).toHaveBeenCalledWith("<b>Bold</b> text");
    const body = mockFetch.mock.calls[0][1].body as URLSearchParams;
    expect(body.get("text")).toBe("Bold text");
  });

  it("skips empty parts after sanitization", async () => {
    mockSanitizeHtml
      .mockReturnValueOnce("Good part")
      .mockReturnValueOnce("") // empty after sanitize
      .mockReturnValueOnce("Another good part");

    mockFetch
      .mockReturnValueOnce(okResponse({ id: "c-1" }))
      .mockReturnValueOnce(okResponse({ id: "post-1" }))
      .mockReturnValueOnce(okResponse({ id: "c-2" }))
      .mockReturnValueOnce(okResponse({ id: "post-2" }));

    const result = await publishThreadChain("enc", "user-1", [
      "Good part",
      "<script>bad</script>",
      "Another good part",
    ]);

    expect(result.success).toBe(true);
    // Only 2 posts published (second was skipped due to empty sanitized content)
    expect(result.allPostIds).toEqual(["post-1", "post-2"]);
    expect(mockFetch).toHaveBeenCalledTimes(4); // 2 containers + 2 publishes
  });
});

// ============================================================================
// Error Handling & Partial Success
// ============================================================================

describe("publishThreadChain — error handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDecrypt.mockReturnValue("token");
    mockSanitizeHtml.mockImplementation((s: string) => s);
  });

  it("returns failure when first container creation fails", async () => {
    mockFetch.mockReturnValueOnce(
      errorResponse(400, { error: { message: "Rate limited" } })
    );

    const result = await publishThreadChain("enc", "user-1", ["Hello"]);
    expect(result.success).toBe(false);
    expect(result.error).toContain("Container 1 failed");
    expect(result.error).toContain("Rate limited");
  });

  it("returns failure when first publish fails", async () => {
    mockFetch
      .mockReturnValueOnce(okResponse({ id: "c-1" })) // container OK
      .mockReturnValueOnce(
        errorResponse(500, { error: { message: "Server error" } })
      ); // publish fails

    const result = await publishThreadChain("enc", "user-1", ["Hello"]);
    expect(result.success).toBe(false);
    expect(result.error).toContain("Publish 1 failed");
    expect(result.error).toContain("Server error");
  });

  it("returns partial success when second part container fails", async () => {
    mockFetch
      // Part 1: success
      .mockReturnValueOnce(okResponse({ id: "c-1" }))
      .mockReturnValueOnce(okResponse({ id: "post-1" }))
      // Part 2: container fails
      .mockReturnValueOnce(
        errorResponse(400, { error: { message: "Content too long" } })
      );

    const result = await publishThreadChain("enc", "user-1", [
      "Part 1",
      "Part 2 is too long...",
    ]);

    expect(result.success).toBe(true); // Partial success
    expect(result.rootThreadId).toBe("post-1");
    expect(result.allPostIds).toEqual(["post-1"]);
    expect(result.error).toContain("Partial");
    expect(result.error).toContain("failed at part 2");
  });

  it("returns partial success when third part publish fails", async () => {
    mockFetch
      // Part 1: success
      .mockReturnValueOnce(okResponse({ id: "c-1" }))
      .mockReturnValueOnce(okResponse({ id: "post-1" }))
      // Part 2: success
      .mockReturnValueOnce(okResponse({ id: "c-2" }))
      .mockReturnValueOnce(okResponse({ id: "post-2" }))
      // Part 3: container OK, publish fails
      .mockReturnValueOnce(okResponse({ id: "c-3" }))
      .mockReturnValueOnce(
        errorResponse(500, { error: { message: "Meta transient 500" } })
      );

    const result = await publishThreadChain("enc", "user-1", [
      "Part 1",
      "Part 2",
      "Part 3",
    ]);

    expect(result.success).toBe(true);
    expect(result.allPostIds).toEqual(["post-1", "post-2"]);
    expect(result.error).toContain("Partial");
    expect(result.error).toContain("part 3");
  });

  it("handles fetch exceptions (network failure)", async () => {
    mockFetch.mockRejectedValue(new Error("Network timeout"));

    const result = await publishThreadChain("enc", "user-1", ["Hello"]);
    expect(result.success).toBe(false);
    expect(result.error).toContain("Exception at part 1");
    expect(result.error).toContain("Network timeout");
  });

  it("handles fetch exception with partial success", async () => {
    mockFetch
      // Part 1: success
      .mockReturnValueOnce(okResponse({ id: "c-1" }))
      .mockReturnValueOnce(okResponse({ id: "post-1" }))
      // Part 2: network failure
      .mockRejectedValueOnce(new Error("DNS lookup failed"));

    const result = await publishThreadChain("enc", "user-1", [
      "Part 1",
      "Part 2",
    ]);

    expect(result.success).toBe(true); // Partial
    expect(result.rootThreadId).toBe("post-1");
    expect(result.allPostIds).toEqual(["post-1"]);
    expect(result.error).toContain("Partial");
  });

  it("handles missing error.message in API response", async () => {
    mockFetch.mockReturnValueOnce(
      errorResponse(400, { error: {} }) // no message field
    );

    const result = await publishThreadChain("enc", "user-1", ["Hello"]);
    expect(result.success).toBe(false);
    expect(result.error).toContain("Unknown container error");
  });

  it("handles container returning no id (non-standard response)", async () => {
    mockFetch.mockReturnValueOnce(
      okResponse({ status: "created" }) // missing id field
    );

    const result = await publishThreadChain("enc", "user-1", ["Hello"]);
    expect(result.success).toBe(false);
    expect(result.error).toContain("Container 1 failed");
  });

  it("handles publish returning no id", async () => {
    mockFetch
      .mockReturnValueOnce(okResponse({ id: "c-1" }))
      .mockReturnValueOnce(okResponse({ success: true })); // missing id

    const result = await publishThreadChain("enc", "user-1", ["Hello"]);
    expect(result.success).toBe(false);
    expect(result.error).toContain("Publish 1 failed");
  });

  it("returns no-parts-published when all parts sanitize to empty", async () => {
    mockSanitizeHtml.mockReturnValue("");

    const result = await publishThreadChain("enc", "user-1", [
      "<script>1</script>",
      "<script>2</script>",
    ]);

    expect(result.success).toBe(false);
    expect(result.error).toContain("No parts were published");
    expect(mockFetch).not.toHaveBeenCalled();
  });
});

// ============================================================================
// Request Format
// ============================================================================

describe("publishThreadChain — request format", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDecrypt.mockReturnValue("token");
    mockSanitizeHtml.mockImplementation((s: string) => s);
  });

  it("sends POST with form-urlencoded content type", async () => {
    mockFetch
      .mockReturnValueOnce(okResponse({ id: "c-1" }))
      .mockReturnValueOnce(okResponse({ id: "post-1" }));

    await publishThreadChain("enc", "user-1", ["Hello"]);

    const createCall = mockFetch.mock.calls[0];
    expect(createCall[1].method).toBe("POST");
    expect(createCall[1].headers["Content-Type"]).toBe(
      "application/x-www-form-urlencoded"
    );
  });

  it("sets media_type to TEXT for container", async () => {
    mockFetch
      .mockReturnValueOnce(okResponse({ id: "c-1" }))
      .mockReturnValueOnce(okResponse({ id: "post-1" }));

    await publishThreadChain("enc", "user-1", ["Hello"]);

    const body = mockFetch.mock.calls[0][1].body as URLSearchParams;
    expect(body.get("media_type")).toBe("TEXT");
    expect(body.get("text")).toBe("Hello");
  });

  it("sends creation_id in publish step", async () => {
    mockFetch
      .mockReturnValueOnce(okResponse({ id: "container-abc" }))
      .mockReturnValueOnce(okResponse({ id: "post-1" }));

    await publishThreadChain("enc", "user-1", ["Hello"]);

    const publishBody = mockFetch.mock.calls[1][1].body as URLSearchParams;
    expect(publishBody.get("creation_id")).toBe("container-abc");
  });

  it("does not set topic_tag when not provided", async () => {
    mockFetch
      .mockReturnValueOnce(okResponse({ id: "c-1" }))
      .mockReturnValueOnce(okResponse({ id: "post-1" }));

    await publishThreadChain("enc", "user-1", ["Hello"]);

    const body = mockFetch.mock.calls[0][1].body as URLSearchParams;
    expect(body.get("topic_tag")).toBeNull();
  });

  it("does not set topic_tag when null", async () => {
    mockFetch
      .mockReturnValueOnce(okResponse({ id: "c-1" }))
      .mockReturnValueOnce(okResponse({ id: "post-1" }));

    await publishThreadChain("enc", "user-1", ["Hello"], null);

    const body = mockFetch.mock.calls[0][1].body as URLSearchParams;
    expect(body.get("topic_tag")).toBeNull();
  });
});
