/**
 * AI Feedback data utilities
 * Pure data functions for saving/loading AI feedback — no JSX.
 */

export interface AIFeedbackEntry {
  type: "post" | "reply" | "improvement" | "idea" | "dm" | "variation";
  content: string;
  rating: "positive" | "negative";
  timestamp: string;
}

const MAX_FEEDBACK_ENTRIES = 50;

export async function saveFeedback(entry: AIFeedbackEntry): Promise<void> {
  try {
    const { supabase } = await import("@/services/supabase");
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;

    // Load existing feedback
    const { data } = await supabase
      .from("user_settings")
      .select("setting_value")
      .eq("user_id", user.id)
      .eq("setting_key", "ai_feedback")
      .maybeSingle();

    // biome-ignore lint/suspicious/noExplicitAny: Supabase returns untyped JSONB
    const existing: { entries: AIFeedbackEntry[] } = (data as any)?.setting_value || { entries: [] };
    existing.entries.unshift(entry);
    // Keep only last N entries
    if (existing.entries.length > MAX_FEEDBACK_ENTRIES) {
      existing.entries = existing.entries.slice(0, MAX_FEEDBACK_ENTRIES);
    }

    await supabase
      .from("user_settings")
      .upsert(
        {
          user_id: user.id,
          setting_key: "ai_feedback",
          // biome-ignore lint/suspicious/noExplicitAny: Supabase JSONB column requires any cast
          setting_value: existing as any,
        },
        { onConflict: "user_id,setting_key" },
      );
  } catch {
    /* non-critical: feedback save is best-effort */
  }
}

export async function loadFeedbackContext(): Promise<string> {
  try {
    const { supabase } = await import("@/services/supabase");
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return "";

    const { data } = await supabase
      .from("user_settings")
      .select("setting_value")
      .eq("user_id", user.id)
      .eq("setting_key", "ai_feedback")
      .maybeSingle();

    // biome-ignore lint/suspicious/noExplicitAny: Supabase returns untyped JSONB
    const sv = (data as any)?.setting_value;
    if (!sv?.entries?.length) return "";

    const entries = sv.entries as AIFeedbackEntry[];
    const positive = entries.filter((e) => e.rating === "positive").length;
    const negative = entries.filter((e) => e.rating === "negative").length;

    if (positive + negative === 0) return "";

    // Build a concise summary for the AI prompt
    const likedExamples = entries
      .filter((e) => e.rating === "positive")
      .slice(0, 3)
      .map((e) => `"${e.content.substring(0, 80)}"`)
      .join(", ");

    const dislikedExamples = entries
      .filter((e) => e.rating === "negative")
      .slice(0, 2)
      .map((e) => `"${e.content.substring(0, 80)}"`)
      .join(", ");

    let context = `\nUSER PREFERENCES (based on ${positive + negative} ratings, ${positive} liked, ${negative} disliked):`;
    if (likedExamples) context += `\nUser liked content like: ${likedExamples}`;
    if (dislikedExamples) context += `\nUser disliked content like: ${dislikedExamples}`;
    context += "\nPlease adapt your style to match what the user prefers.";

    return context;
  } catch {
    return "";
  }
}
