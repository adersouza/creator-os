import { describe, it, expect, vi, beforeEach } from "vitest";

// ============================================================================
// Setup mocks
// ============================================================================

const mockDecrypt = vi.fn();
vi.mock("../../api/_lib/encryption.js", () => ({
  decrypt: (...args: any[]) => mockDecrypt(...args),
}));

// Chainable Supabase query builder mock
function createQueryBuilder(returnData: any = null) {
  const builder: any = {};
  builder.from = vi.fn().mockReturnValue(builder);
  builder.select = vi.fn().mockReturnValue(builder);
  builder.eq = vi.fn().mockReturnValue(builder);
  builder.or = vi.fn().mockReturnValue(builder);
  builder.not = vi.fn().mockReturnValue(builder);
  builder.limit = vi.fn().mockReturnValue(builder);
  builder.in = vi.fn().mockReturnValue(builder);
  builder.maybeSingle = vi.fn().mockResolvedValue({ data: returnData, error: null });
  return builder;
}

let mockQueryBuilder: ReturnType<typeof createQueryBuilder>;

vi.mock("../../api/_lib/supabase.js", () => ({
  getSupabaseAny: () => mockQueryBuilder,
}));

const {
  getDecryptedThreadsToken,
  getDecryptedThreadsTokenByUser,
  getDecryptedIGToken,
  getDecryptedIGTokenByUser,
} = await import("../../api/_lib/tokenAccess.js");

// ============================================================================
// Tests — Threads Token Access
// ============================================================================

describe("getDecryptedThreadsToken", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns decrypted token for active account", async () => {
    const account = {
      id: "acc-123",
      username: "testuser",
      threads_user_id: "tu-456",
      threads_access_token_encrypted: "encrypted-blob",
      needs_reauth: false,
      is_active: true,
    };
    mockQueryBuilder = createQueryBuilder(account);
    mockDecrypt.mockReturnValue("decrypted-access-token");

    const result = await getDecryptedThreadsToken("acc-123");
    expect(result).toEqual({
      token: "decrypted-access-token",
      threadsUserId: "tu-456",
      accountId: "acc-123",
      username: "testuser",
    });
    expect(mockDecrypt).toHaveBeenCalledWith("encrypted-blob");
  });

  it("returns null when account not found", async () => {
    mockQueryBuilder = createQueryBuilder(null);

    const result = await getDecryptedThreadsToken("nonexistent");
    expect(result).toBeNull();
  });

  it("returns null when account needs_reauth is true", async () => {
    const account = {
      id: "acc-123",
      username: "testuser",
      threads_user_id: "tu-456",
      threads_access_token_encrypted: "encrypted-blob",
      needs_reauth: true,
      is_active: true,
    };
    mockQueryBuilder = createQueryBuilder(account);

    const result = await getDecryptedThreadsToken("acc-123");
    expect(result).toBeNull();
    expect(mockDecrypt).not.toHaveBeenCalled();
  });

  it("returns null when account is_active is false", async () => {
    const account = {
      id: "acc-123",
      username: "testuser",
      threads_user_id: "tu-456",
      threads_access_token_encrypted: "encrypted-blob",
      needs_reauth: false,
      is_active: false,
    };
    mockQueryBuilder = createQueryBuilder(account);

    const result = await getDecryptedThreadsToken("acc-123");
    expect(result).toBeNull();
    expect(mockDecrypt).not.toHaveBeenCalled();
  });

  it("returns null when encrypted token field is null", async () => {
    const account = {
      id: "acc-123",
      username: "testuser",
      threads_user_id: "tu-456",
      threads_access_token_encrypted: null,
      needs_reauth: false,
      is_active: true,
    };
    mockQueryBuilder = createQueryBuilder(account);

    const result = await getDecryptedThreadsToken("acc-123");
    expect(result).toBeNull();
  });

  it("returns null when decrypt returns empty/falsy", async () => {
    const account = {
      id: "acc-123",
      username: "testuser",
      threads_user_id: "tu-456",
      threads_access_token_encrypted: "encrypted-blob",
      needs_reauth: false,
      is_active: true,
    };
    mockQueryBuilder = createQueryBuilder(account);
    mockDecrypt.mockReturnValue("");

    const result = await getDecryptedThreadsToken("acc-123");
    expect(result).toBeNull();
  });

  it("returns empty string username when username is null", async () => {
    const account = {
      id: "acc-123",
      username: null,
      threads_user_id: "tu-456",
      threads_access_token_encrypted: "encrypted-blob",
      needs_reauth: false,
      is_active: true,
    };
    mockQueryBuilder = createQueryBuilder(account);
    mockDecrypt.mockReturnValue("token");

    const result = await getDecryptedThreadsToken("acc-123");
    expect(result?.username).toBe("");
  });
});

