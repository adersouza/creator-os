import { describe, expect, it } from "vitest";
import { hasExifData, stripExifFromBuffer } from "../exifStrip.js";

/**
 * Build a minimal valid JPEG with optional APP1 (EXIF) and APP13 (IPTC) segments.
 * Structure: SOI [APP0] [APP1?] [APP13?] DQT SOF0 DHT SOS <image data> EOI
 */
function buildTestJpeg(
	options: {
		includeExif?: boolean | undefined;
		includeIptc?: boolean | undefined;
		exifPayload?: Buffer | undefined;
	} = {},
): Buffer {
	const segments: Buffer[] = [];

	// SOI
	segments.push(Buffer.from([0xff, 0xd8]));

	// APP0 (JFIF marker — always present in valid JPEGs)
	const app0Data = Buffer.from("JFIF\0\x01\x01\0\0\x01\0\x01\0\0", "binary");
	const app0Length = app0Data.length + 2;
	segments.push(
		Buffer.from([0xff, 0xe0, (app0Length >> 8) & 0xff, app0Length & 0xff]),
	);
	segments.push(app0Data);

	// APP1 (EXIF) — optional
	if (options.includeExif !== false) {
		const exifPayload =
			options.exifPayload ||
			Buffer.from(
				"Exif\0\0" + // EXIF header
					"GPS:fake-latitude:40.7128,longitude:-74.0060," + // Simulated GPS data
					"SerialNumber:ABC123DEF456," + // Device serial
					"DateTimeOriginal:2024:01:15 10:30:00", // Timestamp
				"ascii",
			);
		const exifLength = exifPayload.length + 2;
		segments.push(
			Buffer.from([0xff, 0xe1, (exifLength >> 8) & 0xff, exifLength & 0xff]),
		);
		segments.push(exifPayload);
	}

	// APP13 (IPTC) — optional
	if (options.includeIptc) {
		const iptcData = Buffer.from(
			"Photoshop 3.0\0" + "PhotographerName:John Doe",
			"ascii",
		);
		const iptcLength = iptcData.length + 2;
		segments.push(
			Buffer.from([0xff, 0xed, (iptcLength >> 8) & 0xff, iptcLength & 0xff]),
		);
		segments.push(iptcData);
	}

	// DQT (minimal quantization table — 2 + 65 = 67 bytes)
	const dqtPayload = Buffer.alloc(65, 0x10); // Table ID 0 + 64 quantization values
	dqtPayload[0] = 0x00; // 8-bit precision, table 0
	const dqtLength = dqtPayload.length + 2;
	segments.push(
		Buffer.from([0xff, 0xdb, (dqtLength >> 8) & 0xff, dqtLength & 0xff]),
	);
	segments.push(dqtPayload);

	// SOF0 (Start of Frame — minimal 1x1 pixel, 1 component)
	const sof0Payload = Buffer.from([
		0x08, // 8-bit precision
		0x00,
		0x01, // height = 1
		0x00,
		0x01, // width = 1
		0x01, // 1 component
		0x01,
		0x11,
		0x00, // Component 1: ID=1, sampling=1x1, quant table 0
	]);
	const sof0Length = sof0Payload.length + 2;
	segments.push(
		Buffer.from([0xff, 0xc0, (sof0Length >> 8) & 0xff, sof0Length & 0xff]),
	);
	segments.push(sof0Payload);

	// DHT (minimal Huffman table)
	const dhtPayload = Buffer.alloc(29, 0x00);
	dhtPayload[0] = 0x00; // DC table, ID 0
	// 16 bytes of code counts (all zeros = empty table, but structurally valid)
	const dhtLength = dhtPayload.length + 2;
	segments.push(
		Buffer.from([0xff, 0xc4, (dhtLength >> 8) & 0xff, dhtLength & 0xff]),
	);
	segments.push(dhtPayload);

	// SOS (Start of Scan)
	const sosPayload = Buffer.from([
		0x01, // 1 component
		0x01,
		0x00, // Component 1, DC table 0, AC table 0
		0x00,
		0x3f,
		0x00, // Spectral selection, successive approximation
	]);
	const sosLength = sosPayload.length + 2;
	segments.push(
		Buffer.from([0xff, 0xda, (sosLength >> 8) & 0xff, sosLength & 0xff]),
	);
	segments.push(sosPayload);

	// Fake compressed image data
	segments.push(Buffer.from([0x7f, 0x00, 0x00]));

	// EOI
	segments.push(Buffer.from([0xff, 0xd9]));

	return Buffer.concat(segments);
}

