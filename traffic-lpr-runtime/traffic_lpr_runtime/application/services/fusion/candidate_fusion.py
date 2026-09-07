from __future__ import annotations

from pathlib import Path
from typing import Any

from traffic_lpr_runtime.application.services.fusion.candidate_scoring import (
    _best_frame_candidate,
    _candidate_reliability_score,
    _candidate_support_frame_count,
    _candidate_support_frames_payload,
    _candidate_weight,
    _consensus_signal_names,
    _consensus_weight_multiplier,
    _source_family,
)
from traffic_lpr_runtime.application.services.fusion.fusion_strategies import (
    MAX_INTERVAL_FUSION_OBSERVATIONS,
    CandidateFusionService,
)
from traffic_lpr_runtime.application.services.fusion.plate_format import (
    _looks_like_taiwan_long_plate,
    _looks_like_taiwan_short_plate,
    _plate_format_score,
    _uses_taiwan_hint,
)
from traffic_lpr_runtime.application.services.fusion.reliability_selection import (
    _best_interval_review_candidate,
    _best_sample_candidate,
    _review_reasons,
    apply_reliability_selection,
)
from traffic_lpr_runtime.application.services.fusion.sequence_analysis import (
    _ordered_top_sample_candidates,
    _sequence_confidence_cap,
    _sequence_tier,
    _support_gap_count,
)
from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.application.services.preprocessing import PlateObservation
from traffic_lpr_runtime.domain.interfaces import PlateRecognizer
from traffic_lpr_runtime.domain.models import FrameSample, PlateCandidate
from traffic_lpr_runtime.domain.text import normalize_plate_text
from traffic_lpr_runtime.infrastructure.dependencies import DependencyRegistry
