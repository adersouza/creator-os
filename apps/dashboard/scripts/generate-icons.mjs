import sharp from "sharp";
import { mkdirSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = join(__dirname, "..", "public", "icons");
mkdirSync(outDir, { recursive: true });

const sizes = [192, 512];
const brandBlue = "#0930ef";

for (const size of sizes) {
  const fontSize = Math.round(size * 0.38);
  const yOffset = Math.round(size * 0.58);
  const cornerRadius = Math.round(size * 0.18);

  const svg = `<svg width="${size}" height="${size}" xmlns="http://www.w3.org/2000/svg">
    <rect width="${size}" height="${size}" rx="${cornerRadius}" fill="${brandBlue}"/>
    <text x="50%" y="${yOffset}" text-anchor="middle"
      font-family="Inter, Helvetica, Arial, sans-serif"
      font-weight="700" font-size="${fontSize}" fill="#ffffff">TD</text>
  </svg>`;

  await sharp(Buffer.from(svg))
    .png()
    .toFile(join(outDir, `icon-${size}.png`));

  console.log(`Created icon-${size}.png`);
}

// Also create a favicon.ico (32x32 PNG, browsers accept it)
const faviconSvg = `<svg width="32" height="32" xmlns="http://www.w3.org/2000/svg">
  <rect width="32" height="32" rx="6" fill="${brandBlue}"/>
  <text x="50%" y="22" text-anchor="middle"
    font-family="Inter, Helvetica, Arial, sans-serif"
    font-weight="700" font-size="14" fill="#ffffff">TD</text>
</svg>`;

await sharp(Buffer.from(faviconSvg))
  .png()
  .toFile(join(outDir, "..", "favicon.ico"));

console.log("Created favicon.ico");
console.log("Done!");
