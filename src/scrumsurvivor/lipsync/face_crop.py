"""Face crop manager for Wav2Lip lipsync — static detection at startup."""

from __future__ import annotations

import logging

import cv2
import numpy as np

from scrumsurvivor.detection.face_detector import FaceRect, detect_face_once

logger = logging.getLogger(__name__)

# Target size for Wav2Lip model input face crop
_WAV2LIP_FACE_SIZE = (96, 96)

# Ratio-based mouth position inside the face crop (used when mouth_crop_rect is not configured)
_MOUTH_CENTER_X_RATIO = 0.50
_MOUTH_CENTER_Y_RATIO = 0.66
_MOUTH_WIDTH_RATIO = 0.24
_MOUTH_HEIGHT_RATIO = 0.12


class FaceCropManager:
    """Manages the face crop region used for Wav2Lip inference.

    Face detection runs via Haar cascade on startup to obtain a tight
    bounding box around the face.  If ``preset_rect`` and/or ``mouth_rect``
    are provided (from config.yaml) they override auto-detection entirely.

    Args:
        base_photo: BGR image of the avatar base photo.
        preset_rect: Optional ``[x, y, w, h]`` from config -- skips auto-detection.
        mouth_rect: Optional ``[x, y, w, h]`` absolute pixel rect -- overrides
                    ratio-based mouth placement.
    """

    def __init__(
        self,
        base_photo: np.ndarray,
        preset_rect: list[int] | tuple[int, int, int, int] | None = None,
        mouth_rect: list[int] | tuple[int, int, int, int] | None = None,
    ) -> None:
        self._base_photo = base_photo

        if preset_rect is not None:
            self._rect: FaceRect | None = (
                int(preset_rect[0]),
                int(preset_rect[1]),
                int(preset_rect[2]),
                int(preset_rect[3]),
            )
            logger.info("Using preset face_crop_rect from config: %s", self._rect)
        else:
            self._rect = None  # resolved lazily by detect()

        if mouth_rect is not None:
            self._mouth_rect: FaceRect | None = (
                int(mouth_rect[0]),
                int(mouth_rect[1]),
                int(mouth_rect[2]),
                int(mouth_rect[3]),
            )
            logger.info("Using preset mouth_crop_rect from config: %s", self._mouth_rect)
        else:
            self._mouth_rect = None

    def detect(self) -> FaceRect | None:
        """Run face detection on the base photo and store the result."""
        if self._rect is not None:
            return self._rect
        rect = detect_face_once(self._base_photo)
        if rect is not None:
            # Sanity-check: reject rects that are unreasonably large
            # (> 60 % of image width or height). That means the cascade
            # picked up a false positive or the image is weird.
            img_h, img_w = self._base_photo.shape[:2]
            _, _, rw, rh = rect
            if rw > img_w * 0.6 or rh > img_h * 0.6:
                logger.warning(
                    "Auto-detected face rect %s looks too large "
                    "(image is %dx%d). Rejecting.",
                    rect, img_w, img_h,
                )
                return None
        self._rect = rect
        return rect

    def get_crop(self, source_frame: np.ndarray | None = None) -> np.ndarray | None:
        """Return the face crop region resized to Wav2Lip input size (96x96).

        Returns *None* if no face has been detected.
        """
        if self._rect is None:
            self.detect()
        if self._rect is None:
            return None
        x, y, w, h = self._rect
        frame = self._base_photo if source_frame is None else source_frame
        crop = frame[y : y + h, x : x + w]
        return cv2.resize(crop, _WAV2LIP_FACE_SIZE)

    def paste_back(
        self, full_frame: np.ndarray, lip_synced_face: np.ndarray
    ) -> np.ndarray:
        """Paste only the mouth region of the lip-synced face back.

        The Wav2Lip 96x96 output is resized to match the face rect, then only
        a soft elliptical region around the mouth is blended into the original
        frame so the rest of the face stays sharp.

        The mouth ellipse is either:
        - Positioned from ``mouth_crop_rect`` (config) when available, or
        - Computed from fixed ratios within the face rect otherwise.

        Args:
            full_frame: BGR image to paste into.
            lip_synced_face: Wav2Lip output face (96x96 BGR).

        Returns:
            New frame with the lip-synced mouth region blended in.
        """
        if self._rect is None:
            return full_frame

        x, y, w, h = self._rect
        result = full_frame.copy()

        # Resize lip-synced output back to original crop size
        face_resized = cv2.resize(lip_synced_face, (w, h), interpolation=cv2.INTER_LANCZOS4)

        # Build an ellipse mask in face-rect-local coordinates
        mask = np.zeros((h, w), dtype=np.float32)

        if self._mouth_rect is not None:
            mx, my, mw, mh = self._mouth_rect
            # Convert absolute mouth centre to face-rect-local coordinates
            mouth_center = (mx - x + mw // 2, my - y + mh // 2)
            mouth_axes = (max(6, mw // 2), max(4, mh // 2))
        else:
            mouth_center = (
                int(round(w * _MOUTH_CENTER_X_RATIO)),
                int(round(h * _MOUTH_CENTER_Y_RATIO)),
            )
            mouth_axes = (
                max(6, int(round(w * _MOUTH_WIDTH_RATIO))),
                max(4, int(round(h * _MOUTH_HEIGHT_RATIO))),
            )

        cv2.ellipse(mask, mouth_center, mouth_axes, 0, 0, 360, 1.0, -1)

        feather = max(5, min(w, h) // 10)
        ksize = feather if feather % 2 == 1 else feather + 1
        mask = cv2.GaussianBlur(mask, (ksize, ksize), 0)

        region = result[y : y + h, x : x + w].astype(np.float32)
        face_f = face_resized.astype(np.float32)
        mask_3 = mask[:, :, np.newaxis]
        blended = region * (1.0 - mask_3) + face_f * mask_3
        result[y : y + h, x : x + w] = blended.astype(np.uint8)
        return result

    @property
    def rect(self) -> FaceRect | None:
        return self._rect
