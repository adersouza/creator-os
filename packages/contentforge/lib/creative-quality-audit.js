function advisoryWarning(code, label, message, severity = "warn") {
  return { code, label, message, severity };
}

function uniqueWarnings(warnings) {
  var seen = new Set();
  return (warnings || []).filter(function (warning) {
    var key = warning.code + ":" + warning.message;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function normalizeText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function wordList(value) {
  return normalizeText(value).split(" ").filter(Boolean);
}

function levelFromScore(score) {
  if (score >= 78) return "strong";
  if (score >= 55) return "medium";
  return "weak";
}

function average(values) {
  var valid = values.filter(Number.isFinite);
  return valid.length ? valid.reduce(function (sum, value) { return sum + value; }, 0) / valid.length : null;
}

function earlyHookText(ocr) {
  var seen = new Set();
  return (ocr?.results || [])
    .filter(function (item) { return (item.timeSec || 0) <= 3; })
    .map(function (item) { return item.ocrText || ""; })
    .filter(function (text) {
      var key = normalizeText(text);
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .join(" ")
    .trim();
}

function hasSpecificity(words, text) {
  if (/\d/.test(text)) return true;
  var specificTokens = new Set([
    "before", "after", "mistake", "mistakes", "reason", "reasons", "steps", "watch",
    "cost", "save", "reach", "views", "sales", "client", "clients", "money", "days",
    "seconds", "minutes", "instead", "without", "stop", "start", "proof", "result",
  ]);
  return words.some(function (word) { return specificTokens.has(word); });
}

function isGenericHook(words, text) {
  if (!words.length) return false;
  var genericPhrases = [
    "you need this",
    "watch this",
    "this is crazy",
    "this changed everything",
    "you wont believe",
    "wait for it",
    "check this out",
  ];
  if (genericPhrases.some(function (phrase) { return text.includes(phrase); })) return true;
  var vague = new Set(["this", "that", "thing", "things", "secret", "crazy", "insane", "hack", "tips", "trick"]);
  var vagueCount = words.filter(function (word) { return vague.has(word); }).length;
  return words.length <= 5 && vagueCount >= 2 && !hasSpecificity(words, text);
}

function scoreHookClarity(advisory) {
  var text = earlyHookText(advisory.ocr);
  var normalized = normalizeText(text);
  var words = wordList(text);
  var earlyResults = (advisory.ocr?.results || []).filter(function (item) { return (item.timeSec || 0) <= 3; });
  var confidence = average(earlyResults.map(function (item) { return item.confidence; }));
  var warnings = [];
  var score = 45;

  if (!words.length) {
    warnings.push(advisoryWarning("creative_hook_missing", "Hook text missing", "No readable hook text was detected in the first 3 seconds"));
    return {
      level: "weak",
      score: 20,
      text: "",
      wordCount: 0,
      confidence,
      warnings,
    };
  }

  score = 65;
  if (confidence !== null && confidence >= 70) score += 10;
  if (hasSpecificity(words, normalized)) score += 12;
  if (words.length >= 4 && words.length <= 11) score += 8;
  if (words.length < 3) {
    score -= 22;
    warnings.push(advisoryWarning("creative_hook_too_short", "Hook may be too short", "Opening hook may not provide enough context"));
  }
  if (words.length > 14) {
    score -= 18;
    warnings.push(advisoryWarning("creative_hook_too_long", "Hook may be too long", "Opening hook may be hard to read quickly"));
  }
  if (isGenericHook(words, normalized)) {
    score -= 18;
    warnings.push(advisoryWarning("creative_hook_generic", "Hook may be generic", "Opening hook is readable but may not communicate a specific angle"));
  }
  if (confidence !== null && confidence < 55) {
    score -= 15;
    warnings.push(advisoryWarning("creative_hook_low_confidence", "Hook readability uncertain", "Opening hook text has low OCR confidence"));
  }

  score = Math.max(0, Math.min(100, Math.round(score)));
  return {
    level: levelFromScore(score),
    score,
    text,
    wordCount: words.length,
    confidence: confidence === null ? null : Math.round(confidence),
    warnings,
  };
}

function scoreVisualClarity(advisory) {
  var candidates = advisory.coverCandidates || [];
  var coverScore = average(candidates.map(function (candidate) { return candidate.score; }));
  var brightness = average(candidates.map(function (candidate) { return candidate.stats?.brightness; }));
  var edgeScore = average(candidates.map(function (candidate) { return candidate.stats?.edgeScore; }));
  var warnings = [];
  var score = coverScore === null ? 55 : coverScore;
  if ((advisory.readabilityScore || 0) > 0) {
    score = (score * 0.65) + (advisory.readabilityScore * 0.35);
  }
  if (brightness !== null && brightness < 40) {
    score -= 18;
    warnings.push(advisoryWarning("creative_visual_too_dark", "Visual may be too dark", "Sampled frames are dark enough to reduce review clarity"));
  }
  if (edgeScore !== null && edgeScore < 8) {
    score -= 15;
    warnings.push(advisoryWarning("creative_visual_soft", "Visual may be soft", "Sampled frames have low edge detail and may read as blurry"));
  }
  if ((advisory.readabilityScore || 0) > 0 && advisory.readabilityScore < 55) {
    score -= 12;
    warnings.push(advisoryWarning("creative_visual_unclear", "Visual clarity needs review", "Caption readability or frame clarity is low"));
  }
  score = Math.max(0, Math.min(100, Math.round(score)));
  return {
    level: levelFromScore(score),
    score,
    brightness: brightness === null ? null : Math.round(brightness),
    edgeScore: edgeScore === null ? null : Math.round(edgeScore),
    warnings,
  };
}

function scoreSubjectVisibility(advisory) {
  var candidates = advisory.coverCandidates || [];
  var brightness = average(candidates.map(function (candidate) { return candidate.stats?.brightness; }));
  var edgeScore = average(candidates.map(function (candidate) { return candidate.stats?.edgeScore; }));
  var contrast = average(candidates.map(function (candidate) { return candidate.stats?.contrast; }));
  var warnings = [];
  var score = 55;

  if (brightness !== null) score += Math.max(-20, Math.min(15, (brightness - 70) / 3));
  if (edgeScore !== null) score += Math.max(-18, Math.min(20, (edgeScore - 8) * 3));
  if (contrast !== null) score += Math.max(-12, Math.min(15, (contrast - 35) / 2));

  if (!candidates.length) {
    warnings.push(advisoryWarning("creative_subject_uncertain", "Subject visibility uncertain", "No sampled cover frames were available for subject visibility review"));
    score = 35;
  } else if ((brightness !== null && brightness < 38) || (edgeScore !== null && edgeScore < 7)) {
    warnings.push(advisoryWarning("creative_subject_unclear", "Subject may be unclear", "Main subject may not be visually clear in sampled frames"));
  }

  score = Math.max(0, Math.min(100, Math.round(score)));
  return {
    level: levelFromScore(score),
    score,
    method: "heuristic_frame_clarity",
    modelBacked: false,
    brightness: brightness === null ? null : Math.round(brightness),
    edgeScore: edgeScore === null ? null : Math.round(edgeScore),
    contrast: contrast === null ? null : Math.round(contrast),
    warnings,
  };
}

function scoreOpeningStrength(advisory) {
  var metrics = advisory.hookVisibility?.metrics || {};
  var avgDelta = metrics.avgFrameDelta;
  var earlyTextBoxes = metrics.earlyTextBoxes || 0;
  var warnings = [];
  var score = advisory.hookVisibilityScore ?? 50;
  if (earlyTextBoxes > 0) score += 10;
  if (Number.isFinite(avgDelta)) {
    if (avgDelta >= 14) score += 10;
    else if (avgDelta < 6) {
      score -= 18;
      warnings.push(advisoryWarning("creative_opening_static", "Opening may feel static", "First 3 seconds have limited visual change"));
    }
  }
  if (earlyTextBoxes === 0) {
    score -= 18;
    warnings.push(advisoryWarning("creative_opening_no_early_hook", "Opening lacks early hook", "No readable hook text appears in the first 3 seconds"));
  }
  score = Math.max(0, Math.min(100, Math.round(score)));
  return {
    level: levelFromScore(score),
    score,
    earlyTextBoxes,
    avgFrameDelta: avgDelta ?? null,
    warnings,
  };
}

export function buildCreativeQualityAudit(advisory) {
  var hookClarity = scoreHookClarity(advisory);
  var visualClarity = scoreVisualClarity(advisory);
  var subjectVisibility = scoreSubjectVisibility(advisory);
  var openingStrength = scoreOpeningStrength(advisory);
  var score = Math.round(
    (hookClarity.score * 0.32) +
    (openingStrength.score * 0.28) +
    (visualClarity.score * 0.22) +
    (subjectVisibility.score * 0.18)
  );
  var warnings = uniqueWarnings([
    ...hookClarity.warnings,
    ...visualClarity.warnings,
    ...subjectVisibility.warnings,
    ...openingStrength.warnings,
  ]);
  return {
    available: true,
    semanticEngine: "heuristic_v1",
    modelBacked: false,
    verdict: warnings.length ? "warn" : "pass",
    score,
    hookClarity,
    subjectVisibility,
    visualClarity,
    openingStrength,
    warnings,
    metrics: {
      frameSamples: advisory.ocr?.frameSamples || advisory.safeZone?.metrics?.frameSamples || 0,
      ocrTextBoxesDetected: advisory.ocr?.results?.reduce(function (sum, item) {
        return sum + (item.captionBoxes?.length || 0);
      }, 0) || 0,
      coverCandidates: advisory.coverCandidates?.length || 0,
    },
  };
}
