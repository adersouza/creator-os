/**
 * Zod Compatibility Layer for Vercel TS 5.9
 *
 * Vercel's bundled TypeScript 5.9 breaks `z.enum()`, `z.literal()`,
 * `z.unknown()`, and `z.record()` at build time (they emit types the old
 * compiler can't resolve). We wrap those four methods in a single place so
 * the workaround can be removed when Vercel bumps past 5.9.
 *
 * Two usage styles — pick based on file scope:
 *
 * 1. Named helpers when you only need one or two methods:
 *    import { z, zEnum, zRecord } from "./zodCompat.js";
 *    const Schema = z.object({ platform: zEnum(["a","b"]) });
 *
 * 2. Drop-in `z` namespace when you want stock Zod ergonomics without
 *    thinking about which methods are broken:
 *    import { z } from "./zodCompat.js";
 *    const Schema = z.object({ platform: z.enum(["a","b"]) });
 *    // everything works — safe methods forward, broken methods are shimmed.
 *
 * When Vercel upgrades past TS 5.9, this file shrinks to `export { z }
 * from "zod"` and all helpers continue to work unchanged.
 */

import { z as stockZ } from "zod";

export type Infer<T extends stockZ.ZodTypeAny> = stockZ.infer<T>;
export type ZodSchema<T = unknown> = stockZ.ZodSchema<T>;
export type ZodTypeAny = stockZ.ZodTypeAny;

type CompatZod = {
	enum: (...args: unknown[]) => unknown;
	literal: (...args: unknown[]) => unknown;
	unknown: (...args: unknown[]) => unknown;
	record: (...args: unknown[]) => unknown;
	union: (...args: unknown[]) => unknown;
	array: (...args: unknown[]) => unknown;
	string: (...args: unknown[]) => unknown;
};

const compatZ = stockZ as unknown as CompatZod;

// biome-ignore lint/suspicious/noExplicitAny: preserve permissive typing for Vercel TS workaround
export const zEnum = (...args: any[]): any => compatZ.enum(...args);
// biome-ignore lint/suspicious/noExplicitAny: preserve permissive typing for Vercel TS workaround
export const zLiteral = (...args: any[]): any => compatZ.literal(...args);
// biome-ignore lint/suspicious/noExplicitAny: preserve permissive typing for Vercel TS workaround
export const zUnknown = (...args: any[]): any => compatZ.unknown(...args);
// biome-ignore lint/suspicious/noExplicitAny: preserve permissive typing for Vercel TS workaround
export const zRecord = (...args: any[]): any => compatZ.record(...args);
// biome-ignore lint/suspicious/noExplicitAny: preserve permissive typing for Vercel TS workaround
export const zUnion = (...args: any[]): any => compatZ.union(...args);
// biome-ignore lint/suspicious/noExplicitAny: preserve permissive typing for Vercel TS workaround
export const zArray = (...args: any[]): any => compatZ.array(...args);
// biome-ignore lint/suspicious/noExplicitAny: preserve permissive typing for Vercel TS workaround
export const zString = (...args: any[]): any => compatZ.string(...args);

/**
 * Drop-in replacement for the stock `z` namespace. Same surface as `zod`'s
 * export, but with the four problematic methods overridden to go through
 * the `any`-typed shim. Callers can:
 *
 *   import { z } from "./zodCompat.js";
 *   z.object({ platform: z.enum(["a","b"]) });
 *
 * — and not have to remember which methods are broken on Vercel.
 */
// Loosened type for the Proxy: keep stockZ's surface for safe methods, but
// override the broken-on-Vercel-TS-5.9 ones with our `(...args: any[]) => any`
// signatures so callers can write `z.literal("x")`, `z.union([...])`, etc.
// without TS rejecting the args.
type LoosenedZ = Omit<typeof stockZ, "enum" | "literal" | "unknown" | "record" | "union"> & {
	enum: typeof zEnum;
	literal: typeof zLiteral;
	unknown: typeof zUnknown;
	record: typeof zRecord;
	union: typeof zUnion;
};

export const z = new Proxy(stockZ, {
	get(target, prop, receiver) {
		if (prop === "enum") return zEnum;
		if (prop === "literal") return zLiteral;
		if (prop === "unknown") return zUnknown;
		if (prop === "record") return zRecord;
		if (prop === "union") return zUnion;
		return Reflect.get(target, prop, receiver);
	},
}) as unknown as LoosenedZ;
