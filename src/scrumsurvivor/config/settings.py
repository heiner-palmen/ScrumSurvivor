from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

import logging

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config.yaml"


@dataclass
class AppConfig:
    # Asset paths
    base_photo_path: str = "assets/base_photo.png"
    idle_clips_dir: str = "assets/idle_clips/"
    wav2lip_model_path: str = "models/Wav2Lip-SD-NOGAN.pt"

    # Microphone (None = system default; use integer index or partial name string)
    microphone_device: int | str | None = None

    # Speech detection
    speech_threshold: float | None = None  # None = auto-calibrate at startup
    speech_attack_ms: int = 80
    speech_release_ms: int = 300

    # Transitions
    crossfade_frames: int = 15

    # Audio
    audio_delay_ms: int | None = None  # None = auto-calibrate from Wav2Lip latency
    sample_rate: int = 48000
    virtual_audio_device: str = "CABLE Input"

    # Output
    target_fps: int = 25
    output_resolution: list[int] = field(default_factory=lambda: [1280, 720])

    # Preview
    preview_enabled: bool = False

    # Logging
    log_file: str = "logs/scrumsurvivor.log"
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR

    # Idle animation
    blink_interval_range: list[float] = field(default_factory=lambda: [4.0, 8.0])
    breathing_clip_interval_range: list[float] = field(default_factory=lambda: [10.0, 15.0])
    idle_clip_pause_min_s: float = 5.0   # min static base-image dwell between idle clips
    idle_clip_pause_max_s: float = 10.0  # max static base-image dwell between idle clips
    idle_after_speaking_cooldown_s: float = 5.0  # minimum static base-image hold after speech

    # Audio output
    output_gain: float = 0.6  # Scale output audio (0.0–1.0) to reduce noise for lip-sync
    presentation_release_ms: int = 1500  # ms of silence before SPEAKING→IDLE (bridges word gaps)

    # Themes — named asset sets under assets/themes/<name>/
    active_theme: str | None = None  # None = use base_photo_path/idle_clips_dir directly

    # Lipsync
    face_crop_rect: list[int] | None = None   # [x, y, w, h] — overrides Haar face auto-detection
    mouth_crop_rect: list[int] | None = None  # [x, y, w, h] absolute px — overrides ratio-based mouth placement

    # Panic button — instantly switches to real webcam + zero-delay audio
    panic_hotkey: str = "ctrl+shift+p"
    panic_webcam_device: int | str | None = None  # None = panic button disabled
    panic_webcam_backend: int | None = None  # cv2 backend constant (e.g. cv2.CAP_MSMF=1400); None = CAP_DSHOW
    panic_webcam_mirror: bool = False  # Horizontally flip the panic webcam feed


def resolve_asset_paths(config: "AppConfig") -> tuple[str, str]:
    """Return (base_photo_path, idle_clips_dir) respecting active_theme.

    If ``active_theme`` is set the paths are derived as:
        assets/themes/<theme>/base_photo.png
        assets/themes/<theme>/idle_clips/
    Otherwise the explicit paths stored in the config are returned unchanged.
    """
    if config.active_theme:
        from pathlib import Path
        base = Path("assets") / "themes" / config.active_theme
        return str(base / "base_photo.png"), str(base / "idle_clips")
    return config.base_photo_path, config.idle_clips_dir


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load config from YAML file, falling back to defaults for missing keys.

    If the file does not exist, generate a default config and return defaults.
    """
    from dataclasses import fields

    path = Path(config_path)
    if not path.exists():
        logger.info(
            "Config file not found at %s — generating default config.", config_path
        )
        generate_default_config(config_path)
        return AppConfig()

    with path.open("r", encoding="utf-8") as f:
        data: dict = yaml.safe_load(f) or {}

    # Only apply known fields; silently ignore unrecognised keys
    known_fields = {f.name for f in fields(AppConfig)}
    filtered = {k: v for k, v in data.items() if k in known_fields}

    config = AppConfig(**filtered)
    _validate(config)
    return config


# Fields that are resolved at runtime and must not be persisted to config.yaml.
_TRANSIENT_FIELDS = {"active_theme"}


def save_config(config: AppConfig, config_path: str = DEFAULT_CONFIG_PATH) -> None:
    """Serialise *config* to YAML at *config_path*."""
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in asdict(config).items() if k not in _TRANSIENT_FIELDS}
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def generate_default_config(config_path: str = DEFAULT_CONFIG_PATH) -> None:
    """Write a human-readable, commented default config.yaml."""
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    content = """\
# ScrumSurvivor Configuration
# Edit values below. Restart the app to apply changes (no hot-reload).

