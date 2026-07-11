export var REELS_PROFILES = {
  organic: {
    id: "organic",
    label: "Organic Reels",
    target: "1080x1920 / 30 fps",
    width: 1080,
    height: 1920,
    fps: 30,
    videoBitrate: "18000k",
    maxrate: "24000k",
    bufsize: "36000k",
    audioBitrate: "128k",
    audioRate: 48000,
    minWidth: 720,
    minHeight: 720,
    preferredAspect: 9 / 16,
    aspectTolerance: 0.12,
    minFps: 30,
    maxFileSize: 4 * 1024 * 1024 * 1024,
    videoCodecs: ["h264"],
    containers: ["mov,mp4,m4a,3gp,3g2,mj2", "mp4", "mov"],
    audioCodecs: ["aac"],
    minAudioBitrate: 96000,
  },
  boosted: {
    id: "boosted",
    label: "Boosted Reels",
    target: "1080x1920 / 30 fps / 90s",
    width: 1080,
    height: 1920,
    fps: 30,
    videoBitrate: "18000k",
    maxrate: "24000k",
    bufsize: "36000k",
    audioBitrate: "160k",
    audioRate: 48000,
    minWidth: 720,
    minHeight: 1280,
    preferredAspect: 9 / 16,
    aspectTolerance: 0.04,
    minFps: 30,
    maxDuration: 90,
    maxFileSize: 4 * 1024 * 1024 * 1024,
    videoCodecs: ["h264"],
    containers: ["mov,mp4,m4a,3gp,3g2,mj2", "mp4", "mov"],
    audioCodecs: ["aac"],
    minAudioBitrate: 128000,
  },
  highQuality: {
    id: "highQuality",
    label: "High Quality Reels",
    target: "1440x2560 / 60 fps",
    width: 1440,
    height: 2560,
    fps: 60,
    videoBitrate: "32000k",
    maxrate: "42000k",
    bufsize: "64000k",
    audioBitrate: "192k",
    audioRate: 48000,
    minWidth: 1080,
    minHeight: 1920,
    targetWidth: 1440,
    targetHeight: 2560,
    preferredAspect: 9 / 16,
    aspectTolerance: 0.04,
    minFps: 30,
    targetFps: 60,
    maxFileSize: 4 * 1024 * 1024 * 1024,
    videoCodecs: ["h264"],
    containers: ["mov,mp4,m4a,3gp,3g2,mj2", "mp4", "mov"],
    audioCodecs: ["aac"],
    minAudioBitrate: 128000,
  },
  feedPortrait: {
    id: "feedPortrait",
    label: "Instagram Feed Portrait",
    target: "1080x1350 / 30 fps",
    width: 1080,
    height: 1350,
    fps: 30,
    videoBitrate: "12000k",
    maxrate: "18000k",
    bufsize: "24000k",
    audioBitrate: "128k",
    audioRate: 48000,
    minWidth: 720,
    minHeight: 900,
    preferredAspect: 4 / 5,
    aspectLabel: "4:5",
    aspectTolerance: 0.06,
    minFps: 30,
    maxFileSize: 4 * 1024 * 1024 * 1024,
    videoCodecs: ["h264"],
    containers: ["mov,mp4,m4a,3gp,3g2,mj2", "mp4", "mov"],
    audioCodecs: ["aac"],
    minAudioBitrate: 96000,
  },
  square: {
    id: "square",
    label: "Instagram Square",
    target: "1080x1080 / 30 fps",
    width: 1080,
    height: 1080,
    fps: 30,
    videoBitrate: "10000k",
    maxrate: "16000k",
    bufsize: "22000k",
    audioBitrate: "128k",
    audioRate: 48000,
    minWidth: 720,
    minHeight: 720,
    preferredAspect: 1,
    aspectLabel: "1:1",
    aspectTolerance: 0.04,
    minFps: 30,
    maxFileSize: 4 * 1024 * 1024 * 1024,
    videoCodecs: ["h264"],
    containers: ["mov,mp4,m4a,3gp,3g2,mj2", "mp4", "mov"],
    audioCodecs: ["aac"],
    minAudioBitrate: 96000,
  },
};

export function getReelsProfile(profileId) {
  return REELS_PROFILES[profileId] || REELS_PROFILES.organic;
}

export function applyOutputProfileArgs(args, profileId, hasAudio) {
  var profile = getReelsProfile(profileId);
  args.push("-r", String(profile.fps));
  args.push("-c:v", "libx264", "-profile:v", "high", "-level", profile.fps >= 60 ? "5.1" : "4.2");
  args.push("-b:v", profile.videoBitrate, "-maxrate", profile.maxrate, "-bufsize", profile.bufsize);
  args.push("-pix_fmt", "yuv420p", "-movflags", "+faststart");
  if (hasAudio) {
    args.push("-c:a", "aac", "-b:a", profile.audioBitrate, "-ar", String(profile.audioRate));
  } else {
    args.push("-an");
  }
  return args;
}

export function scaleFilterForProfile(profileId) {
  var profile = getReelsProfile(profileId);
  return "scale=" + profile.width + ":" + profile.height + ":flags=lanczos";
}

export function coverScaleFilterForProfile(profileId) {
  var profile = getReelsProfile(profileId);
  return "scale=" + profile.width + ":" + profile.height + ":force_original_aspect_ratio=increase:flags=lanczos,crop=" + profile.width + ":" + profile.height;
}

export function containBlurFilterForProfile(profileId) {
  var profile = getReelsProfile(profileId);
  var size = profile.width + ":" + profile.height;
  return "split=2[bg][fg];" +
    "[bg]scale=" + size + ":force_original_aspect_ratio=increase:flags=lanczos,crop=" + size + ",boxblur=24:2[bg];" +
    "[fg]scale=" + size + ":force_original_aspect_ratio=decrease:flags=lanczos[fg];" +
    "[bg][fg]overlay=(W-w)/2:(H-h)/2";
}
