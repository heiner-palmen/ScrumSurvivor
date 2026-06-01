"""ScrumSurvivor CLI — entry point for all commands."""

from __future__ import annotations

import logging
import sys

import click

from scrumsurvivor.config.settings import (
    DEFAULT_CONFIG_PATH,
    AppConfig,
    generate_default_config,
    load_config,
    resolve_asset_paths,
    save_config,
)


def _setup_logging(config: AppConfig) -> None:
    import os
    from pathlib import Path

    log_path = Path(config.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, config.log_level.upper(), logging.INFO)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_path, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        handlers=handlers,
    )


@click.group()
def cli() -> None:
    """ScrumSurvivor — survive mandatory camera-on meetings."""


def _discover_themes() -> list[str]:
    """Return sorted names of themes that have a base_photo.png."""
    from pathlib import Path

    themes_dir = Path("assets") / "themes"
    if not themes_dir.exists():
        return []
    return sorted(
        d.name for d in themes_dir.iterdir()
        if d.is_dir() and (d / "base_photo.png").exists()
    )


def _discover_theme_options(config: AppConfig) -> list[str | None]:
    """Return startup-selectable asset options, including the configured default assets."""
    from pathlib import Path

    options: list[str | None] = []
    if Path(config.base_photo_path).exists():
        options.append(None)
    options.extend(_discover_themes())
    return options


def _prompt_theme_selection(
    options: list[str | None],
    default_theme: str | None = None,
) -> str | None:
    """Show an interactive CLI prompt to pick a theme or the default asset set."""
    default_choice = 1
    if default_theme in options:
        default_choice = options.index(default_theme) + 1

    click.echo("\n  Available asset themes:")
    for i, name in enumerate(options):
        label = "(default)" if name is None else name
        click.echo(f"    [{i + 1}]  {label}")
    click.echo()

    if len(options) == 1:
        return options[0]

    while True:
        raw = click.prompt(
            f"  Select a theme [1–{len(options)}]",
            default=str(default_choice),
        )
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except ValueError:
            pass
        click.echo(f"  Please enter a number between 1 and {len(options)}.")


def _maybe_select_theme_for_startup(cfg: AppConfig, prompt_theme: bool) -> None:
    """Resolve the asset set to use for this run.

    Explicit CLI ``--theme`` handling happens before this helper. When
    ``prompt_theme`` is enabled, the user gets a startup selector whenever
    multiple asset sets are available. Otherwise, missing default assets fall
    back to the available themes.
    """
    from pathlib import Path

    theme_options = _discover_theme_options(cfg)
    default_assets_exist = Path(cfg.base_photo_path).exists()

    if prompt_theme:
        if not theme_options:
            return
        if len(theme_options) == 1:
            cfg.active_theme = theme_options[0]
            return
        cfg.active_theme = _prompt_theme_selection(
            theme_options,
            default_theme=cfg.active_theme,
        )
        return

    if cfg.active_theme is not None or default_assets_exist:
        return

    if len(theme_options) == 1:
        cfg.active_theme = theme_options[0]
        if cfg.active_theme is not None:
            click.echo(f"INFO: default assets not found; using theme {cfg.active_theme!r}.")
        return

    if len(theme_options) > 1:
        cfg.active_theme = _prompt_theme_selection(theme_options)


