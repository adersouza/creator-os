import { execFile } from "child_process";
import { mkdir, writeFile } from "fs/promises";
import path from "path";
import sharp from "sharp";

const ROOT = path.resolve("test/fixtures/campaign-factory");

function run(command, args) {
  return new Promise((resolve, reject) => {
    execFile(command, args, { timeout: 120000, maxBuffer: 4 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) {
        error.stdout = stdout;
        error.stderr = stderr;
        reject(error);
        return;
      }
      resolve({ stdout, stderr });
    });
  });
}

async function ensureDirs() {
  await Promise.all([
    mkdir(path.join(ROOT, "good"), { recursive: true }),
    mkdir(path.join(ROOT, "warnings"), { recursive: true }),
    mkdir(path.join(ROOT, "failures"), { recursive: true }),
    mkdir(path.join(ROOT, ".generated"), { recursive: true }),
    mkdir(path.join(ROOT, "manifests"), { recursive: true }),
  ]);
}

async function createTextOverlay(name, { text, color = "#ffffff", width = 900, height = 190, fontSize = 84 }) {
  var output = path.join(ROOT, ".generated", name);
  var svg = `
    <svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
      <rect width="100%" height="100%" fill="transparent"/>
      <text x="18" y="${fontSize + 10}" font-family="Arial, Helvetica, sans-serif" font-weight="800" font-size="${fontSize}" fill="${color}">${text}</text>
      <text x="18" y="${fontSize * 2 + 34}" font-family="Arial, Helvetica, sans-serif" font-weight="800" font-size="${fontSize}" fill="${color}">WATCH NOW</text>
    </svg>
  `;
  await sharp(Buffer.from(svg)).png().toFile(output);
  return output;
}

function baseMp4Args({ lavfi, output, duration = 1.2, vf = null, crf = "20", overlay = null, overlayX = 120, overlayY = 880 }) {
  var args = [
    "-hide_banner", "-loglevel", "error", "-y",
    "-f", "lavfi", "-i", lavfi,
  ];
  if (overlay) {
    args.push("-loop", "1", "-i", overlay);
  }
  args.push(
    "-t", String(duration),
    "-an",
    "-c:v", "libx264",
    "-preset", "ultrafast",
    "-profile:v", "high",
    "-level", "4.1",
    "-pix_fmt", "yuv420p",
    "-r", "30",
    "-g", "60",
    "-keyint_min", "60",
    "-sc_threshold", "0",
    "-crf", crf,
  );
  if (overlay) {
    var filter = vf ? "[0:v]" + vf + "[base];[base][1:v]overlay=" + overlayX + ":" + overlayY : "[0:v][1:v]overlay=" + overlayX + ":" + overlayY;
    args.push("-filter_complex", filter);
  } else if (vf) {
    args.push("-vf", vf);
  }
  args.push(
    "-movflags", "+faststart",
    "-brand", "mp42",
    "-metadata", "creation_time=2026-05-14T12:00:00Z",
    "-metadata:s:v:0", "handler_name=Core Media Video",
    output
  );
  return args;
}

async function createFixture(relativePath, options) {
  await run("ffmpeg", baseMp4Args({
    ...options,
    output: path.join(ROOT, relativePath),
  }));
}

export async function generateCampaignFactoryFixtures() {
  await ensureDirs();
  var whiteCaption = await createTextOverlay("white-caption.png", { text: "BIG HOOK" });
  var edgeCaption = await createTextOverlay("edge-caption.png", { text: "EDGE HOOK", width: 1000 });
  var lowContrastCaption = await createTextOverlay("low-contrast-caption.png", { text: "LOW CONTRAST", color: "#3f3f3f" });
  var smallCaption = await createTextOverlay("small-caption.png", { text: "SMALL HOOK", color: "#ffffff", width: 800, height: 190, fontSize: 64 });

  await createFixture("good/campaign_factory_avconvert_render.mp4", {
    lavfi: "testsrc=size=1080x1920:rate=30",
    duration: 1.2,
    overlay: whiteCaption,
    overlayX: 120,
    overlayY: 840,
  });
  await createFixture("good/iphone_reel_upload_ready.mp4", {
    lavfi: "smptebars=size=1080x1920:rate=30",
    duration: 1.2,
  });
  await createFixture("good/android_reel_upload_ready.mp4", {
    lavfi: "testsrc2=size=1080x1920:rate=30",
    duration: 1.2,
  });

  await createFixture("warnings/caption_too_close_to_edge.mp4", {
    lavfi: "color=c=black:s=1080x1920:r=30",
    duration: 1.2,
    overlay: edgeCaption,
    overlayX: 10,
    overlayY: 1670,
  });
  await createFixture("warnings/caption_bottom_ui_zone.mp4", {
    lavfi: "color=c=black:s=1080x1920:r=30",
    duration: 1.2,
    overlay: whiteCaption,
    overlayX: 140,
    overlayY: 1700,
  });
  await createFixture("warnings/low_contrast_caption.mp4", {
    lavfi: "color=c=black:s=1080x1920:r=30",
    duration: 1.2,
    overlay: lowContrastCaption,
    overlayX: 140,
    overlayY: 880,
  });
  await createFixture("warnings/static_opening.mp4", {
    lavfi: "color=c=black:s=1080x1920:r=30",
    duration: 3.4,
  });
  await createFixture("warnings/weak_first_3_seconds.mp4", {
    lavfi: "color=c=0x101010:s=1080x1920:r=30",
    duration: 3.4,
  });
  await createFixture("warnings/overcompressed_but_playable.mp4", {
    lavfi: "testsrc=size=1080x1920:rate=30",
    duration: 1.2,
    crf: "38",
  });
  await createFixture("warnings/small_caption_complex_bg.mp4", {
    lavfi: "testsrc2=size=1080x1920:rate=30",
    duration: 1.2,
    overlay: smallCaption,
    overlayX: 230,
    overlayY: 920,
  });

  await writeFile(path.join(ROOT, "failures/corrupt_video.mp4"), "not a valid mp4\n");
  await writeFile(path.join(ROOT, "failures/invalid_container.mp4"), "not a valid mp4 container\n");
  await writeFile(path.join(ROOT, "failures/unreadable_caption_severe.mp4"), "not a valid mp4\n");

  return ROOT;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  generateCampaignFactoryFixtures()
    .then((root) => {
      console.log(`Generated Campaign Factory fixtures in ${root}`);
    })
    .catch((error) => {
      console.error(error.stderr || error.message);
      process.exit(1);
    });
}
