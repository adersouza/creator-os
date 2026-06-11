/**
 * Client-side media validation — aspect ratio, file size, duration.
 * Meta platform limits (2026):
 *   · Instagram Feed:   1:1, 4:5, 1.91:1   · image ≤ 8 MB   · video ≤ 100 MB, ≤ 60s
 *   · Instagram Reels:  9:16                · video ≤ 100 MB, ≤ 90s  (trial Reels ≤ 15s)
 *   · Instagram Story:  9:16                · video ≤ 100 MB, ≤ 60s
 *   · Threads:          any aspect          · image ≤ 8 MB   · video ≤ 100 MB, ≤ 5 min
 */

export type Surface = 'ig-feed' | 'ig-reel' | 'ig-story' | 'threads';

export interface ValidationConstraints {
	/** Valid aspect ratios expressed as width/height decimals. */
	aspects: { w: number; h: number; label: string }[];
	maxImageBytes: number;
	maxVideoBytes: number;
	maxVideoSeconds: number | null;
	altTextMax: number;
}

const MB = 1024 * 1024;

export const CONSTRAINTS: Record<Surface, ValidationConstraints> = {
	'ig-feed': {
		aspects: [
			{ w: 1, h: 1, label: '1:1' },
			{ w: 4, h: 5, label: '4:5' },
			{ w: 1.91, h: 1, label: '1.91:1' },
		],
		maxImageBytes: 8 * MB,
		maxVideoBytes: 100 * MB,
		maxVideoSeconds: 60,
		altTextMax: 100,
	},
	'ig-reel': {
		aspects: [{ w: 9, h: 16, label: '9:16' }],
		maxImageBytes: 8 * MB,
		maxVideoBytes: 100 * MB,
		maxVideoSeconds: 90,
		altTextMax: 100,
	},
	'ig-story': {
		aspects: [{ w: 9, h: 16, label: '9:16' }],
		maxImageBytes: 8 * MB,
		maxVideoBytes: 100 * MB,
		maxVideoSeconds: 60,
		altTextMax: 100,
	},
	threads: {
		aspects: [],
		maxImageBytes: 8 * MB,
		maxVideoBytes: 100 * MB,
		maxVideoSeconds: 5 * 60,
		altTextMax: 1000,
	},
};

export interface ValidationResult {
	ok: boolean;
	errors: string[];
	warnings: string[];
	dimensions?: { width: number; height: number; aspect: number } | undefined;
	durationSeconds?: number | undefined;
}

export type ValidationMode = 'api' | 'native-handoff';

export interface ValidationOptions {
	mode?: ValidationMode;
}

export async function validateMedia(
	file: File,
	surfaces: Surface[],
	options: ValidationOptions = {},
): Promise<ValidationResult> {
	const errors: string[] = [];
	const warnings: string[] = [];
	const mode = options.mode ?? 'api';
	const isVideo = file.type.startsWith('video/');
	const isImage = file.type.startsWith('image/');

	if (!isVideo && !isImage) {
		return { ok: false, errors: ['Unsupported file type — must be image or video.'], warnings };
	}

	// File size
	for (const surface of surfaces) {
		const c = CONSTRAINTS[surface];
		const cap = isVideo ? c.maxVideoBytes : c.maxImageBytes;
		if (file.size > cap) {
			addConstraintIssue(errors, warnings, mode, surface,
				`${label(surface)}: file is ${fmtBytes(file.size)}, limit is ${fmtBytes(cap)}.`,
			);
		}
	}

	// Dimensions / duration
	let dimensions: ValidationResult['dimensions'];
	let durationSeconds: number | undefined;

	try {
		if (isImage) {
			const dims = await readImageDimensions(file);
			dimensions = { ...dims, aspect: dims.width / Math.max(1, dims.height) };
		} else {
			const meta = await readVideoMeta(file);
			dimensions = { width: meta.width, height: meta.height, aspect: meta.width / Math.max(1, meta.height) };
			durationSeconds = meta.duration;
		}
	} catch {
		warnings.push('Could not read media metadata — uploading without dimension checks.');
	}

	// Aspect validation — skip when surface allows "any"
	if (dimensions) {
		for (const surface of surfaces) {
			const c = CONSTRAINTS[surface];
			if (c.aspects.length === 0) continue;
			const tolerant = c.aspects.some(
				(a) => Math.abs(dimensions?.aspect - a.w / a.h) < 0.03,
			);
			if (!tolerant) {
				const accepted = c.aspects.map((a) => a.label).join(', ');
				addConstraintIssue(errors, warnings, mode, surface,
					`${label(surface)}: aspect ${fmtAspect(dimensions.aspect)} not allowed — accepts ${accepted}.`,
				);
			}
		}
	}

	// Duration validation
	if (durationSeconds != null) {
		for (const surface of surfaces) {
			const c = CONSTRAINTS[surface];
			if (c.maxVideoSeconds != null && durationSeconds > c.maxVideoSeconds) {
				addConstraintIssue(errors, warnings, mode, surface,
					`${label(surface)}: video is ${Math.ceil(durationSeconds)}s, limit is ${c.maxVideoSeconds}s.`,
				);
			}
		}
	}

	return { ok: errors.length === 0, errors, warnings, dimensions, durationSeconds };
}

function addConstraintIssue(
	errors: string[],
	warnings: string[],
	mode: ValidationMode,
	surface: Surface,
	message: string,
): void {
	if (mode === 'native-handoff' && surface.startsWith('ig-')) {
		warnings.push(`${message} Instagram may crop or recompress this during manual posting.`);
		return;
	}
	errors.push(message);
}

function label(s: Surface): string {
	switch (s) {
		case 'ig-feed': return 'IG Feed';
		case 'ig-reel': return 'IG Reel';
		case 'ig-story': return 'IG Story';
		case 'threads': return 'Threads';
	}
}

function fmtBytes(n: number): string {
	if (n > MB) return `${(n / MB).toFixed(1)} MB`;
	return `${(n / 1024).toFixed(0)} KB`;
}

function fmtAspect(a: number): string {
	if (a >= 0.99 && a <= 1.01) return '1:1';
	if (a < 1) return `${a.toFixed(2)}:1`;
	return `${a.toFixed(2)}:1`;
}

function readImageDimensions(file: File): Promise<{ width: number; height: number }> {
	return new Promise((resolve, reject) => {
		const url = URL.createObjectURL(file);
		const img = new Image();
		img.onload = () => {
			URL.revokeObjectURL(url);
			resolve({ width: img.naturalWidth, height: img.naturalHeight });
		};
		img.onerror = () => {
			URL.revokeObjectURL(url);
			reject(new Error('image load failed'));
		};
		img.src = url;
	});
}

function readVideoMeta(file: File): Promise<{ width: number; height: number; duration: number }> {
	return new Promise((resolve, reject) => {
		const url = URL.createObjectURL(file);
		const v = document.createElement('video');
		v.preload = 'metadata';
		v.onloadedmetadata = () => {
			URL.revokeObjectURL(url);
			resolve({
				width: v.videoWidth,
				height: v.videoHeight,
				duration: v.duration,
			});
		};
		v.onerror = () => {
			URL.revokeObjectURL(url);
			reject(new Error('video load failed'));
		};
		v.src = url;
	});
}
