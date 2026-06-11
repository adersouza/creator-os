import crypto from "crypto";
import path from "path";
import { mkdir } from "fs/promises";
import sharp from "sharp";

function escapeXml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function wrapText(text, maxChars) {
  var words = String(text || "").trim().split(/\s+/).filter(Boolean);
  var lines = [];
  var current = "";
  for (var word of words) {
    var next = current ? current + " " + word : word;
    if (next.length > maxChars && current) {
      lines.push(current);
      current = word;
    } else {
      current = next;
    }
  }
  if (current) lines.push(current);
  return lines.slice(0, 3);
}

export function overlayYExpression(position) {
  if (position === "top") return "100";
  if (position === "center") return "(H-h)/2";
  return "H-h-120";
}

export async function createTextOverlayPng(options = {}) {
  var text = (options.overlayText || options.watermarkText || "").trim();
  if (!text) return null;
  var outputDir = options.outputDir;
  if (!outputDir) return null;

  await mkdir(outputDir, { recursive: true });
  var fontSize = Math.max(18, Math.min(96, parseInt(options.overlayFontSize, 10) || 42));
  var opacity = Math.max(0.35, Math.min(1, parseFloat(options.overlayOpacity) || 0.9));
  var boxOpacity = Math.max(0.18, Math.min(0.65, opacity * 0.42));
  var width = Math.max(320, Math.min(1280, Math.round((parseInt(options.width, 10) || 1080) * 0.84)));
  var lines = wrapText(text.slice(0, 120), Math.max(14, Math.floor(width / (fontSize * 0.58))));
  var lineHeight = Math.round(fontSize * 1.22);
  var paddingX = Math.round(fontSize * 0.58);
  var paddingY = Math.round(fontSize * 0.45);
  var height = Math.max(fontSize + paddingY * 2, lines.length * lineHeight + paddingY * 2);
  var startY = paddingY + Math.round(fontSize * 0.82);
  var tspans = lines.map(function (line, index) {
    return "<text x=\"50%\" y=\"" + (startY + index * lineHeight) + "\" text-anchor=\"middle\">" + escapeXml(line) + "</text>";
  }).join("");
  var svg = "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"" + width + "\" height=\"" + height + "\">" +
    "<rect x=\"0\" y=\"0\" width=\"100%\" height=\"100%\" rx=\"" + Math.round(fontSize * 0.28) + "\" fill=\"rgba(0,0,0," + boxOpacity.toFixed(2) + ")\"/>" +
    "<g font-family=\"Arial, Helvetica, sans-serif\" font-size=\"" + fontSize + "\" font-weight=\"700\" fill=\"rgba(255,255,255," + opacity.toFixed(2) + ")\">" +
    tspans +
    "</g></svg>";
  var filename = "overlay_" + crypto.createHash("sha1").update(svg).digest("hex").slice(0, 12) + ".png";
  var outputPath = path.join(outputDir, filename);
  await sharp(Buffer.from(svg)).png().toFile(outputPath);
  return outputPath;
}
