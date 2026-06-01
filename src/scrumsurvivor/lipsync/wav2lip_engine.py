"""Wav2Lip inference engine — wraps the vendored model with pre/post-processing."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_FACE_SIZE = (96, 96)  # Wav2Lip input/output face resolution


class Wav2LipEngine:
    """Loads the Wav2Lip model and performs per-frame lipsync inference.

    Args:
        model_path: Path to the ``.pth`` weights file.
        device: PyTorch device string (``"cuda"`` or ``"cpu"``).
    """

    def __init__(
        self,
        model_path: str,
        device: str = "cuda",
    ) -> None:
        self._model_path = model_path
        self._device_str = device
        self._model = None
        self._device = None
        self._ready = False
        self._load()

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load(self) -> None:
        # Check file existence before importing heavy torch/model deps
        if not Path(self._model_path).exists():
            raise FileNotFoundError(
                f"Wav2Lip model weights not found at {self._model_path!r}. "
                "Download from https://github.com/Rudrabha/Wav2Lip#getting-the-weights "
                "and place in models/wav2lip.pth"
            )

        import torch

        self._device = torch.device(self._device_str)

        # weights_only=False is required: the official Wav2Lip .pth is a
        # TorchScript or legacy pickle checkpoint from a trusted source.
        checkpoint = torch.load(
            self._model_path, map_location=self._device, weights_only=False
        )

        # The official Wav2Lip releases ship as TorchScript archives.
        # torch.load auto-dispatches to torch.jit.load for these, returning a
        # RecursiveScriptModule which is ready to use directly.
        if isinstance(checkpoint, torch.jit.ScriptModule):
            logger.info("Detected TorchScript checkpoint — using jit model directly.")
            model = checkpoint.to(self._device)
            model.eval()
        else:
            # Legacy pickle checkpoint: extract state_dict and load into our
            # Wav2Lip architecture definition.
            from scrumsurvivor.lipsync.wav2lip_vendor.models import Wav2Lip
            model = Wav2Lip()
            state_dict = checkpoint.get("state_dict", checkpoint)
            # Remove 'module.' prefix if saved with DataParallel
            state_dict = {k.replace("module.", "", 1): v for k, v in state_dict.items()}
            model.load_state_dict(state_dict)
            model = model.to(self._device)
            model.eval()

        self._model = model
        logger.info("Wav2Lip model loaded on %s.", self._device)
        self.warm_up()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return self._ready

    def warm_up(self) -> None:
        """Run a dummy inference to initialise CUDA kernels."""
        import torch

        logger.debug("Wav2Lip warm-up inference running…")
        audio_dummy = torch.zeros(1, 1, 80, 16, device=self._device)
        face_dummy = torch.zeros(1, 6, 96, 96, device=self._device)
        with torch.no_grad():
            self._model(audio_dummy, face_dummy)
        if self._device_str == "cuda":
            torch.cuda.synchronize(self._device)
        self._ready = True
        logger.info("Wav2Lip warm-up complete.")

    def process(
        self, face_image: np.ndarray, mel_window: np.ndarray
    ) -> np.ndarray:
        """Produce a lip-synced face frame.

        Args:
            face_image: BGR uint8, any size (will be resized to 96×96).
            mel_window: Float32 array of shape ``(1, 80, 16)`` or ``(80, 16)``.

        Returns:
            BGR uint8 face image of shape ``(96, 96, 3)``.
        """
        import torch

        # ── Prepare face tensor ──────────────────────────────────────────────
        face_96 = cv2.resize(face_image, _FACE_SIZE)
        # Wav2Lip was trained on BGR (OpenCV default) — do NOT convert to RGB.

        # Masked face: zero out lower half (lips region)
        masked = face_96.copy()
        masked[_FACE_SIZE[1] // 2 :, :] = 0

        # Stack masked + original → (6, 96, 96) normalized to [0, 1]
        face_arr = np.concatenate(
            [masked.transpose(2, 0, 1), face_96.transpose(2, 0, 1)], axis=0
        ).astype(np.float32) / 255.0
        face_t = torch.from_numpy(face_arr).unsqueeze(0).to(self._device)  # (1,6,96,96)

        # ── Prepare mel tensor ───────────────────────────────────────────────
        if mel_window.ndim == 2:
            mel_window = mel_window[np.newaxis]  # → (1, 80, 16)
        mel_t = (
            torch.from_numpy(mel_window).unsqueeze(0).to(self._device)
        )  # (1, 1, 80, 16)

        # ── Inference ────────────────────────────────────────────────────────
        with torch.no_grad():
            pred = self._model(mel_t, face_t)  # (1, 3, 96, 96)

        # ── Post-process ─────────────────────────────────────────────────────
        pred_np = (pred.squeeze(0).cpu().numpy().clip(0, 1) * 255).astype(np.uint8)
        # Model was trained on BGR — output is also BGR, no conversion needed.
        pred_bgr = pred_np.transpose(1, 2, 0).copy()
        return pred_bgr
