/**
 * Timezone Utilities
 * Auto-detect and format times in user's local timezone
 */

// Get user's timezone from browser
export const getUserTimezone = (): string => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return 'UTC';
  }
};

// Get timezone abbreviation (e.g., "GMT-3")
export const getTimezoneAbbreviation = (timezone?: string): string => {
  const tz = timezone || getUserTimezone();
  const date = new Date();

  try {
    // Get offset in minutes
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      timeZoneName: 'short',
    });
    const parts = formatter.formatToParts(date);
    const tzPart = parts.find(p => p.type === 'timeZoneName');
    return tzPart?.value || 'UTC';
  } catch {
    return 'UTC';
  }
};

// Get full timezone display (e.g., "America/Sao_Paulo (GMT-3)")
export const getTimezoneDisplay = (timezone?: string): string => {
  const tz = timezone || getUserTimezone();
  const abbr = getTimezoneAbbreviation(tz);
  return `${tz} (${abbr})`;
};

// Format date in user's timezone
export const formatInTimezone = (
  date: Date | string,
  options: Intl.DateTimeFormatOptions = {},
  timezone?: string
): string => {
  const tz = timezone || getUserTimezone();
  const d = typeof date === 'string' ? new Date(date) : date;

  try {
    return new Intl.DateTimeFormat('en-US', {
      ...options,
      timeZone: tz,
    }).format(d);
  } catch {
    return d.toLocaleString();
  }
};

// Format time only (e.g., "2:30 PM")
export const formatTime = (date: Date | string, timezone?: string): string => {
  return formatInTimezone(date, {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }, timezone);
};

// Format date only (e.g., "Dec 9, 2025")
export const formatDate = (date: Date | string, timezone?: string): string => {
  return formatInTimezone(date, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }, timezone);
};

// Format date and time (e.g., "Dec 9, 2025 at 2:30 PM")
export const formatDateTime = (date: Date | string, timezone?: string): string => {
  const d = typeof date === 'string' ? new Date(date) : date;
  const tz = timezone || getUserTimezone();

  return formatInTimezone(d, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }, tz);
};

// Format date without year (e.g., "Jan 15")
export const formatShortDate = (date: Date | string | number, timezone?: string): string => {
  const d = typeof date === 'number' ? new Date(date) : date;
  return formatInTimezone(d, {
    month: 'short',
    day: 'numeric',
  }, timezone);
};

// Format relative time (e.g., "just now", "5m ago", "3h ago", "2d ago")
// Falls back to formatDate() for dates older than 30 days
export const formatRelativeTime = (date: Date | string | number | null): string => {
  if (!date) return 'Never';
  const now = Date.now();
  const then = date instanceof Date ? date.getTime()
    : typeof date === 'number' ? date
    : new Date(date).getTime();
  if (isNaN(then)) return 'Never';
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  return formatDate(new Date(then));
};

// Format relative date with time (e.g., "Today at 2:30 PM", "Tomorrow at 9:00 AM", "Dec 15 at 3:00 PM")
export const formatScheduledDateTime = (date: Date | string, timezone?: string): string => {
  const d = typeof date === 'string' ? new Date(date) : date;
  const tz = timezone || getUserTimezone();
  const now = new Date();

  // Get dates in timezone
  const dateInTz = new Date(d.toLocaleString('en-US', { timeZone: tz }));
  const nowInTz = new Date(now.toLocaleString('en-US', { timeZone: tz }));

  const isToday = dateInTz.toDateString() === nowInTz.toDateString();

  const tomorrow = new Date(nowInTz);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const isTomorrow = dateInTz.toDateString() === tomorrow.toDateString();

  const time = formatTime(d, tz);

  if (isToday) {
    return `Today at ${time}`;
  } else if (isTomorrow) {
    return `Tomorrow at ${time}`;
  } else {
    const dateStr = formatInTimezone(d, {
      month: 'short',
      day: 'numeric',
    }, tz);
    return `${dateStr} at ${time}`;
  }
};

// Format for calendar day header (e.g., "Mon 9")
export const formatCalendarDay = (date: Date | string, timezone?: string): { dayName: string; dayNum: string } => {
  const d = typeof date === 'string' ? new Date(date) : date;
  const tz = timezone || getUserTimezone();

  const dayName = formatInTimezone(d, { weekday: 'short' }, tz);
  const dayNum = formatInTimezone(d, { day: 'numeric' }, tz);

  return { dayName, dayNum };
};

// Get hour in 24h format for a date in user's timezone
export const getHourInTimezone = (date: Date | string, timezone?: string): number => {
  const d = typeof date === 'string' ? new Date(date) : date;
  const tz = timezone || getUserTimezone();

  const hourStr = formatInTimezone(d, { hour: 'numeric', hour12: false }, tz);
  return parseInt(hourStr, 10);
};

// Check if date is in the past (in user's timezone)
export const isPastDate = (date: Date | string): boolean => {
  const d = typeof date === 'string' ? new Date(date) : date;
  return d.getTime() < Date.now();
};

