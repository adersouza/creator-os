export const CAMPAIGN_FACTORY_AUDIT_CONFIG = {
  schema: "contentforge.campaign_factory_thresholds.v1",
  profile: "campaign_factory_v1",
  thresholds: {
    // Calibrated against generated vertical reel fixtures; tighten only after labeled real-corpus evidence.
    minSocialWidth: 720,
    minSocialHeight: 1280,
    verticalAspectRatio: 9 / 16,
    verticalAspectTolerance: 0.12,

    // Reels safe-zone heuristics: keep captions away from edges, bottom UI, and right-side controls.
    captionEdgeMarginRatio: 0.06,
    rightUiStartRatio: 0.78,
    rightUiMinYRatio: 0.22,
    bottomUiStartRatio: 0.82,
    topUiEndRatio: 0.06,

    // OCR/readability defaults from synthetic caption fixtures; blocking only for Campaign Factory fan-out.
    ocrLowConfidence: 55,
    captionLowContrast: 55,
    captionMinHeightRatio: 0.035,
    heuristicLowContrast: 70,

    // Hook signals block Campaign Factory fan-out; cover signals remain ranking aids.
    staticOpeningDelta: 6,
    weakOpeningDelta: 10,
    coverCandidateSimilarityDelta: 8,
    coverDarkBrightness: 35,
    coverBlurEdgeScore: 8,

    // Watchability gates use available deterministic FFmpeg evidence. Optional filters stay advisory when absent.
    minVmaf: 78,
    maxCambi: 18,
    minIntegratedLufs: -20,
    maxIntegratedLufs: -8,
    maxTruePeakDb: -1,

    // Local workstation soft target for generated fixtures; report-only.
    advisoryLatencySoftLimitMs: 5000,

    // Campaign Factory fan-out blocks unless every source/sibling comparison clears these conservative targets.
    pdqSafeDistance: 40,
    sscdSafeSimilarity: 0.50,

    // Multi-account originality checks are advisory. They compare requested references only by default.
    originalityMaxReferenceFiles: 12,
    originalityOpeningHighSimilarity: 82,
    originalityOpeningMediumSimilarity: 62,
    originalityCoverHighSimilarity: 84,
    originalityCoverMediumSimilarity: 64,
    originalityHookHighSimilarity: 0.72,
    originalityHookMediumSimilarity: 0.48,
    originalityOverallHighRisk: 78,
    originalityOverallMediumRisk: 55,
  },
  sampling: {
    maxVideos: 5,
    ocrFrameTimesSec: [0.4, 1.4, 2.6],
    coverCandidateFractions: [0.25, 0.55],
  },
};

export function campaignFactoryThresholds() {
  return CAMPAIGN_FACTORY_AUDIT_CONFIG.thresholds;
}
