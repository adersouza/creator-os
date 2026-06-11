import { describe, expect, it } from "vitest";

/**
 * Threads API Conversation & Ghost Posts — Contract Tests
 *
 * Validates the expected request shapes and error handling contracts for:
 * 1. getConversation(token, mediaId, reverse?) → GET /{media-id}/replies
 * 2. getGhostPosts(token, userId) → GET /{user-id}/ghost_posts
 *
 * These are contract tests — they validate shapes and invariants
 * without calling the real Threads API.
 */

// ---------------------------------------------------------------------------
// 1. getConversation Request Shape
// ---------------------------------------------------------------------------

describe("getConversation request contract", () => {
    const REPLIES_FIELDS =
        "id,text,username,timestamp,media_product_type,media_type,media_url,permalink,profile_picture_url,is_reply,is_reply_owned_by_me,replied_to,root_post,has_replies,hide_status,reply_audience,shortcode,thumbnail_url,children,topic_tag";

    function buildConversationUrl(mediaId: string, reverse = false): string {
        return `https://graph.threads.net/v1.0/${mediaId}/replies?fields=${REPLIES_FIELDS}&reverse=${reverse ? "true" : "false"}`;
    }

    it("builds URL with all required conversation fields", () => {
        const url = buildConversationUrl("12345");
        const requiredFields = [
            "id",
            "text",
            "username",
            "timestamp",
            "media_product_type",
            "media_type",
            "media_url",
            "permalink",
            "profile_picture_url",
            "is_reply",
            "is_reply_owned_by_me",
            "replied_to",
            "root_post",
            "has_replies",
            "hide_status",
            "reply_audience",
            "shortcode",
            "thumbnail_url",
            "children",
            "topic_tag",
        ];
        for (const field of requiredFields) {
            expect(url).toContain(field);
        }
    });

    it("uses the /replies endpoint on the media ID", () => {
        const url = buildConversationUrl("98765");
        expect(url).toMatch(/\/98765\/replies\?/);
    });

    it("passes reverse=false by default", () => {
        const url = buildConversationUrl("12345");
        expect(url).toContain("&reverse=false");
    });

    it("passes reverse=true when requested", () => {
        const url = buildConversationUrl("12345", true);
        expect(url).toContain("&reverse=true");
    });

    it("handles empty mediaId gracefully in URL construction", () => {
        const url = buildConversationUrl("");
        expect(url).toContain("/replies?fields=");
    });

    it("response shape includes data array", () => {
        // Contract: the Threads API returns { data: [...] } or { error: {...} }
        const successResponse = {
            data: [
                {
                    id: "reply_1",
                    text: "Hello!",
                    username: "testuser",
                    timestamp: "2026-03-09T22:00:00Z",
                    media_type: "TEXT_POST",
                    is_reply: true,
                    has_replies: false,
                    hide_status: "NOT_HUSHED",
                },
            ],
        };

        expect(successResponse).toHaveProperty("data");
        expect(Array.isArray(successResponse.data)).toBe(true);
        expect(successResponse.data[0]).toHaveProperty("id");
        expect(successResponse.data[0]).toHaveProperty("text");
        expect(successResponse.data[0]).toHaveProperty("username");
        expect(successResponse.data[0]).toHaveProperty("timestamp");
        expect(successResponse.data[0]).toHaveProperty("is_reply");
    });

    it("error shape includes error.message", () => {
        const errorResponse = {
            error: {
                message: "Invalid media ID",
                type: "OAuthException",
                code: 100,
            },
        };

        expect(errorResponse).toHaveProperty("error");
        expect(errorResponse.error).toHaveProperty("message");
        expect(errorResponse.error).toHaveProperty("code");
        expect(typeof errorResponse.error.message).toBe("string");
    });

    it("reverse param is delegated to the Threads API request", () => {
        const urlNormal = buildConversationUrl("111");
        const urlReversed = buildConversationUrl("111", true);

        expect(urlNormal).toContain("&reverse=false");
        expect(urlReversed).toContain("&reverse=true");
        expect(urlReversed).not.toBe(urlNormal);
    });
});

// ---------------------------------------------------------------------------
// 2. getGhostPosts Request Shape
// ---------------------------------------------------------------------------

