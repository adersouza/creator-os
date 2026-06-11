/**
 * Automated OpenAPI 3.0 specification for the Juno33 API.
 *
 * Generated from Zod schemas in api/_lib/validation.ts.
 * This ensures the documentation always matches the implementation.
 */

import {
	OpenAPIRegistry,
	OpenApiGeneratorV3,
} from "@asteasolutions/zod-to-openapi";
import { PublishPostSchema } from "./validation.js";

const registry = new OpenAPIRegistry();

// ----------------------------------------------------------------------------
// Components & Security
// ----------------------------------------------------------------------------
registry.registerComponent("securitySchemes", "bearerAuth", {
	type: "http",
	scheme: "bearer",
	description:
		"Supabase JWT from auth.getSession(). Pass as `Authorization: Bearer <token>`.",
});

// #601: Document X-API-Key authentication for public API v1 endpoints
registry.registerComponent("securitySchemes", "apiKeyAuth", {
	type: "apiKey",
	in: "header",
	name: "X-API-Key",
	description:
		"API key for public API endpoints. Generate keys in Settings > API Keys. " +
		"Keys use the `juno_ak_` prefix and are SHA-256 hashed at rest. " +
		"Pass as `X-API-Key: juno_ak_...` header. " +
		"Rate limited to 100 requests/minute per key. " +
		"Scopes: read, write, admin, mcp. Keys may also include allowed_account_ids to restrict account access.",
});

// ----------------------------------------------------------------------------
// Post Endpoints
// ----------------------------------------------------------------------------
registry.registerPath({
	method: "post",
	path: "/api/posts",
	summary: "Publish or delete a post",
	tags: ["Posts"],
	parameters: [
		{
			name: "action",
			in: "query",
			required: true,
			schema: { type: "string", enum: ["publish", "delete"] },
		},
	],
	request: {
		body: {
			content: {
				"application/json": {
					schema: PublishPostSchema,
				},
			},
		},
	},
	responses: {
		200: {
			description: "Successful operation",
			content: {
				"application/json": {
					schema: {
						type: "object",
						properties: { success: { type: "boolean" } },
					},
				},
			},
		},
	},
});

// ----------------------------------------------------------------------------
// Operator Control Plane
// ----------------------------------------------------------------------------
registry.registerPath({
	method: "get",
	path: "/api/operator",
	summary: "Get operator action manifest",
	tags: ["Operator"],
	parameters: [
		{
			name: "action",
			in: "query",
			required: true,
			schema: { type: "string", enum: ["manifest"] },
		},
	],
	responses: {
		200: {
			description: "Machine-readable operator action manifest with safety and rollback metadata",
			content: {
				"application/json": {
					schema: {
						type: "object",
						properties: {
							version: { type: "string" },
							summary: { type: "object", additionalProperties: true },
							actions: {
								type: "array",
								items: {
									type: "object",
									required: [
										"toolName",
										"riskLevel",
										"sideEffectType",
										"requiresApproval",
										"requiresIdempotencyKey",
										"supportsDryRun",
										"hostedAvailable",
										"rollbackSupport",
										"compensationDescription",
										"compensationRequiresApproval",
									],
									properties: {
										toolName: { type: "string" },
										riskLevel: { type: "string", enum: ["low", "medium", "high", "critical"] },
										sideEffectType: {
											type: "string",
											enum: ["none", "ai_generation", "content_write", "external_publish", "settings_write", "destructive"],
										},
										requiresApproval: { type: "boolean" },
										requiresIdempotencyKey: { type: "boolean" },
										supportsDryRun: { type: "boolean" },
										hostedAvailable: { type: "boolean" },
										rollbackSupport: { type: "string", enum: ["none", "compensating_action", "delete_or_revert"] },
										compensationActionName: { type: "string" },
										compensationDescription: { type: "string" },
										compensationRequiresApproval: { type: "boolean" },
										rollbackWindowHours: { type: "number" },
									},
								},
							},
						},
					},
				},
			},
		},
	},
});

// ----------------------------------------------------------------------------
// Generator
// ----------------------------------------------------------------------------
export function generateOpenApiSpec() {
	const generator = new OpenApiGeneratorV3(registry.definitions);

	return generator.generateDocument({
		openapi: "3.0.0",
		info: {
			title: "Juno33 API",
			version: "1.0.0",
			description: "Unified API for Threads & Instagram management.",
		},
		servers: [{ url: "https://juno33.com" }],
	});
}

// Support for the legacy export if needed
export const openApiSpec = generateOpenApiSpec();
