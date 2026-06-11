export type Theme = "ink" | "cream" | "oxblood" | "vale";

export type LinkBlockType =
  | "link"
  | "animated"
  | "scheduled_window"
  | "email_capture"
  | "tip_jar"
  | "digital_product"
  | "affiliate_catalog"
  | "bento_media_grid"
  | "code_gate"
  | "course"
  | "membership"
  | "booking"
  | "storefront"
  | "tour"
  | "presave";

export interface LinkItem {
  id: string;
  title: string;
  url: string;
  clicks: number;
  blockType?: LinkBlockType | string | undefined;
  subtitle?: string | undefined;
  metadata?: Record<string, unknown> | undefined;
}

export interface SmartLink {
  id: string;
  slug: string;
  title: string;
  targetUrl: string;
  isActive: boolean;
  totalClicks: number;
  last30: number[];
  lastEdited: string;
  theme: Theme;
  items: LinkItem[];
  utm: { source: string; medium: string; campaign: string };
  metadata?: Record<string, unknown> | undefined;
}

export type DetailTab = "editor" | "analytics" | "utm";

export const THEME_META: Record<Theme, { label: string; swatch: string }> = {
  ink: { label: "Ink", swatch: "#1A1A1C" },
  cream: { label: "Chalk", swatch: "#F4F4F2" },
  oxblood: { label: "Ray", swatch: "#E5484D" },
  vale: { label: "Graphite", swatch: "#6F7078" },
};

export const NEW_LINK_PLACEHOLDER_URL = "https://example.invalid";

export const LINK_BLOCK_LIBRARY: Array<{
  type: LinkBlockType;
  label: string;
  description: string;
  defaultTitle: string;
  icon: string;
}> = [
  {
    type: "link",
    label: "Link",
    description: "Standard outbound link with CTR tracking.",
    defaultTitle: "New link",
    icon: "↗",
  },
  {
    type: "animated",
    label: "Animated link",
    description: "Hero link with attention treatment.",
    defaultTitle: "Featured link",
    icon: "▶",
  },
  {
    type: "scheduled_window",
    label: "Scheduled window",
    description: "Visible only between start and end dates.",
    defaultTitle: "Limited drop",
    icon: "⏱",
  },
  {
    type: "email_capture",
    label: "Email capture",
    description: "Newsletter capture block.",
    defaultTitle: "Get the newsletter",
    icon: "✉",
  },
  {
    type: "tip_jar",
    label: "Tip jar",
    description: "Support presets and payment handoff.",
    defaultTitle: "Tip jar",
    icon: "$",
  },
  {
    type: "digital_product",
    label: "Digital product",
    description: "File, audio, video, or download checkout.",
    defaultTitle: "Digital product",
    icon: "⬇",
  },
  {
    type: "course",
    label: "Course",
    description: "Course or lesson collection.",
    defaultTitle: "Course",
    icon: "⊞",
  },
  {
    type: "membership",
    label: "Membership",
    description: "Recurring access or gated content.",
    defaultTitle: "Membership",
    icon: "★",
  },
  {
    type: "booking",
    label: "Booking",
    description: "Calendar or consult booking.",
    defaultTitle: "Book a session",
    icon: "□",
  },
  {
    type: "storefront",
    label: "Storefront",
    description: "Multi-product storefront or cart.",
    defaultTitle: "Shop the store",
    icon: "⊟",
  },
  {
    type: "affiliate_catalog",
    label: "Affiliate",
    description: "Brand catalog or affiliate offer.",
    defaultTitle: "Recommended stack",
    icon: "∞",
  },
  {
    type: "tour",
    label: "Tour dates",
    description: "Date list, tickets, and presale codes.",
    defaultTitle: "Tour dates",
    icon: "T",
  },
  {
    type: "presave",
    label: "Pre-save",
    description: "Music pre-save destination.",
    defaultTitle: "Pre-save the release",
    icon: "P",
  },
  {
    type: "code_gate",
    label: "Code-gated link",
    description: "Hidden until a visitor enters a code.",
    defaultTitle: "Enter code for early access",
    icon: "⊘",
  },
  {
    type: "bento_media_grid",
    label: "Media grid",
    description: "Bento-style image or video grid.",
    defaultTitle: "Latest media",
    icon: "▦",
  },
];
