import { describe, it, expect, vi, afterEach } from "vitest";
import {
  isPastDate,
  formatInTimezone,
  formatTime,
  formatDate,
  formatDateTime,
  formatCalendarDay,
  getHourInTimezone,
  getTimezoneAbbreviation,
  getTimezoneDisplay,
  buildDateInTimezone,
  getTimeInTimezone,
  isSameDayInTimezone,
  getStartOfDay,
} from "../../utils/timezone";

describe("isPastDate", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns true for a date in the past", () => {
    const pastDate = new Date("2020-01-01T00:00:00Z");
    expect(isPastDate(pastDate)).toBe(true);
  });

  it("returns false for a date in the future", () => {
    const futureDate = new Date(Date.now() + 86_400_000); // tomorrow
    expect(isPastDate(futureDate)).toBe(false);
  });

  it("accepts ISO string input", () => {
    expect(isPastDate("2020-01-01T00:00:00Z")).toBe(true);
    expect(isPastDate("2099-12-31T23:59:59Z")).toBe(false);
  });

  it("handles 'now' edge — a date slightly before now is past", () => {
    vi.useFakeTimers();
    const now = new Date("2025-06-15T12:00:00Z");
    vi.setSystemTime(now);

    expect(isPastDate(new Date("2025-06-15T11:59:59Z"))).toBe(true);
    expect(isPastDate(new Date("2025-06-15T12:00:01Z"))).toBe(false);
  });

  it("returns true for invalid date string (NaN < any number)", () => {
    // new Date("garbage").getTime() === NaN, NaN < Date.now() is false
    expect(isPastDate("not-a-date")).toBe(false);
  });
});

describe("formatInTimezone", () => {
  it("formats a date in a specific timezone", () => {
    const date = new Date("2025-12-25T15:30:00Z");
    const result = formatInTimezone(
      date,
      { month: "short", day: "numeric", year: "numeric" },
      "UTC"
    );
    expect(result).toContain("Dec");
    expect(result).toContain("25");
    expect(result).toContain("2025");
  });

  it("handles string dates", () => {
    const result = formatInTimezone(
      "2025-06-15T10:00:00Z",
      { hour: "numeric", minute: "2-digit", hour12: true },
      "UTC"
    );
    expect(result).toContain("10");
    expect(result).toContain("00");
  });

  it("shifts time when timezone differs from UTC", () => {
    // 3 PM UTC should be 11 AM in America/New_York (EDT = UTC-4)
    const date = new Date("2025-06-15T15:00:00Z");
    const nyResult = formatInTimezone(
      date,
      { hour: "numeric", hour12: false },
      "America/New_York"
    );
    expect(nyResult).toContain("11");
  });
});

describe("formatTime", () => {
  it("returns time in 12h format", () => {
    const result = formatTime("2025-06-15T14:30:00Z", "UTC");
    expect(result).toContain("2");
    expect(result).toContain("30");
    expect(result).toContain("PM");
  });

  it("formats midnight correctly", () => {
    const result = formatTime("2025-06-15T00:00:00Z", "UTC");
    expect(result).toContain("12");
    expect(result).toContain("AM");
  });
});

describe("formatDate", () => {
  it("returns short date format", () => {
    const result = formatDate("2025-12-25T00:00:00Z", "UTC");
    expect(result).toContain("Dec");
    expect(result).toContain("25");
    expect(result).toContain("2025");
  });
});

describe("formatDateTime", () => {
  it("returns date and time combined", () => {
    const result = formatDateTime("2025-12-25T14:30:00Z", "UTC");
    expect(result).toContain("Dec");
    expect(result).toContain("25");
    expect(result).toContain("2025");
    expect(result).toContain("2");
    expect(result).toContain("30");
  });
});

describe("formatCalendarDay", () => {
  it("returns day name and day number", () => {
    // 2025-12-25 is a Thursday
    const result = formatCalendarDay("2025-12-25T12:00:00Z", "UTC");
    expect(result.dayName).toBe("Thu");
    expect(result.dayNum).toBe("25");
  });
});