@cli.command()
@click.option(
    "--config", default=DEFAULT_CONFIG_PATH, show_default=True,
    help="Path to config.yaml"
)
@click.option("--preview/--no-preview", default=None, help="Override preview window from config")
@click.option(
    "--theme",
    default=None,
    help="Theme name under assets/themes/<name> (overrides config active_theme)",
)
@click.option(
    "--prompt-theme",
    is_flag=True,
    default=False,
    help="Prompt to choose which asset set to use for this run",
)
def run(config: str, preview: bool | None, theme: str | None, prompt_theme: bool) -> None:
    """Run the virtual camera pipeline."""
    import cv2
    from scrumsurvivor.pipeline import Pipeline

    from pathlib import Path

    cfg = load_config(config)
    if theme:
        cfg.active_theme = theme
    else:
        _maybe_select_theme_for_startup(cfg, prompt_theme=prompt_theme)
    if preview is True:
        cfg.preview_enabled = True
    elif preview is False:
        cfg.preview_enabled = False
    _setup_logging(cfg)

    logger = logging.getLogger(__name__)
    logger.info("Starting ScrumSurvivor pipeline…")

    # ── Resolve assets (theme-aware) and load base photo ─────────────────────
    base_photo_path, idle_clips_dir = resolve_asset_paths(cfg)

    base_photo = cv2.imread(base_photo_path)
    if base_photo is None:
        click.echo(f"ERROR: base_photo not found at {base_photo_path!r}. "
                   "Run 'validate-assets' for details.", err=True)
        raise SystemExit(1)
    w, h = cfg.output_resolution
    base_photo = cv2.resize(base_photo, (w, h))

    # ── Phase 2: Idle compositor ──────────────────────────────────────────────
    from scrumsurvivor.idle.idle_compositor import IdleCompositor
    from scrumsurvivor.idle.clip_manager import IdleClipManager

    clip_mgr = IdleClipManager(
        idle_clips_dir,
        pause_min_s=cfg.idle_clip_pause_min_s,
        pause_max_s=cfg.idle_clip_pause_max_s,
        blink_interval_range=tuple(cfg.blink_interval_range),  # type: ignore[arg-type]
        breathing_interval_range=tuple(cfg.breathing_clip_interval_range),  # type: ignore[arg-type]
    )
    clip_mgr.load()

    idle_compositor = IdleCompositor(
        base_image=base_photo,
        clip_manager=clip_mgr,
        transition_frames=cfg.crossfade_frames,
    )

    # ── Phase 3: Lipsync ──────────────────────────────────────────────────────
    from scrumsurvivor.lipsync.gpu_check import check_gpu, require_gpu
    from scrumsurvivor.lipsync.face_crop import FaceCropManager
    from scrumsurvivor.lipsync.audio_preprocessor import AudioPreprocessor
    from scrumsurvivor.lipsync.wav2lip_engine import Wav2LipEngine

    gpu_report = check_gpu()
    if not gpu_report.sufficient:
        click.echo(
            "WARNING: No sufficient GPU found — lipsync disabled. "
            "Avatar will show idle animation only.", err=True
        )
        lipsync_engine = None
        face_crop_mgr = None
        audio_preprocessor = None
    else:
        logger.info("Loading Wav2Lip model…")
        lipsync_engine = Wav2LipEngine(
            model_path=cfg.wav2lip_model_path,
            device="cuda",
        )
        face_crop_mgr = FaceCropManager(
            base_photo=base_photo,
            preset_rect=cfg.face_crop_rect,
            mouth_rect=cfg.mouth_crop_rect,
        )
        logger.info("Detecting face in base photo…")
        rect = face_crop_mgr.detect()
        if rect is None:
            click.echo(
                "WARNING: Could not detect face in base_photo.png — "
                "lipsync disabled. Check that base_photo.png shows your face clearly.",
                err=True,
            )
            lipsync_engine = None
            face_crop_mgr = None
            audio_preprocessor = None
        else:
            logger.info("Face detected at %s", rect)
            audio_preprocessor = AudioPreprocessor(sample_rate=cfg.sample_rate)

            # Warm up CUDA / TorchScript JIT to avoid first-frame hiccup.
            # The GPU needs several inferences to ramp clocks and compile all
            # JIT paths.  We run until latency stabilises (< 50 ms) or until
            # a hard cap to avoid a very long startup.
            logger.info("Warming up Wav2Lip inference…")
            _warmup_face = face_crop_mgr.get_crop()
            if _warmup_face is not None:
                import time as _time
                import numpy as _np
                import torch as _torch

                _warmup_mel = _np.zeros((1, 80, 16), dtype=_np.float32)
                _MAX_WARMUP_ITERS = 20
                _TARGET_MS = 50.0   # consider settled once a frame is this fast
                for _wi in range(_MAX_WARMUP_ITERS):
                    _t0 = _time.perf_counter()
                    lipsync_engine.process(_warmup_face, _warmup_mel)
                    if lipsync_engine._device_str == "cuda":
                        _torch.cuda.synchronize(lipsync_engine._device)
                    _elapsed_ms = (_time.perf_counter() - _t0) * 1000
                    logger.debug(
                        "Wav2Lip warmup iter %d: %.1f ms", _wi + 1, _elapsed_ms
                    )
                    if _elapsed_ms < _TARGET_MS:
                        logger.info(
                            "Wav2Lip warmup complete after %d iter(s) (%.1f ms).",
                            _wi + 1,
                            _elapsed_ms,
                        )
                        break
                else:
                    logger.warning(
                        "Wav2Lip warmup: reached %d iterations without settling"
                        " below %.0f ms — continuing anyway.",
                        _MAX_WARMUP_ITERS,
                        _TARGET_MS,
                    )

    # ── Phase 5: Compositor + transition ─────────────────────────────────────
    from scrumsurvivor.compositor.frame_compositor import FrameCompositor
    from scrumsurvivor.compositor.transition import CrossfadeTransition

    frame_compositor = FrameCompositor(output_size=(w, h))
    transition = CrossfadeTransition(n_frames=cfg.crossfade_frames)

    # ── Wire pipeline ─────────────────────────────────────────────────────────
    pipeline = Pipeline(cfg)
    pipeline.set_base_photo(base_photo)
    pipeline.set_idle_processor(idle_compositor)
    if lipsync_engine is not None:
        pipeline.set_lipsync_engine(lipsync_engine)
        pipeline.set_face_crop_manager(face_crop_mgr)
        pipeline.set_audio_preprocessor(audio_preprocessor)
    pipeline.set_frame_compositor(frame_compositor)
    pipeline.set_transition(transition)

    pipeline.run()


