/**
 * Canvas-based image compression. Zero deps — browsers already own the codecs.
 *
 * Side effect: re-encoding through canvas drops all EXIF metadata (GPS,
 * camera model, timestamp). That's the privacy strip we want — IG and
 * Threads readers shouldn't see where a photo was taken.
 *
 * Used on the composer media strip, avatar upload, and white-label logo.
 */

export interface CompressOptions {
	/** Max longest edge in px. Default 2048 (enough for IG 4:5 portraits at 4x retina). */
	maxDimension?: number | undefined;
	/** JPEG quality 0..1. Default 0.85. */
	quality?: number | undefined;
	/** Skip compression entirely when file is already under this size. Default 1.5 MB. */
	skipBelowBytes?: number | undefined;
	/** Output mime type. Default image/jpeg; pass image/webp for better compression if targets support it. */
	mimeType?: 'image/jpeg' | 'image/webp' | 'image/png' | undefined;
}

const DEFAULTS: {
	maxDimension: number;
	quality: number;
	skipBelowBytes: number;
	mimeType: 'image/jpeg' | 'image/webp' | 'image/png';
} = {
	maxDimension: 2048,
	quality: 0.85,
	skipBelowBytes: 1.5 * 1024 * 1024,
	mimeType: 'image/jpeg',
};

export async function compressImage(file: File, options: CompressOptions = {}): Promise<File> {
	if (!file.type.startsWith('image/')) return file;
	if (file.type === 'image/gif' || file.type === 'image/svg+xml') return file;

	const opts = {
		maxDimension: options.maxDimension ?? DEFAULTS.maxDimension,
		quality: options.quality ?? DEFAULTS.quality,
		skipBelowBytes: options.skipBelowBytes ?? DEFAULTS.skipBelowBytes,
		mimeType: options.mimeType ?? DEFAULTS.mimeType,
	};

	// Skip path — already small enough. We lose EXIF stripping here, so expose
	// a separate stripExif() below for callers who want that specifically.
	if (file.size < opts.skipBelowBytes) return file;

	const dataUrl = await fileToDataUrl(file);
	const img = await loadImage(dataUrl);

	const maxEdge = Math.max(img.width, img.height);
	const scale = maxEdge > opts.maxDimension ? opts.maxDimension / maxEdge : 1;
	const width = Math.round(img.width * scale);
	const height = Math.round(img.height * scale);

	const canvas = document.createElement('canvas');
	canvas.width = width;
	canvas.height = height;
	const ctx = canvas.getContext('2d');
	if (!ctx) return file;

	ctx.drawImage(img, 0, 0, width, height);

	const blob = await new Promise<Blob | null>((resolve) =>
		canvas.toBlob(resolve, opts.mimeType, opts.quality),
	);
	if (!blob) return file;

	// Only commit the compressed version when it's actually smaller — a small
	// JPEG of a large PNG screenshot may be smaller, but forcing JPEG on a
	// well-optimized source sometimes bloats.
	if (blob.size >= file.size) return file;

	const ext = opts.mimeType === 'image/webp' ? 'webp' : opts.mimeType === 'image/png' ? 'png' : 'jpg';
	const baseName = file.name.replace(/\.[^.]+$/, '');
	return new File([blob], `${baseName}.${ext}`, {
		lastModified: Date.now(),
		...(opts.mimeType ? { type: opts.mimeType } : {}),
	});
}

/**
 * Strip EXIF metadata by re-encoding through canvas without downscaling.
 * Use on avatars where you care about privacy but not compression.
 */
export async function stripExif(file: File): Promise<File> {
	if (!file.type.startsWith('image/')) return file;
	if (file.type === 'image/gif' || file.type === 'image/svg+xml' || file.type === 'image/png') return file;

	const dataUrl = await fileToDataUrl(file);
	const img = await loadImage(dataUrl);

	const canvas = document.createElement('canvas');
	canvas.width = img.width;
	canvas.height = img.height;
	const ctx = canvas.getContext('2d');
	if (!ctx) return file;

	ctx.drawImage(img, 0, 0);

	const blob = await new Promise<Blob | null>((resolve) =>
		canvas.toBlob(resolve, 'image/jpeg', 0.95),
	);
	if (!blob) return file;

	const baseName = file.name.replace(/\.[^.]+$/, '');
	return new File([blob], `${baseName}.jpg`, { type: 'image/jpeg', lastModified: Date.now() });
}

function fileToDataUrl(file: File): Promise<string> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(reader.result as string);
		reader.onerror = () => reject(reader.error);
		reader.readAsDataURL(file);
	});
}

function loadImage(src: string): Promise<HTMLImageElement> {
	return new Promise((resolve, reject) => {
		const img = new Image();
		img.onload = () => resolve(img);
		img.onerror = () => reject(new Error('Image load failed'));
		img.src = src;
	});
}
