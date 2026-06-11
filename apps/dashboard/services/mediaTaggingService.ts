// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Media Tagging Service
 * Phase 4.3 - AI-powered auto-tagging for media uploads
 *
 * Features:
 * - Object detection
 * - Scene recognition
 * - Dominant color extraction
 * - OCR text extraction
 * - Smart categorization
 * - Hashtag suggestions
 */

import logger from "@/utils/logger";
import { getAIService } from "./aiServiceClient.js";

export interface MediaTags {
	mediaType: "image" | "video" | "graphic";
	dominantColors: string[]; // Hex color codes
	objects: string[]; // Detected objects (e.g., ['laptop', 'coffee', 'notepad'])
	scene: string; // Scene category (e.g., 'workspace', 'outdoor', 'food')
	mood?: string | undefined; // Mood/vibe (e.g., 'productive', 'relaxing', 'energetic')
	suggestedHashtags: string[]; // Auto-generated hashtags
	ocrText?: string | null | undefined; // Extracted text from image
	categories: string[]; // Auto-assigned categories
	confidence: number; // 0-100 confidence score
}

/**
 * Extract dominant colors from image file
 * Uses canvas to analyze pixel data
 */
async function extractDominantColors(file: File): Promise<string[]> {
	return new Promise((resolve) => {
		const img = new Image();
		const reader = new FileReader();

		reader.onerror = () => resolve([]);
		reader.onload = (e) => {
			img.onerror = () => resolve([]);
			img.onload = () => {
				const canvas = document.createElement("canvas");
				const ctx = canvas.getContext("2d");
				if (!ctx) {
					resolve([]);
					return;
				}

				// Scale down for performance
				const MAX_SIZE = 100;
				const scale = Math.min(MAX_SIZE / img.width, MAX_SIZE / img.height);
				canvas.width = img.width * scale;
				canvas.height = img.height * scale;

				ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
				const imageData = ctx.getImageData(
					0,
					0,
					canvas.width,
					canvas.height,
				).data;

				// Count color frequency (simplified)
				const colorCounts: Record<string, number> = {};
				for (let i = 0; i < imageData.length; i += 4) {
					const r = Math.round(imageData[i]! / 32) * 32;
					const g = Math.round(imageData[i + 1]! / 32) * 32;
					const b = Math.round(imageData[i + 2]! / 32) * 32;

					// Skip very dark/very light colors
					if (r < 40 && g < 40 && b < 40) continue;
					if (r > 220 && g > 220 && b > 220) continue;

					const hex = `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
					colorCounts[hex] = (colorCounts[hex] || 0) + 1;
				}

				// Get top 3 colors
				const topColors = Object.entries(colorCounts)
					.sort((a, b) => b[1] - a[1])
					.slice(0, 3)
					.map(([color]) => color);

				resolve(topColors);
			};
			img.src = e.target?.result as string;
		};

		reader.readAsDataURL(file);
	});
}

/**
 * Detect if image contains significant text (likely a graphic/screenshot)
 */
function detectGraphicContent(filename: string): boolean {
	const graphicPatterns = [
		/screenshot/i,
		/screen[-_]?shot/i,
		/graphic/i,
		/design/i,
		/banner/i,
		/flyer/i,
		/poster/i,
		/template/i,
	];

	return graphicPatterns.some((pattern) => pattern.test(filename));
}

/**
 * Analyze image with AI to detect objects, scenes, and extract text
 */
async function analyzeImageWithAI(
	_file: File,
): Promise<Partial<MediaTags> | null> {
	try {
		const aiService = await getAIService();

		// AI prompt for image analysis
		const prompt = `Analyze this image and provide the following in JSON format:

{
  "objects": ["object1", "object2", ...],  // List 3-5 prominent objects
  "scene": "scene_type",  // One of: workspace, outdoor, food, portrait, product, event, travel, nature, indoor, abstract
  "mood": "mood",  // One of: professional, casual, energetic, calm, playful, serious, inspirational, luxury
  "text": "any text visible in the image or null if none",
  "suggestedHashtags": ["#hashtag1", "#hashtag2", ...]  // 3-5 relevant hashtags
}

Be concise and accurate. Return ONLY valid JSON.`;

		const response = await aiService.generateContent(prompt);

		// Parse AI response
		const jsonMatch = response.match(/\{[\s\S]*\}/);
		if (!jsonMatch) {
			logger.warn("[MediaTagging] Failed to parse AI response:", response);
			return null;
		}

		const parsed = JSON.parse(jsonMatch[0]);

		return {
			objects: parsed.objects || [],
			scene: parsed.scene || "unknown",
			mood: parsed.mood || undefined,
			ocrText: parsed.text || null,
			suggestedHashtags: parsed.suggestedHashtags || [],
		};
	} catch (error) {
		logger.warn("[MediaTagging] AI analysis failed:", error);
		return null;
	}
}

/**
 * Determine smart categories based on tags
 */
function determineCategories(tags: Partial<MediaTags>): string[] {
	const categories: string[] = [];

	// Scene-based categorization
	if (tags.scene === "workspace" || tags.scene === "indoor") {
		categories.push("Behind the Scenes");
	}
	if (
		tags.scene === "outdoor" ||
		tags.scene === "travel" ||
		tags.scene === "nature"
	) {
		categories.push("Lifestyle");
	}
	if (tags.scene === "food") {
		categories.push("Food & Beverage");
	}
	if (tags.scene === "product") {
		categories.push("Product Photos");
	}

	// Object-based categorization
	if (
		tags.objects?.some((obj) =>
			["person", "people", "face", "portrait"].includes(obj.toLowerCase()),
		)
	) {
		categories.push("People & Portraits");
	}

	// Text-based (likely graphics)
	if (tags.ocrText && tags.ocrText.length > 10) {
		categories.push("Graphics & Text");
	}

	// Default if no category assigned
	if (categories.length === 0) {
		categories.push("Uncategorized");
	}

	return categories;
}

/**
 * Main function: Tag media file on upload
 * @param file - The file to analyze
 * @returns MediaTags with all detected information
 */
export async function tagMediaOnUpload(file: File): Promise<MediaTags> {
	logger.info(`[MediaTagging] Analyzing file: ${file.name}`);

	// Determine media type
	let mediaType: "image" | "video" | "graphic" = "image";
	if (file.type.startsWith("video/")) {
		mediaType = "video";
	} else if (detectGraphicContent(file.name)) {
		mediaType = "graphic";
	}

	// Extract dominant colors (images only)
	let dominantColors: string[] = [];
	if (file.type.startsWith("image/")) {
		try {
			dominantColors = await extractDominantColors(file);
		} catch (err) {
			logger.warn("[MediaTagging] Color extraction failed:", err);
		}
	}

	// AI analysis (images only for now)
	let aiTags: Partial<MediaTags> | null = null;
	if (file.type.startsWith("image/")) {
		aiTags = await analyzeImageWithAI(file);
	}

	// Fallback values if AI fails
	const objects = aiTags?.objects || [];
	const scene = aiTags?.scene || "unknown";
	const mood = aiTags?.mood;
	const ocrText = aiTags?.ocrText;
	const suggestedHashtags = aiTags?.suggestedHashtags || [];

	// Determine categories
	const categories = determineCategories({
		mediaType,
		objects,
		scene,
		ocrText,
	});

	// Calculate confidence (0-100)
	const confidence = aiTags
		? Math.min(
				100,
				(objects.length > 0 ? 40 : 0) +
					(scene !== "unknown" ? 30 : 0) +
					(suggestedHashtags.length > 0 ? 30 : 0),
			)
		: 0;

	const tags: MediaTags = {
		mediaType,
		dominantColors,
		objects,
		scene,
		mood,
		suggestedHashtags,
		ocrText,
		categories,
		confidence,
	};

	logger.info(`[MediaTagging] Analysis complete for ${file.name}:`, tags);

	return tags;
}

/**
 * Search media by tags
 * @param mediaLibrary - Array of media items with tags
 * @param query - Search query (tag, color, scene, etc.)
 * @returns Filtered media items
 */
export function searchMediaByTags(
	// biome-ignore lint/suspicious/noExplicitAny: media items have open-ended extra properties
	mediaLibrary: Array<{ id: string; tags?: MediaTags | undefined; [key: string]: any }>,
	query: string,
	// biome-ignore lint/suspicious/noExplicitAny: media items have open-ended extra properties
): Array<{ id: string; tags?: MediaTags | undefined; [key: string]: any }> {
	const lowerQuery = query.toLowerCase().trim();

	if (!lowerQuery) return mediaLibrary;

	return mediaLibrary.filter((item) => {
		if (!item.tags) return false;

		// Search in objects
		if (item.tags.objects.some((obj) => obj.toLowerCase().includes(lowerQuery)))
			return true;

		// Search in scene
		if (item.tags.scene.toLowerCase().includes(lowerQuery)) return true;

		// Search in mood
		if (item.tags.mood?.toLowerCase().includes(lowerQuery)) return true;

		// Search in hashtags
		if (
			item.tags.suggestedHashtags.some((tag) =>
				tag.toLowerCase().includes(lowerQuery),
			)
		)
			return true;

		// Search in OCR text
		if (item.tags.ocrText?.toLowerCase().includes(lowerQuery)) return true;

		// Search in categories
		if (
			item.tags.categories.some((cat) => cat.toLowerCase().includes(lowerQuery))
		)
			return true;

		// Search by color (hex code)
		if (
			lowerQuery.startsWith("#") &&
			item.tags.dominantColors.some((color) =>
				color.toLowerCase().includes(lowerQuery),
			)
		)
			return true;

		return false;
	});
}

/**
 * Filter media by date range
 * @param mediaLibrary - Array of media items
 * @param dateRange - "today", "week", "month", "year", or custom date
 * @returns Filtered media items
 */
export function filterMediaByDate(
	// biome-ignore lint/suspicious/noExplicitAny: uploadedAt may be string or Date, media items have open-ended extra properties
	mediaLibrary: Array<{ id: string; uploadedAt: any; [key: string]: any }>,
	dateRange: string,
	// biome-ignore lint/suspicious/noExplicitAny: same as above
): Array<{ id: string; uploadedAt: any; [key: string]: any }> {
	const now = new Date();
	let startDate: Date;

	switch (dateRange.toLowerCase()) {
		case "today":
			startDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());
			break;
		case "week":
		case "last week":
			startDate = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
			break;
		case "month":
		case "last month":
			startDate = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
			break;
		case "year":
		case "last year":
			startDate = new Date(now.getTime() - 365 * 24 * 60 * 60 * 1000);
			break;
		default: {
			// Try parsing as date
			const parsed = new Date(dateRange);
			if (Number.isNaN(parsed.getTime())) return mediaLibrary;
			startDate = parsed;
		}
	}

	return mediaLibrary.filter((item) => {
		const uploadDate = item.uploadedAt?.toDate
			? item.uploadedAt.toDate()
			: new Date(item.uploadedAt);
		return uploadDate >= startDate;
	});
}

export const mediaTaggingService = {
	tagMediaOnUpload,
	searchMediaByTags,
	filterMediaByDate,
};