@cli.command()
@click.option(
    "--config", default=DEFAULT_CONFIG_PATH, show_default=True,
    help="Path to config.yaml"
)
def generate_config(config: str) -> None:
    """Generate a commented default config.yaml."""
    from pathlib import Path

    if Path(config).exists():
        click.confirm(
            f"{config!r} already exists. Overwrite?", abort=True
        )
    generate_default_config(config)
    click.echo(f"Config written to {config!r}")


@cli.command()
@click.option(
    "--config", default=DEFAULT_CONFIG_PATH, show_default=True
)
def check_gpu(config: str) -> None:
    """Check GPU capability for lipsync mode."""
    from scrumsurvivor.lipsync.gpu_check import check_gpu as _check, print_gpu_report

    report = _check()
    print_gpu_report(report)
    if not report.sufficient:
        sys.exit(1)


@cli.command()
@click.option(
    "--config", default=DEFAULT_CONFIG_PATH, show_default=True
)
def validate_assets(config: str) -> None:
    """Verify that required asset files are present."""
    from pathlib import Path

    cfg = load_config(config)
    base_photo_path, _ = resolve_asset_paths(cfg)
    missing: list[str] = []
    for path_str in (base_photo_path,):
        if not Path(path_str).exists():
            missing.append(path_str)

    if missing:
        click.echo("Missing assets:")
        for p in missing:
            click.echo(f"  {p}")
        sys.exit(1)
    else:
        click.echo("All required assets found.")


