// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Demographics Trend Analysis - Phase 3.5
 * Utilities for tracking and analyzing demographic changes over time
 */

export interface DemographicSnapshot {
  date: Date;
  age?: Record<string, number> | undefined;
  gender?: Record<string, number> | undefined;
  topCities?: Array<{ name: string; count: number }> | undefined;
  topCountries?: Array<{ name: string; count: number }> | undefined;
  topInterests?: string[] | undefined;
}

export interface TrendChange {
  label: string;
  current: number | string;
  previous: number | string;
  percentChange: number;
  trend: "up" | "down" | "stable";
}

export interface InterestChange {
  interest: string;
  status: "new" | "stable" | "removed";
  currentRank?: number | undefined;
  previousRank?: number | undefined;
}

export interface DemographicTrends {
  ageShift: {
    direction: "younger" | "older" | "stable";
    description: string;
    topAgeGroup: string;
    previousTopAgeGroup: string;
  };
  genderShift: {
    changes: TrendChange[];
    description: string;
  };
  geographicTrends: {
    trendingCities: Array<{ name: string; growth: number }>;
    decliningCities: Array<{ name: string; decline: number }>;
    newCities: string[];
    trendingCountries: Array<{ name: string; growth: number }>;
    decliningCountries: Array<{ name: string; decline: number }>;
  };
  interestTrends: {
    added: string[];
    removed: string[];
    stable: string[];
    topGrowing: InterestChange[];
  };
  summary: string;
}

/**
 * Calculate the weighted average age from age distribution
 */
function calculateAverageAge(ageDistribution: Record<string, number>): number {
  const ageRanges: Record<string, number> = {
    "13-17": 15,
    "18-24": 21,
    "25-34": 29.5,
    "35-44": 39.5,
    "45-54": 49.5,
    "55-64": 59.5,
    "65+": 70,
  };

  let totalWeight = 0;
  let weightedSum = 0;

  Object.entries(ageDistribution).forEach(([range, count]) => {
    const midpoint = ageRanges[range] || 30;
    weightedSum += midpoint * count;
    totalWeight += count;
  });

  return totalWeight > 0 ? weightedSum / totalWeight : 30;
}

/**
 * Get the top age group from distribution
 */
function getTopAgeGroup(ageDistribution: Record<string, number>): string {
  let topGroup = "";
  let maxCount = 0;

  Object.entries(ageDistribution).forEach(([range, count]) => {
    if (count > maxCount) {
      maxCount = count;
      topGroup = range;
    }
  });

  return topGroup || "Unknown";
}

/**
 * Determine trend direction from percent change
 */
function getTrendDirection(
  percentChange: number,
  threshold = 5,
): "up" | "down" | "stable" {
  if (percentChange > threshold) return "up";
  if (percentChange < -threshold) return "down";
  return "stable";
}

/**
 * Analyze demographic trends between two snapshots
 */
export function analyzeDemographicTrends(
  current: DemographicSnapshot,
  previous: DemographicSnapshot,
): DemographicTrends {
  // Analyze age shift
  const ageShift = analyzeAgeShift(current.age, previous.age);

  // Analyze gender shift
  const genderShift = analyzeGenderShift(current.gender, previous.gender);

  // Analyze geographic trends
  const geographicTrends = analyzeGeographicTrends(
    current.topCities,
    previous.topCities,
    current.topCountries,
    previous.topCountries,
  );

  // Analyze interest trends
  const interestTrends = analyzeInterestTrends(
    current.topInterests,
    previous.topInterests,
  );

  // Generate summary
  const summary = generateTrendSummary(
    ageShift,
    genderShift,
    geographicTrends,
    interestTrends,
  );

  return {
    ageShift,
    genderShift,
    geographicTrends,
    interestTrends,
    summary,
  };
}

/**
 * Analyze age distribution shift
 */
function analyzeAgeShift(
  current?: Record<string, number>,
  previous?: Record<string, number>,
): DemographicTrends["ageShift"] {
  if (!current || !previous) {
    return {
      direction: "stable",
      description: "Insufficient age data for trend analysis",
      topAgeGroup: current ? getTopAgeGroup(current) : "Unknown",
      previousTopAgeGroup: previous ? getTopAgeGroup(previous) : "Unknown",
    };
  }

  const currentAvgAge = calculateAverageAge(current);
  const previousAvgAge = calculateAverageAge(previous);
  const ageDiff = currentAvgAge - previousAvgAge;

  let direction: "younger" | "older" | "stable" = "stable";
  let description = "Your audience age distribution remains stable";

  if (ageDiff > 1.5) {
    direction = "older";
    description = `Your audience is trending ${Math.abs(ageDiff).toFixed(1)} years older on average`;
  } else if (ageDiff < -1.5) {
    direction = "younger";
    description = `Your audience is trending ${Math.abs(ageDiff).toFixed(1)} years younger on average`;
  }

  return {
    direction,
    description,
    topAgeGroup: getTopAgeGroup(current),
    previousTopAgeGroup: getTopAgeGroup(previous),
  };
}

