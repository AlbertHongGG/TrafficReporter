from __future__ import annotations

from enum import Enum


class EvidenceReason(str, Enum):
    ANCHOR = 'anchor'
    ANCHOR_FRAME = 'anchor-frame'
    INTERVAL_START = 'interval-start'
    INTERVAL_END = 'interval-end'
    SCHEDULED_SAMPLE = 'scheduled-sample'
    TEMPORAL_BURST = 'temporal-burst'
    MOTION_HOTSPOT = 'motion-hotspot'
    HIGH_CONFIDENCE = 'high-confidence'
    HIGHEST_CONFIDENCE = 'highest-confidence'
    HIGHEST_RESOLUTION = 'highest-resolution'
    REPRESENTATIVE = 'representative'
    TEMPORAL_SUPPORT = 'temporal-support'
    SHARPNESS_PEAK = 'sharpness-peak'

    def __str__(self) -> str:
        return self.value


class DecisionSource(str, Enum):
    SINGLE_FRAME = 'single-frame'
    TEMPORAL_FUSION = 'temporal-fusion'
    CROSS_FRAME_VOTE = 'cross-frame-vote'
    USER_SELECTED = 'user-selected'
    FUSED_IMAGE = 'fused-image'
    FUSED_CHAR = 'fused-char'
    TEMPORAL_RESTORED = 'temporal-restored'
    SUPPORT_CARRY = 'support-carry'
    LEGACY_VOTE = 'legacy-vote'

    def __str__(self) -> str:
        return self.value


class ArtifactStage(str, Enum):
    RAW = 'raw'
    ORIGINAL = 'original'
    RECTIFIED = 'rectified'
    ENHANCED = 'enhanced'
    RESTORED = 'restored'
    TEMPORAL_RESTORED = 'temporal-restored'
    FUSED = 'fused'

    def __str__(self) -> str:
        return self.value


class VehicleKind(str, Enum):
    ANY = 'any'
    VEHICLE = 'vehicle'
    MOTORCYCLE = 'motorcycle'
    CAR = 'car'
    TRUCK = 'truck'
    BUS = 'bus'

    def __str__(self) -> str:
        return self.value


class TrackingTier(str, Enum):
    FULL = 'full'
    PARTIAL = 'partial'
    DETECTION_FALLBACK = 'detection-fallback'
    ANCHOR_ONLY = 'anchor-only'
    ANCHOR_INVALID = 'anchor-invalid'

    def __str__(self) -> str:
        return self.value


class AnchorStatus(str, Enum):
    VALID = 'valid'
    MISSING_SELECTION = 'missing-selection'
    OUTSIDE_INTERVAL = 'outside-interval'
    NOT_DETECTED = 'not-detected'
    MISMATCHED = 'mismatched'
    DEGRADED = 'degraded'

    def __str__(self) -> str:
        return self.value


class JobStatus(str, Enum):
    IDLE = 'idle'
    QUEUED = 'queued'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
    DEGRADED = 'degraded'

    def __str__(self) -> str:
        return self.value
