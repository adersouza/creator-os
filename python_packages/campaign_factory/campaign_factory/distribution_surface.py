def normalize_distribution_surface(value: str | None) -> str:
    normalized = (value or "regular_reel").strip().lower().replace("-", "_")
    aliases = {
        "reel": "regular_reel",
        "regular": "regular_reel",
        "ig_reel": "regular_reel",
        "trial": "trial_reel",
        "trial_reels": "trial_reel",
        "stories": "story",
        "ig_story": "story",
        "cta_story": "story_cta",
        "single_image": "feed_single",
        "feed_image": "feed_single",
        "feed_single_image": "feed_single",
        "carousel": "feed_carousel",
        "carousel_album": "feed_carousel",
    }
    normalized = aliases.get(normalized, normalized)
    allowed = {
        "regular_reel",
        "trial_reel",
        "story",
        "story_cta",
        "feed_single",
        "feed_carousel",
    }
    return normalized if normalized in allowed else "regular_reel"