/**
 * Analyze gender distribution shift
 */
function analyzeGenderShift(
  current?: Record<string, number>,
  previous?: Record<string, number>,
): DemographicTrends["genderShift"] {
  const changes: TrendChange[] = [];

  if (!current || !previous) {
    return {
      changes: [],
      description: "Insufficient gender data for trend analysis",
    };
  }

  const currentTotal = Object.values(current).reduce((a, b) => a + b, 0);
  const previousTotal = Object.values(previous).reduce((a, b) => a + b, 0);

  // Compare each gender
  const genders = new Set([...Object.keys(current), ...Object.keys(previous)]);

  genders.forEach((gender) => {
    const currentCount = current[gender] || 0;
    const previousCount = previous[gender] || 0;

    const currentPercent =
      currentTotal > 0 ? (currentCount / currentTotal) * 100 : 0;
    const previousPercent =
      previousTotal > 0 ? (previousCount / previousTotal) * 100 : 0;

    const percentChange = currentPercent - previousPercent;

    changes.push({
      label: gender.charAt(0).toUpperCase() + gender.slice(1),
      current: `${currentPercent.toFixed(1)}%`,
      previous: `${previousPercent.toFixed(1)}%`,
      percentChange,
      trend: getTrendDirection(percentChange, 2),
    });
  });

  // Generate description
  const significantChanges = changes.filter(
    (c) => Math.abs(c.percentChange) > 2,
  );
  let description = "Gender distribution remains balanced";

  if (significantChanges.length > 0) {
    const biggest = significantChanges.reduce(
      (max, curr) =>
        Math.abs(curr.percentChange) > Math.abs(max!.percentChange) ? curr : max,
      significantChanges[0],
    );
    description = `${biggest!.label} audience ${biggest!.trend === "up" ? "increased" : "decreased"} by ${Math.abs(biggest!.percentChange).toFixed(1)} percentage points`;
  }

  return { changes, description };
}

/**
 * Analyze geographic trends
 */
function analyzeGeographicTrends(
  currentCities?: Array<{ name: string; count: number }>,
  previousCities?: Array<{ name: string; count: number }>,
  currentCountries?: Array<{ name: string; count: number }>,
  previousCountries?: Array<{ name: string; count: number }>,
): DemographicTrends["geographicTrends"] {
  const trendingCities: Array<{ name: string; growth: number }> = [];
  const decliningCities: Array<{ name: string; decline: number }> = [];
  const newCities: string[] = [];
  const trendingCountries: Array<{ name: string; growth: number }> = [];
  const decliningCountries: Array<{ name: string; decline: number }> = [];

  // Analyze cities
  if (currentCities && previousCities) {
    const previousCityMap = new Map(
      previousCities.map((c) => [c.name, c.count]),
    );
    const currentTotal = currentCities.reduce((sum, c) => sum + c.count, 0);
    const previousTotal = previousCities.reduce((sum, c) => sum + c.count, 0);

    currentCities.forEach((city) => {
      const prevCount = previousCityMap.get(city.name);

      if (prevCount === undefined) {
        newCities.push(city.name);
      } else {
        const currentShare = currentTotal > 0 ? city.count / currentTotal : 0;
        const previousShare = previousTotal > 0 ? prevCount / previousTotal : 0;
        if (previousShare === 0) return; // Skip — can't compute growth from zero base
        const growth = ((currentShare - previousShare) / previousShare) * 100;

        if (growth > 10) {
          trendingCities.push({ name: city.name, growth });
        } else if (growth < -10) {
          decliningCities.push({ name: city.name, decline: Math.abs(growth) });
        }
      }
    });
  }

  // Analyze countries
  if (currentCountries && previousCountries) {
    const previousCountryMap = new Map(
      previousCountries.map((c) => [c.name, c.count]),
    );
    const currentTotal = currentCountries.reduce((sum, c) => sum + c.count, 0);
    const previousTotal = previousCountries.reduce(
      (sum, c) => sum + c.count,
      0,
    );

    currentCountries.forEach((country) => {
      const prevCount = previousCountryMap.get(country.name);

      if (prevCount !== undefined) {
        const currentShare =
          currentTotal > 0 ? country.count / currentTotal : 0;
        const previousShare = previousTotal > 0 ? prevCount / previousTotal : 0;
        if (previousShare === 0) return; // Skip — can't compute growth from zero base
        const growth = ((currentShare - previousShare) / previousShare) * 100;

        if (growth > 10) {
          trendingCountries.push({ name: country.name, growth });
        } else if (growth < -10) {
          decliningCountries.push({
            name: country.name,
            decline: Math.abs(growth),
          });
        }
      }
    });
  }

  return {
    trendingCities: trendingCities
      .sort((a, b) => b.growth - a.growth)
      .slice(0, 5),
    decliningCities: decliningCities
      .sort((a, b) => b.decline - a.decline)
      .slice(0, 5),
    newCities: newCities.slice(0, 5),
    trendingCountries: trendingCountries
      .sort((a, b) => b.growth - a.growth)
      .slice(0, 5),
    decliningCountries: decliningCountries
      .sort((a, b) => b.decline - a.decline)
      .slice(0, 5),
  };
}

