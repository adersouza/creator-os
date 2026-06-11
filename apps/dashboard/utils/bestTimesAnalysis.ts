/**
 * Best Times Analysis Utility
 *
 * Analyzes user's published post performance by day and hour to generate
 * personalized "Best Times to Post" heatmap based on actual engagement data.
 */

export interface TimeSlotPerformance {
  day: number; // 0-6 (Sun-Sat)
  hour: number; // 0-23
  postCount: number;
  totalEngagement: number;
  avgEngagementRate: number;
  totalViews: number;
  totalLikes: number;
  totalReplies: number;
  totalReposts: number;
}

export interface BestTimesResult {
  heatmap: { day: number; hour: number; score: number }[];
  topSlots: TimeSlotPerformance[];
  insights: {
    bestDay: string;
    bestHour: number;
    avgEngagementByDay: Record<number, number>;
    avgEngagementByHour: Record<number, number>;
    hasEnoughData: boolean;
    postCount: number;
  };
}

/**
 * Converts various date formats to JavaScript Date object
 */
function toDate(value: any): Date {
  if (value instanceof Date) return value;
  if (value?.toDate && typeof value.toDate === 'function') {
    return value.toDate(); // Firestore Timestamp
  }
  if (typeof value === 'string') return new Date(value);
  return new Date();
}

/**
 * Analyze user's post performance by time to generate personalized best times heatmap
 */
export async function analyzeBestPostingTimes(
  posts: any[]
): Promise<BestTimesResult> {
  // Filter published posts with performance data
  const publishedPosts = posts.filter(p =>
    p.status === 'published' &&
    p.publishedAt &&
    p.performance &&
    p.performance.views > 0
  );

  // If insufficient data, return default industry-based heatmap
  if (publishedPosts.length < 5) {
    return generateDefaultHeatmap(publishedPosts.length);
  }

  // Group posts by (day, hour) time slots
  const slotMap = new Map<string, TimeSlotPerformance>();

  publishedPosts.forEach(post => {
    const publishedDate = toDate(post.publishedAt);
    const day = publishedDate.getDay(); // 0-6
    const hour = publishedDate.getHours(); // 0-23
    const key = `${day}-${hour}`;

    // Calculate weighted engagement score
    // Replies and reposts are weighted higher as they indicate stronger engagement
    const engagement =
      (post.performance.likes || 0) +
      (post.performance.replies || 0) * 2 +
      (post.performance.reposts || 0) * 1.5 +
      (post.performance.quotes || 0) * 1.5;

    const views = post.performance.views || 1;
    const engagementRate = (engagement / views) * 100;

    const existing = slotMap.get(key);
    if (existing) {
      existing.postCount++;
      existing.totalEngagement += engagement;
      existing.totalViews += views;
      existing.totalLikes += post.performance.likes || 0;
      existing.totalReplies += post.performance.replies || 0;
      existing.totalReposts += post.performance.reposts || 0;
      existing.avgEngagementRate =
        (existing.totalEngagement / existing.totalViews) * 100;
    } else {
      slotMap.set(key, {
        day,
        hour,
        postCount: 1,
        totalEngagement: engagement,
        avgEngagementRate: engagementRate,
        totalViews: views,
        totalLikes: post.performance.likes || 0,
        totalReplies: post.performance.replies || 0,
        totalReposts: post.performance.reposts || 0,
      });
    }
  });

  // Calculate scores (0-100) for each time slot
  const slots = Array.from(slotMap.values());
  const maxEngagement = Math.max(...slots.map(s => s.avgEngagementRate), 1);

  const heatmap: { day: number; hour: number; score: number }[] = [];

  // Generate heatmap for all hours from 6 AM to 11 PM (active hours)
  for (let day = 0; day < 7; day++) {
    for (let hour = 6; hour < 24; hour++) {
      const key = `${day}-${hour}`;
      const slot = slotMap.get(key);

      let score = 30; // Base score for no data

      if (slot && slot.postCount >= 2) {
        // Multiple posts - use normalized engagement rate
        score = Math.min(100, (slot.avgEngagementRate / maxEngagement) * 100);
      } else if (slot && slot.postCount === 1) {
        // Single post - use engagement but cap at 70 to indicate uncertainty
        score = Math.min(70, (slot.avgEngagementRate / maxEngagement) * 70);
      }

      heatmap.push({ day, hour, score: Math.round(score) });
    }
  }

  // Get top 5 performing time slots (with at least 2 posts)
  const topSlots = slots
    .filter(s => s.postCount >= 2)
    .sort((a, b) => b.avgEngagementRate - a.avgEngagementRate)
    .slice(0, 5);

  // Calculate aggregate insights
  const bestSlot = topSlots[0] || slots.sort((a, b) => b.avgEngagementRate - a.avgEngagementRate)[0];
  const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

  const avgByDay: Record<number, number> = {};
  const avgByHour: Record<number, number> = {};

  // Calculate average engagement rate by day
  for (let day = 0; day < 7; day++) {
    const daySlots = slots.filter(s => s.day === day);
    if (daySlots.length > 0) {
      const totalEngagement = daySlots.reduce((sum, s) => sum + s.totalEngagement, 0);
      const totalViews = daySlots.reduce((sum, s) => sum + s.totalViews, 0);
      avgByDay[day] = (totalEngagement / totalViews) * 100;
    }
  }

  // Calculate average engagement rate by hour
  for (let hour = 0; hour < 24; hour++) {
    const hourSlots = slots.filter(s => s.hour === hour);
    if (hourSlots.length > 0) {
      const totalEngagement = hourSlots.reduce((sum, s) => sum + s.totalEngagement, 0);
      const totalViews = hourSlots.reduce((sum, s) => sum + s.totalViews, 0);
      avgByHour[hour] = (totalEngagement / totalViews) * 100;
    }
  }

  return {
    heatmap,
    topSlots,
    insights: {
      bestDay: days[bestSlot != null ? bestSlot.day : 2]!,
      bestHour: bestSlot != null ? bestSlot.hour : 19,
      avgEngagementByDay: avgByDay,
      avgEngagementByHour: avgByHour,
      hasEnoughData: true,
      postCount: publishedPosts.length,
    },
  };
}

/**
 * Generate default heatmap based on industry best practices
 * Used when user has insufficient post data (<5 posts)
 */
function generateDefaultHeatmap(postCount: number): BestTimesResult {
  // Industry best practice defaults
  const peakHours = [8, 9, 12, 13, 17, 18, 19, 20, 21];
  const peakDays = [2, 3, 4, 5]; // Tue-Fri

  const heatmap: { day: number; hour: number; score: number }[] = [];

  for (let day = 0; day < 7; day++) {
    for (let hour = 6; hour < 24; hour++) {
      let score = 30; // Base score

      if (peakHours.includes(hour)) score += 35;
      if (peakDays.includes(day)) score += 20;
      if (hour >= 19 && hour <= 21) score += 15; // Evening prime time
      if (day === 0 || day === 6) score -= 10; // Weekend penalty

      heatmap.push({ day, hour, score: Math.min(score, 100) });
    }
  }

  const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

  return {
    heatmap,
    topSlots: [],
    insights: {
      bestDay: days[3]!, // Wednesday
      bestHour: 19,
      avgEngagementByDay: {},
      avgEngagementByHour: {},
      hasEnoughData: false,
      postCount,
    },
  };
}