# ── Asset Paths ──────────────────────────────────────────────────────────────
base_photo_path: assets/base_photo.png
idle_clips_dir: assets/idle_clips/
wav2lip_model_path: models/wav2lip.pth

# ── Microphone ───────────────────────────────────────────────────────────────
microphone_device: null     # null = system default; setup writes the selected input device index

# ── Speech Detection ─────────────────────────────────────────────────────────
speech_threshold: null      # null = auto-calibrate from ambient noise at startup
speech_attack_ms: 80        # ms of speech before switching to SPEAKING state
speech_release_ms: 300      # ms of silence before switching to IDLE state

# ── Frame Transitions ────────────────────────────────────────────────────────
crossfade_frames: 15        # Frames to blend for state switches and idle asset boundaries (~600ms @ 25fps)

# ── Audio ────────────────────────────────────────────────────────────────────
audio_delay_ms: null        # null = auto-calibrate from Wav2Lip latency measurement
sample_rate: 48000
virtual_audio_device: "CABLE Input"   # Setup rewrites this to an exact selector, e.g. hostapi=Windows WASAPI | id=25

# ── Output ───────────────────────────────────────────────────────────────────
target_fps: 25
output_resolution: [1280, 720]

# ── Preview ──────────────────────────────────────────────────────────────────
preview_enabled: false      # Show local output preview window (or use --preview flag)

# ── Logging ──────────────────────────────────────────────────────────────────
log_file: logs/scrumsurvivor.log
log_level: INFO             # DEBUG, INFO, WARNING, ERROR

# ── Idle Animation ───────────────────────────────────────────────────────────
blink_interval_range: [4.0, 8.0]  # Random seconds between recorded blink clips
breathing_clip_interval_range: [10.0, 15.0]  # Random seconds between recorded breathing clips
idle_clip_pause_min_s: 5.0      # Minimum static base-image time before the next supplemental idle clip
idle_clip_pause_max_s: 10.0     # Maximum static base-image time before the next supplemental idle clip
idle_after_speaking_cooldown_s: 5.0  # Minimum static base-image hold after speech before a new idle clip starts
# ── Audio Output ─────────────────────────────────────────────────────────
output_gain: 0.6            # Scale output audio (0.0-1.0) — reduces noise impact on lip-sync
presentation_release_ms: 1500  # ms of silence before switching SPEAKING→IDLE (bridges natural word gaps)
"""
    path.write_text(content, encoding="utf-8")
    logger.info("Generated default config at %s", config_path)


def _validate(config: AppConfig) -> None:
    """Raise ValueError for obviously invalid config values."""
    if config.target_fps <= 0:
        raise ValueError(f"target_fps must be positive, got {config.target_fps}")
    if len(config.output_resolution) != 2:
        raise ValueError("output_resolution must have exactly 2 elements [width, height]")
    if config.output_resolution[0] <= 0 or config.output_resolution[1] <= 0:
        raise ValueError("output_resolution values must be positive")
    if (
        len(config.blink_interval_range) != 2
        or config.blink_interval_range[0] >= config.blink_interval_range[1]
    ):
        raise ValueError("blink_interval_range must be [min, max] with min < max")
    if (
        len(config.breathing_clip_interval_range) != 2
        or config.breathing_clip_interval_range[0] >= config.breathing_clip_interval_range[1]
    ):
        raise ValueError(
            "breathing_clip_interval_range must be [min, max] with min < max"
        )
    if config.idle_clip_pause_min_s < 0:
        raise ValueError("idle_clip_pause_min_s must be non-negative")
    if config.idle_clip_pause_max_s < config.idle_clip_pause_min_s:
        raise ValueError("idle_clip_pause_max_s must be >= idle_clip_pause_min_s")
    if config.idle_after_speaking_cooldown_s < 0:
        raise ValueError("idle_after_speaking_cooldown_s must be non-negative")
    if config.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise ValueError(f"Invalid log_level: {config.log_level!r}")