/**
 * Analyze interest trends
 */
function analyzeInterestTrends(
  current?: string[],
  previous?: string[],
): DemographicTrends["interestTrends"] {
  const added: string[] = [];
  const removed: string[] = [];
  const stable: string[] = [];
  const topGrowing: InterestChange[] = [];

  if (!current || !previous) {
    return { added: [], removed: [], stable: current || [], topGrowing: [] };
  }

  const currentSet = new Set(current);
  const previousSet = new Set(previous);

  // Find added interests
  current.forEach((interest, index) => {
    if (!previousSet.has(interest)) {
      added.push(interest);
      topGrowing.push({
        interest,
        status: "new",
        currentRank: index + 1,
      });
    } else {
      stable.push(interest);
    }
  });

  // Find removed interests
  previous.forEach((interest) => {
    if (!currentSet.has(interest)) {
      removed.push(interest);
    }
  });

  // Calculate rank changes for stable interests
  stable.forEach((interest) => {
    const currentRank = current.indexOf(interest) + 1;
    const previousRank = previous.indexOf(interest) + 1;
    const rankChange = previousRank - currentRank;

    if (rankChange > 0) {
      topGrowing.push({
        interest,
        status: "stable",
        currentRank,
        previousRank,
      });
    }
  });

  return {
    added,
    removed,
    stable,
    topGrowing: topGrowing.slice(0, 5),
  };
}

/**
 * Generate human-readable trend summary
 */
function generateTrendSummary(
  ageShift: DemographicTrends["ageShift"],
  genderShift: DemographicTrends["genderShift"],
  geographicTrends: DemographicTrends["geographicTrends"],
  interestTrends: DemographicTrends["interestTrends"],
): string {
  const insights: string[] = [];

  // Age insight
  if (ageShift.direction !== "stable") {
    insights.push(ageShift.description);
  }

  // Gender insight
  if (genderShift.changes.some((c) => c.trend !== "stable")) {
    insights.push(genderShift.description);
  }

  // Geographic insight
  if (geographicTrends.trendingCities.length > 0) {
    insights.push(
      `Growing audience in ${geographicTrends.trendingCities[0]!.name}`,
    );
  } else if (geographicTrends.trendingCountries.length > 0) {
    insights.push(
      `Expanding reach in ${geographicTrends.trendingCountries[0]!.name}`,
    );
  }

  // Interest insight
  if (interestTrends.added.length > 0) {
    insights.push(`New interest: ${interestTrends.added[0]}`);
  }

  if (insights.length === 0) {
    return "Your audience demographics remain stable month-over-month.";
  }

  return `${insights.join(". ")}.`;
}

/**
 * Get trend arrow emoji based on direction
 */
export function getTrendArrow(
  trend: "up" | "down" | "stable",
): "↗️" | "↘️" | "➡️" {
  switch (trend) {
    case "up":
      return "↗️";
    case "down":
      return "↘️";
    default:
      return "➡️";
  }
}

/**
 * Get trend color based on direction (for positive/negative connotation)
 */
export function getTrendColor(
  trend: "up" | "down" | "stable",
  isPositive = true,
): string {
  if (trend === "stable") return "gray";
  if (isPositive) {
    return trend === "up" ? "green" : "red";
  }
  return trend === "up" ? "red" : "green";
}

export default {
  analyzeDemographicTrends,
  getTrendArrow,
  getTrendColor,
};
