"""Tests for Wav2LipEngine (mocked model — no GPU required)."""

from __future__ import annotations

import sys
import types
import numpy as np
import pytest
from unittest.mock import MagicMock, patch


def _make_torch_mock():
    """Build a minimal torch mock that returns sensible tensor-like objects."""
    import numpy as np

    torch_mock = MagicMock(name="torch")

    # Provide a real-ish Tensor-like via numpy wrapping
    class FakeTensor:
        def __init__(self, array):
            self._arr = np.array(array, dtype=np.float32)

        def squeeze(self, dim):
            return FakeTensor(self._arr.squeeze(dim))

        def cpu(self):
            return self

        def numpy(self):
            return self._arr

        def unsqueeze(self, dim):
            return FakeTensor(np.expand_dims(self._arr, dim))

        def to(self, device):
            return self

        def __mul__(self, other):
            return FakeTensor(self._arr * other)

    def from_numpy(arr):
        return FakeTensor(arr)

    torch_mock.from_numpy.side_effect = from_numpy
    torch_mock.device.side_effect = lambda s: s
    torch_mock.no_grad.return_value.__enter__ = MagicMock(return_value=None)
    torch_mock.no_grad.return_value.__exit__ = MagicMock(return_value=False)
    torch_mock.zeros.side_effect = lambda *shape, **kw: FakeTensor(np.zeros(shape, dtype=np.float32))

    # Model output: (1, 3, 96, 96) all 0.5
    fake_output = FakeTensor(np.full((1, 3, 96, 96), 0.5, dtype=np.float32))
    mock_model_instance = MagicMock()
    mock_model_instance.return_value = fake_output
    torch_mock._fake_output = fake_output
    torch_mock._mock_model = mock_model_instance

    return torch_mock


def _make_engine_with_mock(torch_mock):
    """Build a Wav2LipEngine with all torch/model internals mocked."""
    from scrumsurvivor.lipsync.wav2lip_engine import Wav2LipEngine

    engine = Wav2LipEngine.__new__(Wav2LipEngine)
    engine._model = torch_mock._mock_model
    engine._device = "cpu"
    engine._device_str = "cpu"
    engine._ready = True
    return engine


def test_process_output_shape():
    """process() should return a (96, 96, 3) BGR uint8 array."""
    torch_mock = _make_torch_mock()
    with patch.dict(sys.modules, {"torch": torch_mock}):
        engine = _make_engine_with_mock(torch_mock)
        face = np.zeros((96, 96, 3), dtype=np.uint8)
        mel = np.zeros((80, 16), dtype=np.float32)
        result = engine.process(face, mel)

    assert result.shape == (96, 96, 3)
    assert result.dtype == np.uint8


def test_process_output_values_in_range():
    """All pixel values should be 0-255."""
    torch_mock = _make_torch_mock()
    with patch.dict(sys.modules, {"torch": torch_mock}):
        engine = _make_engine_with_mock(torch_mock)
        face = np.zeros((96, 96, 3), dtype=np.uint8)
        mel = np.zeros((1, 80, 16), dtype=np.float32)
        result = engine.process(face, mel)

    assert result.min() >= 0
    assert result.max() <= 255


def test_load_raises_when_model_missing(tmp_path):
    """Should raise FileNotFoundError if the .pth file does not exist."""
    torch_mock = _make_torch_mock()
    with patch.dict(sys.modules, {"torch": torch_mock}):
        from scrumsurvivor.lipsync.wav2lip_engine import Wav2LipEngine
        with pytest.raises(FileNotFoundError):
            Wav2LipEngine(model_path=str(tmp_path / "nonexistent.pth"), device="cpu")


@pytest.mark.gpu
def test_engine_loads_and_processes_real_model():
    """Integration: requires actual model file and GPU."""
    from scrumsurvivor.lipsync.wav2lip_engine import Wav2LipEngine

    engine = Wav2LipEngine(model_path="models/wav2lip.pth", device="cuda")
    assert engine.is_ready

    face = np.random.randint(0, 255, (96, 96, 3), dtype=np.uint8)
    mel = np.random.randn(80, 16).astype(np.float32)
    result = engine.process(face, mel)
    assert result.shape == (96, 96, 3)