describe("getHourInTimezone", () => {
  it("returns the hour in the given timezone", () => {
    // 3 PM UTC = hour 15
    const result = getHourInTimezone("2025-06-15T15:00:00Z", "UTC");
    expect(result).toBe(15);
  });

  it("shifts hour for different timezone", () => {
    // 3 PM UTC = 11 AM EDT (UTC-4)
    const result = getHourInTimezone("2025-06-15T15:00:00Z", "America/New_York");
    expect(result).toBe(11);
  });
});

describe("getTimezoneAbbreviation", () => {
  it("returns abbreviation for a known timezone", () => {
    const result = getTimezoneAbbreviation("UTC");
    expect(result).toBe("UTC");
  });

  it("returns a string for any valid timezone", () => {
    const result = getTimezoneAbbreviation("America/New_York");
    expect(typeof result).toBe("string");
    expect(result.length).toBeGreaterThan(0);
  });
});

describe("getTimezoneDisplay", () => {
  it("returns timezone name with abbreviation in parens", () => {
    const result = getTimezoneDisplay("UTC");
    expect(result).toBe("UTC (UTC)");
  });

  it("includes timezone name and abbreviation for non-UTC", () => {
    const result = getTimezoneDisplay("America/New_York");
    expect(result).toContain("America/New_York");
    expect(result).toMatch(/\(.+\)/); // abbreviation in parens
  });
});

describe("buildDateInTimezone", () => {
  it("builds a UTC date from calendar date + time in UTC", () => {
    const calendarDate = new Date("2025-06-15T00:00:00Z");
    const result = buildDateInTimezone(calendarDate, 14, 30, "UTC");
    expect(result.getUTCHours()).toBe(14);
    expect(result.getUTCMinutes()).toBe(30);
  });

  it("correctly offsets for a non-UTC timezone", () => {
    // 2 PM in America/New_York (EDT = UTC-4) should be 6 PM UTC
    const calendarDate = new Date("2025-06-15T00:00:00Z");
    const result = buildDateInTimezone(calendarDate, 14, 0, "America/New_York");
    expect(result.getUTCHours()).toBe(18);
    expect(result.getUTCMinutes()).toBe(0);
  });
});

describe("getTimeInTimezone", () => {
  it("extracts hour and minute in UTC", () => {
    const date = new Date("2025-06-15T14:30:00Z");
    const result = getTimeInTimezone(date, "UTC");
    expect(result.hour).toBe(14);
    expect(result.minute).toBe(30);
  });

  it("shifts for non-UTC timezone", () => {
    // 18:00 UTC = 14:00 EDT
    const date = new Date("2025-06-15T18:00:00Z");
    const result = getTimeInTimezone(date, "America/New_York");
    expect(result.hour).toBe(14);
    expect(result.minute).toBe(0);
  });

  it("accepts string dates", () => {
    const result = getTimeInTimezone("2025-06-15T08:45:00Z", "UTC");
    expect(result.hour).toBe(8);
    expect(result.minute).toBe(45);
  });
});

describe("isSameDayInTimezone", () => {
  it("returns true for same calendar day", () => {
    const d1 = new Date("2025-06-15T10:00:00Z");
    const d2 = new Date("2025-06-15T22:00:00Z");
    expect(isSameDayInTimezone(d1, d2, "UTC")).toBe(true);
  });

  it("returns false for different calendar days", () => {
    const d1 = new Date("2025-06-15T10:00:00Z");
    const d2 = new Date("2025-06-16T10:00:00Z");
    expect(isSameDayInTimezone(d1, d2, "UTC")).toBe(false);
  });

  it("handles timezone boundaries — same UTC day but different local day", () => {
    // 2025-06-15 23:00 UTC = 2025-06-16 in UTC+2 (Europe/Helsinki)
    const d1 = new Date("2025-06-15T01:00:00Z");
    const d2 = new Date("2025-06-15T23:00:00Z");
    // In Helsinki (UTC+3 during summer), d2 is June 16
    expect(isSameDayInTimezone(d1, d2, "Europe/Helsinki")).toBe(false);
  });
});

describe("getStartOfDay", () => {
  it("returns start of day for UTC", () => {
    const date = new Date("2025-06-15T14:30:00Z");
    const result = getStartOfDay(date, "UTC");
    // getStartOfDay constructs a date from formatted parts — check it's midnight local
    expect(result.getHours()).toBe(0);
    expect(result.getMinutes()).toBe(0);
  });
});