// Get start of day in user's timezone
export const getStartOfDay = (date: Date, timezone?: string): Date => {
  const tz = timezone || getUserTimezone();
  const dateStr = formatInTimezone(date, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }, tz);

  // Parse back to get start of day in that timezone
  const [month, day, year] = dateStr.split('/');
  return new Date(`${year}-${month}-${day}T00:00:00`);
};

/**
 * Build a UTC Date from a calendar date + hour + minute in a specific timezone.
 * This is critical for scheduling: the user picks "3:00 PM" in their timezone,
 * and we need to store the correct UTC instant.
 *
 * Without this, using `new Date().setHours()` uses the browser's local timezone,
 * which may differ from the user's configured timezone preference.
 */
export const buildDateInTimezone = (
  calendarDate: Date,
  hour: number,
  minute: number,
  timezone?: string,
): Date => {
  const tz = timezone || getUserTimezone();

  // Extract the calendar date parts as displayed in the user's timezone
  const yearStr = formatInTimezone(calendarDate, { year: 'numeric' }, tz);
  const monthStr = formatInTimezone(calendarDate, { month: '2-digit' }, tz);
  const dayStr = formatInTimezone(calendarDate, { day: '2-digit' }, tz);

  const year = parseInt(yearStr, 10);
  const month = parseInt(monthStr, 10);
  const day = parseInt(dayStr, 10);

  // Build an ISO-ish string and use the timezone offset to get the correct UTC instant.
  // We create a date string for the target timezone and compute the offset.
  const pad = (n: number) => n.toString().padStart(2, '0');
  const localStr = `${year}-${pad(month)}-${pad(day)}T${pad(hour)}:${pad(minute)}:00`;

  // Create a formatter that gives us the UTC offset for this specific date/time in the target tz
  const tempDate = new Date(localStr + 'Z'); // Use as a reference point
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone: tz,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });

  // Binary search-ish: find the UTC timestamp where formatting in the target tz
  // gives us the desired local time. Start with a rough estimate.
  // Get the offset by comparing what the formatter says vs what we want.
  const parts = formatter.formatToParts(tempDate);
  const getValue = (type: string) => parseInt(parts.find(p => p.type === type)?.value || '0', 10);
  const formattedHour = getValue('hour') === 24 ? 0 : getValue('hour');
  const formattedMinute = getValue('minute');
  const formattedDay = getValue('day');
  const formattedMonth = getValue('month');

  // Compute rough offset in minutes between what we want and what we got
  const wantedMinutes = day * 24 * 60 + hour * 60 + minute;
  const gotMinutes = formattedDay * 24 * 60 + formattedHour * 60 + formattedMinute;
  const offsetMs = (gotMinutes - wantedMinutes) * 60 * 1000;

  // Handle month boundary: if months differ, adjust by ~30 days
  let monthAdjustMs = 0;
  if (formattedMonth !== month) {
    monthAdjustMs = formattedMonth > month ? 30 * 24 * 60 * 60 * 1000 : -30 * 24 * 60 * 60 * 1000;
  }

  const result = new Date(tempDate.getTime() - offsetMs - monthAdjustMs);

  // Verify: format the result back and check it matches
  const verify = formatter.formatToParts(result);
  const vHour = parseInt(verify.find(p => p.type === 'hour')?.value || '0', 10);
  const vMin = parseInt(verify.find(p => p.type === 'minute')?.value || '0', 10);

  if (vHour !== hour || vMin !== minute) {
    // If verification fails (DST edge case), try adjusting by ±1 hour
    for (const adj of [3600000, -3600000]) {
      const adjusted = new Date(result.getTime() + adj);
      const v2 = formatter.formatToParts(adjusted);
      const v2Hour = parseInt(v2.find(p => p.type === 'hour')?.value || '0', 10);
      const v2Min = parseInt(v2.find(p => p.type === 'minute')?.value || '0', 10);
      if (v2Hour === hour && v2Min === minute) {
        return adjusted;
      }
    }
  }

  return result;
};

/**
 * Extract hour and minute from a Date as they would display in the given timezone.
 * Used when editing a scheduled post to show the correct time in the user's timezone.
 */
export const getTimeInTimezone = (
  date: Date | string,
  timezone?: string,
): { hour: number; minute: number } => {
  const d = typeof date === 'string' ? new Date(date) : date;
  const tz = timezone || getUserTimezone();

  const hourStr = formatInTimezone(d, { hour: 'numeric', hour12: false }, tz);
  const minuteStr = formatInTimezone(d, { minute: '2-digit' }, tz);

  return {
    hour: parseInt(hourStr, 10) % 24,
    minute: parseInt(minuteStr, 10),
  };
};

/**
 * Check if two dates fall on the same calendar day in a given timezone.
 */
export const isSameDayInTimezone = (
  date1: Date,
  date2: Date,
  timezone?: string,
): boolean => {
  const tz = timezone || getUserTimezone();
  const d1 = formatInTimezone(date1, { year: 'numeric', month: '2-digit', day: '2-digit' }, tz);
  const d2 = formatInTimezone(date2, { year: 'numeric', month: '2-digit', day: '2-digit' }, tz);
  return d1 === d2;
};
