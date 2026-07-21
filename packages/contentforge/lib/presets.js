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