// ============================================================================
// Tests — Threads Token by User
// ============================================================================

describe("getDecryptedThreadsTokenByUser", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns decrypted token for first active account by user", async () => {
    const account = {
      id: "acc-789",
      username: "userAccount",
      threads_user_id: "tu-111",
      threads_access_token_encrypted: "enc-token",
    };
    mockQueryBuilder = createQueryBuilder(account);
    mockDecrypt.mockReturnValue("real-token");

    const result = await getDecryptedThreadsTokenByUser("user-id-1");
    expect(result).toEqual({
      token: "real-token",
      threadsUserId: "tu-111",
      accountId: "acc-789",
      username: "userAccount",
    });
    expect(mockQueryBuilder.eq).toHaveBeenCalledWith("user_id", "user-id-1");
    expect(mockQueryBuilder.eq).toHaveBeenCalledWith("is_active", true);
  });

  it("returns null when no account has encrypted token", async () => {
    const account = {
      id: "acc-789",
      username: "userAccount",
      threads_user_id: "tu-111",
      threads_access_token_encrypted: null,
    };
    mockQueryBuilder = createQueryBuilder(account);

    const result = await getDecryptedThreadsTokenByUser("user-id-1");
    expect(result).toBeNull();
  });

  it("returns null when no matching account found", async () => {
    mockQueryBuilder = createQueryBuilder(null);

    const result = await getDecryptedThreadsTokenByUser("no-such-user");
    expect(result).toBeNull();
  });

  it("returns null when decrypt fails (returns falsy)", async () => {
    const account = {
      id: "acc-789",
      username: "userAccount",
      threads_user_id: "tu-111",
      threads_access_token_encrypted: "broken-blob",
    };
    mockQueryBuilder = createQueryBuilder(account);
    mockDecrypt.mockReturnValue(null);

    const result = await getDecryptedThreadsTokenByUser("user-id-1");
    expect(result).toBeNull();
  });
});

// ============================================================================
// Tests — Instagram Token Access
// ============================================================================