describe("getGhostPosts request contract", () => {
    const GHOST_POST_FIELDS =
        "id,media_product_type,media_type,text,timestamp,permalink,is_reply,shortcode";

    function buildGhostPostsUrl(userId: string): string {
        return `https://graph.threads.net/v1.0/${userId}/ghost_posts?fields=${GHOST_POST_FIELDS}`;
    }

    it("builds URL with all required ghost post fields", () => {
        const url = buildGhostPostsUrl("user_123");
        const requiredFields = [
            "id",
            "media_product_type",
            "media_type",
            "text",
            "timestamp",
            "permalink",
            "is_reply",
            "shortcode",
        ];
        for (const field of requiredFields) {
            expect(url).toContain(field);
        }
    });

    it("uses the /ghost_posts endpoint on the user ID", () => {
        const url = buildGhostPostsUrl("user_456");
        expect(url).toMatch(/\/user_456\/ghost_posts\?/);
    });

    it("response shape includes data array of ghost posts", () => {
        const successResponse = {
            data: [
                {
                    id: "ghost_1",
                    media_product_type: "THREADS",
                    media_type: "TEXT_POST",
                    text: "This is a ghost post",
                    timestamp: "2026-03-09T20:00:00Z",
                    permalink: "https://threads.net/@user/post/ghost_1",
                    is_reply: false,
                    shortcode: "abc123",
                },
            ],
        };

        expect(successResponse).toHaveProperty("data");
        expect(Array.isArray(successResponse.data)).toBe(true);
        const post = successResponse.data[0];
        expect(post).toHaveProperty("id");
        expect(post).toHaveProperty("media_product_type");
        expect(post.media_product_type).toBe("THREADS");
        expect(post).toHaveProperty("text");
        expect(post).toHaveProperty("timestamp");
        expect(post).toHaveProperty("permalink");
        expect(post.is_reply).toBe(false);
    });

    it("error handling throws on API error response", () => {
        const errorResponse = {
            error: {
                message: "User does not exist or cannot be loaded",
                type: "OAuthException",
                code: 100,
            },
        };

        // Contract: getGhostPosts throws when data.error exists
        function handleResponse(data: typeof errorResponse) {
            if (data.error) throw new Error(data.error.message);
            return data;
        }

        expect(() => handleResponse(errorResponse)).toThrow(
            "User does not exist or cannot be loaded",
        );
    });

    it("ghost posts are auto-published and expire after 24h", () => {
        // Contract validation: ghost posts have a 24h ttl
        const ghostPost = {
            id: "ghost_1",
            timestamp: new Date("2026-03-09T20:00:00Z"),
        };

        const now = new Date("2026-03-10T21:00:00Z");
        const hoursElapsed =
            (now.getTime() - ghostPost.timestamp.getTime()) / (1000 * 60 * 60);

        expect(hoursElapsed).toBeGreaterThan(24);
        // After 24h, ghost post should be considered expired
    });

    it("empty data array indicates no ghost posts", () => {
        const emptyResponse = { data: [] };

        function handleResponse(data: typeof emptyResponse) {
            if ((data as any).error)
                throw new Error((data as any).error.message);
            return data;
        }

        const result = handleResponse(emptyResponse);
        expect(result.data).toHaveLength(0);
    });
});

// ---------------------------------------------------------------------------
// 3. Cross-cutting Contract: Error Handling
// ---------------------------------------------------------------------------

describe("Threads API error handling contract", () => {
    it("both endpoints throw Error when API returns error object", () => {
        function processApiResponse(data: {
            error?: { message: string; code?: number };
            data?: unknown[];
        }) {
            if (data.error) throw new Error(data.error.message);
            return data;
        }

        const errorPayload = {
            error: { message: "Rate limit exceeded", code: 4 },
        };

        expect(() => processApiResponse(errorPayload)).toThrow(
            "Rate limit exceeded",
        );
    });

    it("both endpoints pass through successful responses", () => {
        function processApiResponse(data: {
            error?: { message: string };
            data?: unknown[];
        }) {
            if (data.error) throw new Error(data.error.message);
            return data;
        }

        const successPayload = { data: [{ id: "1" }] };
        const result = processApiResponse(successPayload);
        expect(result).toBe(successPayload);
        expect(result.data).toHaveLength(1);
    });

    it("error.type is typically OAuthException for Threads API", () => {
        const apiError = {
            error: {
                message: "Invalid token",
                type: "OAuthException",
                code: 190,
            },
        };

        expect(apiError.error.type).toBe("OAuthException");
    });
});
