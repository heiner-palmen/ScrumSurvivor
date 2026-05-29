"""Idle compositor — stacks all idle effects into a single processor."""

from __future__ import annotations

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _resize_to_smaller(
    frame: np.ndarray,
    reference: np.ndarray,
) -> np.ndarray:
    """Return *frame* resized to *reference* shape if it is larger, else unchanged."""
    if frame.shape == reference.shape:
        return frame
    # Pick the smaller resolution and resize the larger frame down to it.
    target_h, target_w = reference.shape[:2]
    frame_h, frame_w = frame.shape[:2]
    if frame_h * frame_w > target_h * target_w:
        return cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
    return cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)


class IdleCompositor:
    """Chains breathing, head-sway, blink, and noise effects over the idle frame.

    If idle video clips are available they supply the base frame; otherwise
    a static base image is used.

    Args:
        base_image: Static BGR fallback frame when no clips are loaded.
        clip_manager: Optional :class:`IdleClipManager` for animated base frames.
        breathing: Optional :class:`BreathingEffect`.
        head_sway: Optional :class:`HeadSwayEffect`.
        blink: Optional :class:`BlinkEffect`.
        noise: Optional :class:`NoiseEffect`.
    """

    def __init__(
        self,
        base_image: np.ndarray,
        clip_manager=None,
        breathing=None,
        head_sway=None,
        blink=None,
        noise=None,
        transition_frames: int = 0,
    ) -> None:
        self._base = base_image
        self._clip_manager = clip_manager
        self._breathing = breathing
        self._head_sway = head_sway
        self._blink = blink
        self._noise = noise
        self._transition_frames = max(0, int(transition_frames))
        self._transition_from: np.ndarray | None = None
        self._transition_step = 0
        self._last_output: np.ndarray | None = None
        self._last_source_key = "base"

    @staticmethod
    def _smoothstep_alpha(step: int, total_steps: int) -> float:
        if total_steps <= 0:
            return 1.0
        alpha = min(max((step + 1) / total_steps, 0.0), 1.0)
        return alpha * alpha * (3.0 - 2.0 * alpha)

    def _start_transition(self, from_frame: np.ndarray) -> None:
        if self._transition_frames <= 0:
            self._transition_from = None
            self._transition_step = 0
            return
        self._transition_from = from_frame.astype(np.float32)
        self._transition_step = 0

    def _apply_transition(self, target_frame: np.ndarray) -> np.ndarray:
        if self._transition_from is None:
            return target_frame

        # Ensure both frames share the same resolution before blending.
        if self._transition_from.shape != target_frame.shape:
            target_frame = _resize_to_smaller(target_frame, self._transition_from)
            self._transition_from = _resize_to_smaller(
                self._transition_from, target_frame
            )

        alpha = self._smoothstep_alpha(self._transition_step, self._transition_frames)
        target_f32 = target_frame.astype(np.float32)
        blended = self._transition_from * (1.0 - alpha) + target_f32 * alpha
        self._transition_step += 1
        if self._transition_step >= self._transition_frames:
            self._transition_from = None
        return blended.astype(np.uint8)

    @property
    def is_clip_playing(self) -> bool:
        """True when an idle clip is actively playing (not in pause between clips)."""
        if self._clip_manager is None:
            return False
        return self._clip_manager.is_clip_playing

    @property
    def has_speaking_compatible_clips(self) -> bool:
        if self._clip_manager is None:
            return False
        return bool(getattr(self._clip_manager, "has_speaking_compatible_clips", False))

    @property
    def current_clip_allows_speaking_overlay(self) -> bool:
        if self._clip_manager is None:
            return False
        return bool(getattr(self._clip_manager, "current_clip_allows_speaking_overlay", False))

    def speaking_base_frame(self, fallback_frame: np.ndarray) -> np.ndarray:
        """Return the blink frame that may continue during speech, if any."""
        if self._clip_manager is None:
            return fallback_frame
        reader = getattr(self._clip_manager, "read_speaking_compatible_frame", None)
        if not callable(reader):
            return fallback_frame
        frame = reader()
        if frame is None:
            return fallback_frame
        return frame

    def suppress_idle_clips_for(self, seconds: float) -> None:
        """Prevent new idle clips from starting for *seconds* seconds."""
        if self._clip_manager is None:
            return
        suppress = getattr(self._clip_manager, "suppress_for", None)
        if callable(suppress):
            suppress(seconds)

    def set_clip_starts_blocked(self, blocked: bool) -> None:
        """Prevent the clip manager from starting new clips while speech is pending."""
        if self._clip_manager is None:
            return
        setter = getattr(self._clip_manager, "set_clip_starts_blocked", None)
        if callable(setter):
            setter(blocked)

    def _has_recorded_role_clips(self, attribute_name: str) -> bool:
        if self._clip_manager is None:
            return False
        return bool(getattr(self._clip_manager, attribute_name, False))

    def process(self, _raw_frame: np.ndarray) -> np.ndarray:
        """Return the next idle composite frame.

        *_raw_frame* is ignored (idle mode uses pre-rendered assets), but the
        signature matches the pipeline processor protocol.
        """
        # 1. Choose base frame
        source_key = "base"
        if self._clip_manager is not None and self._clip_manager.has_clips:
            frame = self._clip_manager.read_frame()
            if frame is None:
                frame = self._base.copy()
            else:
                source_key = "clip"
        else:
            frame = self._base.copy()

        # 2. Apply effects in order
        if self._breathing is not None and not self._has_recorded_role_clips("has_recorded_breathing_clips"):
            frame = self._breathing.apply(frame)
        if self._head_sway is not None:
            frame = self._head_sway.apply(frame)
        if self._blink is not None and not self._has_recorded_role_clips("has_recorded_blink_clips"):
            frame = self._blink.apply(frame)
        if self._noise is not None:
            frame = self._noise.apply(frame)

        if (
            self._last_output is not None
            and source_key != self._last_source_key
        ):
            self._start_transition(self._last_output)

            # Resize *frame* to match the previous output so the transition
            # can always blend regardless of resolution differences.
            frame = _resize_to_smaller(frame, self._last_output)

        frame = self._apply_transition(frame)
        self._last_source_key = source_key
        self._last_output = frame.copy()

        return frame