describe("getDecryptedIGToken", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns decrypted IG token with FB page token", async () => {
    const account = {
      id: "ig-001",
      username: "ig_user",
      instagram_user_id: "igu-222",
      instagram_access_token_encrypted: "enc-ig-token",
      facebook_page_access_token_encrypted: "enc-fb-page-token",
      login_type: "fb_login",
      needs_reauth: false,
      is_active: true,
    };
    mockQueryBuilder = createQueryBuilder(account);
    mockDecrypt
      .mockReturnValueOnce("decrypted-ig-token")
      .mockReturnValueOnce("decrypted-fb-page-token");

    const result = await getDecryptedIGToken("ig-001");
    expect(result).toEqual({
      token: "decrypted-ig-token",
      igUserId: "igu-222",
      accountId: "ig-001",
      username: "ig_user",
      loginType: "fb_login",
      fbPageToken: "decrypted-fb-page-token",
    });
    expect(mockDecrypt).toHaveBeenCalledTimes(2);
  });

  it("returns token without fbPageToken when FB token is absent", async () => {
    const account = {
      id: "ig-002",
      username: "ig_basic_user",
      instagram_user_id: "igu-333",
      instagram_access_token_encrypted: "enc-ig-token",
      facebook_page_access_token_encrypted: null,
      login_type: "ig_basic",
      needs_reauth: false,
      is_active: true,
    };
    mockQueryBuilder = createQueryBuilder(account);
    mockDecrypt.mockReturnValue("decrypted-ig-token");

    const result = await getDecryptedIGToken("ig-002");
    expect(result?.fbPageToken).toBeUndefined();
    expect(result?.loginType).toBe("ig_basic");
  });

  it("returns undefined for fbPageToken when FB token decrypt fails", async () => {
    const account = {
      id: "ig-003",
      username: "ig_user",
      instagram_user_id: "igu-444",
      instagram_access_token_encrypted: "enc-ig-token",
      facebook_page_access_token_encrypted: "enc-fb-bad",
      login_type: "fb_login",
      needs_reauth: false,
      is_active: true,
    };
    mockQueryBuilder = createQueryBuilder(account);
    mockDecrypt
      .mockReturnValueOnce("decrypted-ig-token")
      .mockReturnValueOnce(""); // falsy → becomes undefined

    const result = await getDecryptedIGToken("ig-003");
    expect(result?.fbPageToken).toBeUndefined();
  });

  it("returns null when IG account needs_reauth", async () => {
    const account = {
      id: "ig-004",
      username: "ig_user",
      instagram_user_id: "igu-555",
      instagram_access_token_encrypted: "enc-token",
      facebook_page_access_token_encrypted: null,
      login_type: "ig_basic",
      needs_reauth: true,
      is_active: true,
    };
    mockQueryBuilder = createQueryBuilder(account);

    const result = await getDecryptedIGToken("ig-004");
    expect(result).toBeNull();
    expect(mockDecrypt).not.toHaveBeenCalled();
  });

  it("returns null when IG account is inactive", async () => {
    const account = {
      id: "ig-005",
      username: "ig_user",
      instagram_user_id: "igu-666",
      instagram_access_token_encrypted: "enc-token",
      facebook_page_access_token_encrypted: null,
      login_type: "ig_basic",
      needs_reauth: false,
      is_active: false,
    };
    mockQueryBuilder = createQueryBuilder(account);

    const result = await getDecryptedIGToken("ig-005");
    expect(result).toBeNull();
  });

  it("returns null when IG encrypted token is null", async () => {
    const account = {
      id: "ig-006",
      username: "ig_user",
      instagram_user_id: "igu-777",
      instagram_access_token_encrypted: null,
      facebook_page_access_token_encrypted: null,
      login_type: "ig_basic",
      needs_reauth: false,
      is_active: true,
    };
    mockQueryBuilder = createQueryBuilder(account);

    const result = await getDecryptedIGToken("ig-006");
    expect(result).toBeNull();
  });

  it("defaults loginType to ig_basic when null", async () => {
    const account = {
      id: "ig-007",
      username: "ig_user",
      instagram_user_id: "igu-888",
      instagram_access_token_encrypted: "enc-token",
      facebook_page_access_token_encrypted: null,
      login_type: null,
      needs_reauth: false,
      is_active: true,
    };
    mockQueryBuilder = createQueryBuilder(account);
    mockDecrypt.mockReturnValue("token");

    const result = await getDecryptedIGToken("ig-007");
    expect(result?.loginType).toBe("ig_basic");
  });
});

// ============================================================================
// Tests — IG Token by User
// ============================================================================

describe("getDecryptedIGTokenByUser", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns decrypted IG token by user with FB page token", async () => {
    const account = {
      id: "ig-100",
      username: "ig_by_user",
      instagram_user_id: "igu-900",
      instagram_access_token_encrypted: "enc-ig",
      facebook_page_access_token_encrypted: "enc-fb",
      login_type: "fb_login",
    };
    mockQueryBuilder = createQueryBuilder(account);
    mockDecrypt
      .mockReturnValueOnce("ig-token")
      .mockReturnValueOnce("fb-token");

    const result = await getDecryptedIGTokenByUser("user-ig-1");
    expect(result).toEqual({
      token: "ig-token",
      igUserId: "igu-900",
      accountId: "ig-100",
      username: "ig_by_user",
      loginType: "fb_login",
      fbPageToken: "fb-token",
    });
  });

  it("returns null when no IG account found for user", async () => {
    mockQueryBuilder = createQueryBuilder(null);

    const result = await getDecryptedIGTokenByUser("no-ig-user");
    expect(result).toBeNull();
  });

  it("returns null when IG token decrypt returns null", async () => {
    const account = {
      id: "ig-101",
      username: "ig_user",
      instagram_user_id: "igu-901",
      instagram_access_token_encrypted: "enc-ig",
      facebook_page_access_token_encrypted: null,
      login_type: "ig_basic",
    };
    mockQueryBuilder = createQueryBuilder(account);
    mockDecrypt.mockReturnValue(null);

    const result = await getDecryptedIGTokenByUser("user-ig-2");
    expect(result).toBeNull();
  });
});
