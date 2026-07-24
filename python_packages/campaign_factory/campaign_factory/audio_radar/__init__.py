"""Provider-neutral trend discovery and embedded-audio fulfillment."""

from .acquisition import (
    AcquiredAudio,
    AudioAcquisitionError,
    AudioCache,
)
from .binding import (
    AudioBindingError,
    bind_embedding_receipt,
)
from .embedding import (
    AudioEmbeddingError,
    EmbeddingSettings,
    embed_selected_audio,
)
from .learning import build_audio_performance_fact
from .models import (
    AudioLocator,
    PlatformSoundId,
    TrendCandidate,
)
from .normalization import normalize_candidates
from .pipeline import (
    EmbeddedTrendingResult,
    NeedsEmbeddedAudioError,
    fulfill_embedded_trending,
)
from .ranking import (
    AudioMatchContext,
    RankedCandidate,
    rank_candidates,
)
from .segment import (
    SegmentSelection,
    SegmentSelectionError,
    select_segment,
)

__all__ = [
    "AcquiredAudio",
    "AudioAcquisitionError",
    "AudioBindingError",
    "AudioCache",
    "AudioEmbeddingError",
    "AudioLocator",
    "AudioMatchContext",
    "EmbeddedTrendingResult",
    "EmbeddingSettings",
    "NeedsEmbeddedAudioError",
    "PlatformSoundId",
    "RankedCandidate",
    "SegmentSelection",
    "SegmentSelectionError",
    "TrendCandidate",
    "build_audio_performance_fact",
    "bind_embedding_receipt",
    "embed_selected_audio",
    "fulfill_embedded_trending",
    "normalize_candidates",
    "rank_candidates",
    "select_segment",
]
