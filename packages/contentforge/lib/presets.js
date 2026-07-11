export const PLATFORM_PRESETS = [
  {
    id: "tiktok",
    label: "TikTok",
    sub: "FYP Optimized",
    edits: 5,
    spins: 10,
    variantPreset: "quality",
    flip: false,
    vert: true,
    icon: "\u25B6",
    mediaType: "video",
  },
  {
    id: "reels",
    label: "Reels",
    sub: "Quality First",
    edits: 8,
    spins: 6,
    variantPreset: "quality",
    flip: false,
    vert: true,
    icon: "\u25C9",
    mediaType: "video",
  },
  {
    id: "both",
    label: "Multi",
    sub: "All Platforms",
    edits: 10,
    spins: 5,
    variantPreset: "quality",
    flip: false,
    vert: true,
    icon: "\u2B21",
    mediaType: "video",
  },
  {
    id: "custom",
    label: "Custom",
    sub: "Full Control",
    edits: 5,
    spins: 5,
    variantPreset: "custom",
    flip: false,
    vert: false,
    icon: "\u2699",
    mediaType: "video",
  },
];

export const IMAGE_PRESETS = [
  {
    id: "ig-feed",
    label: "IG Feed",
    sub: "Quality First",
    variants: 50,
    variantPreset: "quality",
    icon: "\u25A3",
  },
  {
    id: "ig-stories",
    label: "IG Stories",
    sub: "9:16 Optimized",
    variants: 50,
    variantPreset: "quality",
    icon: "\u25AF",
  },
  {
    id: "ig-mass",
    label: "Batch Export",
    sub: "High Volume",
    variants: 150,
    variantPreset: "light",
    icon: "\u2B22",
  },
  {
    id: "img-custom",
    label: "Custom",
    sub: "Full Control",
    variants: 25,
    variantPreset: "custom",
    icon: "\u2699",
  },
];

export const MANIPULATION_LEVELS = [
  {
    id: "clean",
    label: "Clean",
    ssim: "0.99",
    risk: "None",
    compat: "All",
    color: "#38bdf8",
    desc: "Imperceptible crop \u00B7 micro time warp \u00B7 pitch shift",
    imgDesc: "3-5% crop \u00B7 JPEG quality variation only",
    barPct: 15,
  },
  {
    id: "light",
    label: "Light",
    ssim: "0.95",
    risk: "Low",
    compat: "TikTok",
    color: "#4ade80",
    desc: "Pixel noise \u00B7 color shift \u00B7 speed \u00B7 zoom",
    imgDesc: "Sub-perceptual crop \u00B7 JPEG quality variation",
    barPct: 30,
  },
  {
    id: "medium",
    label: "Medium",
    ssim: "0.88",
    risk: "Med",
    compat: "TT + Reels",
    color: "#fbbf24",
    desc: "+ text overlays \u00B7 borders \u00B7 rotation",
    imgDesc: "+ CIE LCh color modulation \u00B7 sub-degree rotation",
    barPct: 55,
  },
  {
    id: "heavy",
    label: "Heavy",
    ssim: "0.78",
    risk: "High",
    compat: "Strict",
    color: "#fb923c",
    desc: "+ color grades \u00B7 reverb \u00B7 sharpening",
    imgDesc: "+ gamma shift \u00B7 sharpen \u00B7 noise injection",
    barPct: 80,
  },
  {
    id: "stealth",
    label: "Stealth",
    ssim: "0.91",
    risk: "Max",
    compat: "All",
    color: "#c084fc",
    // Research-backed: targets PDQ 64x64 DCT grid + CNN/ViT neural embeddings
    desc: "Drift crop \u00B7 time warp \u00B7 luma wave",
    imgDesc: "3-5% crop (PDQ grid shift) \u00B7 LCh modulate \u00B7 rotation \u00B7 mozjpeg",
    barPct: 70,
  },
];

// Effectiveness estimates (updated with PDQ/IG research, April 2026)
// PDQ: 256-bit DCT hash, 31-bit Hamming threshold. Crop is #1 weakness.
// IG also uses CNN/ViT neural embeddings — rotation + modulation defeats these.
export const EFFECTIVENESS = {
  clean:   { tt: 70, ig: 60, yt: 75 },
  light:   { tt: 55, ig: 40, yt: 65 },
  medium:  { tt: 75, ig: 65, yt: 82 },
  heavy:   { tt: 88, ig: 82, yt: 90 },
  stealth: { tt: 94, ig: 92, yt: 95 },
};

// Image-specific effectiveness (simpler pipeline, but images are easier to differentiate)
export const IMAGE_EFFECTIVENESS = {
  clean:   { ig: 55, fb: 50 },
  light:   { ig: 50, fb: 45 },
  medium:  { ig: 75, fb: 70 },
  heavy:   { ig: 88, fb: 85 },
  stealth: { ig: 95, fb: 92 },
};

export const COLOR_PRESETS = [
  { name: "original", eq: "" },
  { name: "warm", eq: "colortemperature=temperature=7500" },
  { name: "cool", eq: "colortemperature=temperature=4500" },
  { name: "matte", eq: "curves=preset=lighter,eq=contrast=0.85:saturation=0.7" },
  { name: "high-contrast", eq: "eq=contrast=1.4:saturation=1.15" },
  { name: "vintage", eq: "curves=preset=vintage" },
  { name: "vivid", eq: "eq=saturation=1.4:contrast=1.1" },
  { name: "cross-process", eq: "curves=preset=cross_process" },
  { name: "soft-warm", eq: "colortemperature=temperature=6500,eq=contrast=0.9:brightness=0.03" },
  { name: "moody-dark", eq: "eq=brightness=-0.06:contrast=1.2:saturation=0.8" },
];

export const HOOK_TEXTS = [
  "Follow for more",
  "Link in bio",
  "Wait for it",
  "Watch till the end",
  "POV:",
  "Story time",
  "Part 1",
  "Part 2",
  "Part 3",
  "You need to see this",
  "This changed everything",
  "Save this",
  "Don't scroll",
  "Hear me out",
  "Hot take",
];

export const CROP_STYLES = [
  { name: "center", x: "0.5", y: "0.5" },
  { name: "left", x: "0.35", y: "0.5" },
  { name: "right", x: "0.65", y: "0.5" },
  { name: "top", x: "0.5", y: "0.35" },
  { name: "bottom", x: "0.5", y: "0.65" },
];

export const BORDER_STYLES = [
  "none",
  "vignette",
  "thin-white",
  "letterbox",
  "dark-gray",
];

export const DEVICE_PREFIXES = [
  "IMG_",
  "VID_",
  "PXL_",
  "RPReplay_",
  "MOV_",
  "TRIM_",
  "InShot_",
  "SnapSave_",
];

export const DAYS = ["MON", "TUE", "WED", "THU", "FRI"];