@cli.command()
@click.option(
    "--config", default=DEFAULT_CONFIG_PATH, show_default=True
)
@click.option(
    "--iterations", default=20, show_default=True,
    help="Number of Wav2Lip iterations for latency measurement"
)
@click.option(
    "--verify-sync", is_flag=True, default=False,
    help="Also run A/V sync verification after calibration"
)
def calibrate(config: str, iterations: int, verify_sync: bool) -> None:
    """Measure Wav2Lip latency and (optionally) verify A/V sync."""
    import numpy as np
    from scrumsurvivor.lipsync.gpu_check import check_gpu, require_gpu
    from scrumsurvivor.lipsync.wav2lip_engine import Wav2LipEngine
    from scrumsurvivor.audio.latency_calibrator import LatencyCalibrator
    from scrumsurvivor.audio.sync_verifier import SyncVerifier

    cfg = load_config(config)
    _setup_logging(cfg)

    report = check_gpu()
    require_gpu(report)

    click.echo("Loading Wav2Lip model…")
    engine = Wav2LipEngine(
        model_path=cfg.wav2lip_model_path,
        device="cuda",
    )

    face = np.zeros((96, 96, 3), dtype=np.uint8)
    mel = np.zeros((1, 80, 16), dtype=np.float32)

    cal = LatencyCalibrator(engine, face, mel, iterations=iterations)
    delay_ms = cal.calibrate()
    stats = cal.get_stats()

    click.echo(
        f"Latency: avg={stats['avg_ms']:.1f}ms  std={stats['std_ms']:.1f}ms  "
        f"recommended_delay={delay_ms:.1f}ms"
    )

    if cfg.audio_delay_ms is None:
        cfg.audio_delay_ms = int(delay_ms)
        save_config(cfg, config)
        click.echo(f"audio_delay_ms set to {cfg.audio_delay_ms} ms and saved to {config!r}")

    if verify_sync:
        verifier = SyncVerifier(
            audio_delay_ms=cfg.audio_delay_ms,
            wav2lip_avg_latency_ms=stats["avg_ms"],
        )
        result = verifier.run_test()
        click.echo(
            f"Sync: offset={result['offset_ms']:.1f}ms  "
            f"in_sync={result['in_sync']}"
        )
        if result["recommendation"]:
            click.echo(f"Recommendation: {result['recommendation']}")


@cli.command()
@click.option(
    "--config", default=DEFAULT_CONFIG_PATH, show_default=True
)
def setup(config: str) -> None:
    """Interactive first-run setup wizard."""
    from scrumsurvivor.setup_wizard import run_setup_wizard

    run_setup_wizard(config)


@cli.command(name="test-mode")
@click.option(
    "--config", default=DEFAULT_CONFIG_PATH, show_default=True
)
@click.option(
    "--frames", default=150, show_default=True,
    help="Number of frames to run before stopping"
)
def test_mode(config: str, frames: int) -> None:
    """Run the pipeline for a fixed number of frames then exit (smoke test)."""
    import numpy as np
    from scrumsurvivor.config.settings import AppConfig
    from scrumsurvivor.pipeline import Pipeline

    cfg = load_config(config)
    _setup_logging(cfg)

    click.echo(f"Running test mode for {frames} frames…")
    # Monkey-patch to stop after N frames
    original_main_loop = Pipeline._main_loop
    frame_count = [0]

    def limited_loop(self):  # type: ignore[no-untyped-def]
        import time
        assert self._microphone is not None
        assert self._speech_detector is not None
        assert self._virtual_camera is not None

        frame_interval = 1.0 / self._config.target_fps
        while self._running and frame_count[0] < frames:
            t_start = time.monotonic()
            output_frame = self._compose_frame(self.state)
            self._virtual_camera.send(output_frame)
            frame_count[0] += 1
            elapsed = time.monotonic() - t_start
            sleep_s = frame_interval - elapsed
            if sleep_s > 0:
                time.sleep(sleep_s)
        self._running = False

    Pipeline._main_loop = limited_loop  # type: ignore[method-assign]
    try:
        pipeline = Pipeline(cfg)
        pipeline.run()
        click.echo(f"Test mode completed {frame_count[0]} frames successfully.")
    finally:
        Pipeline._main_loop = original_main_loop  # type: ignore[method-assign]