describe("stripExifFromBuffer", () => {
	it("strips APP1 (EXIF) segment from JPEG", () => {
		const jpeg = buildTestJpeg({ includeExif: true });
		expect(hasExifData(jpeg)).toBe(true);

		const stripped = stripExifFromBuffer(jpeg);
		expect(hasExifData(stripped)).toBe(false);
		expect(stripped.length).toBeLessThan(jpeg.length);
	});

	it("strips APP13 (IPTC) segment from JPEG", () => {
		const jpeg = buildTestJpeg({ includeExif: false, includeIptc: true });
		const stripped = stripExifFromBuffer(jpeg);
		expect(stripped.length).toBeLessThan(jpeg.length);

		// Verify APP13 marker is gone
		let foundApp13 = false;
		for (let i = 0; i < stripped.length - 1; i++) {
			if (stripped[i] === 0xff && stripped[i + 1] === 0xed) {
				foundApp13 = true;
				break;
			}
		}
		expect(foundApp13).toBe(false);
	});

	it("strips both APP1 and APP13 when present", () => {
		const jpeg = buildTestJpeg({ includeExif: true, includeIptc: true });
		const stripped = stripExifFromBuffer(jpeg);
		expect(stripped.length).toBeLessThan(jpeg.length);
		expect(hasExifData(stripped)).toBe(false);
	});

	it("preserves JPEG structure (SOI + segments + SOS + data + EOI)", () => {
		const jpeg = buildTestJpeg({ includeExif: true });
		const stripped = stripExifFromBuffer(jpeg);

		// Must start with SOI
		expect(stripped[0]).toBe(0xff);
		expect(stripped[1]).toBe(0xd8);

		// Must end with EOI
		expect(stripped[stripped.length - 2]).toBe(0xff);
		expect(stripped[stripped.length - 1]).toBe(0xd9);
	});

	it("preserves APP0 (JFIF) segment", () => {
		const jpeg = buildTestJpeg({ includeExif: true });
		const stripped = stripExifFromBuffer(jpeg);

		// APP0 marker should still be present at offset 2
		expect(stripped[2]).toBe(0xff);
		expect(stripped[3]).toBe(0xe0);
	});

	it("returns original buffer when no metadata is present", () => {
		const jpeg = buildTestJpeg({ includeExif: false, includeIptc: false });
		const stripped = stripExifFromBuffer(jpeg);

		// Should return the exact same buffer reference (no copy)
		expect(stripped).toBe(jpeg);
	});

	it("returns non-JPEG input unchanged", () => {
		const pngHeader = Buffer.from([
			0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
		]);
		const result = stripExifFromBuffer(pngHeader);
		expect(result).toBe(pngHeader);
	});

	it("handles empty buffer", () => {
		const empty = Buffer.alloc(0);
		const result = stripExifFromBuffer(empty);
		expect(result).toBe(empty);
	});

	it("handles 1-byte buffer", () => {
		const tiny = Buffer.from([0xff]);
		const result = stripExifFromBuffer(tiny);
		expect(result).toBe(tiny);
	});

	it("handles large EXIF payloads", () => {
		// Simulate a 64KB EXIF segment (typical for photos with embedded thumbnails)
		const largeExif = Buffer.alloc(60_000, 0x42);
		const jpeg = buildTestJpeg({ includeExif: true, exifPayload: largeExif });
		const stripped = stripExifFromBuffer(jpeg);

		expect(stripped.length).toBeLessThan(jpeg.length);
		expect(jpeg.length - stripped.length).toBeGreaterThanOrEqual(60_000);
		expect(hasExifData(stripped)).toBe(false);
	});
});

describe("hasExifData", () => {
	it("returns true for JPEG with EXIF", () => {
		const jpeg = buildTestJpeg({ includeExif: true });
		expect(hasExifData(jpeg)).toBe(true);
	});

	it("returns false for JPEG without EXIF", () => {
		const jpeg = buildTestJpeg({ includeExif: false });
		expect(hasExifData(jpeg)).toBe(false);
	});

	it("returns false for non-JPEG", () => {
		expect(hasExifData(Buffer.from([0x89, 0x50, 0x4e, 0x47]))).toBe(false);
	});

	it("returns false for empty buffer", () => {
		expect(hasExifData(Buffer.alloc(0))).toBe(false);
	});

	it("returns false for buffer too small for JPEG", () => {
		expect(hasExifData(Buffer.from([0xff]))).toBe(false);
	});
});
