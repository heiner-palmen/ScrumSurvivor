"""Interactive first-run setup wizard for hardware configuration."""

from __future__ import annotations

import sys
from dataclasses import dataclass

import click

from scrumsurvivor.audio.device_selector import (
    format_output_device_selector,
    output_device_score,
    resolve_hostapi_name,
)
from scrumsurvivor.capture.microphone import MicrophoneCapture
from scrumsurvivor.config.settings import AppConfig, load_config, save_config

_CABLE_KEYWORDS = ("cable", "vb-cable", "vb cable", "virtual audio")
_METER_WIDTH = 40
_MIN_SPEECH_THRESHOLD = 0.005
_CLEAR_LINE = " " * 160


@dataclass(frozen=True, slots=True)
class DeviceOption:
    value: int | str | None
    label: str
    details: str = ""
    device_index: int | None = None
    default_sample_rate: int | None = None


def run_setup_wizard(config_path: str) -> AppConfig:
    """Guide the user through initial audio/output selection and threshold tuning."""
    cfg = load_config(config_path)

    click.echo("=== ScrumSurvivor Setup ===")
    click.echo(
        "pyvirtualcam backend selection is fixed to auto-detect and is no longer written to config.yaml."
    )
    click.echo("")

    microphone_choice = prompt_for_device_choice(
        title="Microphone",
        options=list_microphone_options(),
        current_value=cfg.microphone_device,
        prompt_text="Select the microphone ScrumSurvivor should listen to",
    )
    cfg.microphone_device = microphone_choice.value

    virtual_audio_choice = prompt_for_device_choice(
        title="Virtual audio output",
        options=list_virtual_audio_output_options(),
        current_value=cfg.virtual_audio_device,
        prompt_text="Select the VB-Cable or virtual audio endpoint ScrumSurvivor should feed",
    )
    cfg.virtual_audio_device = str(virtual_audio_choice.value)

    cfg.sample_rate = resolve_sample_rate(
        microphone_choice=microphone_choice,
        virtual_audio_choice=virtual_audio_choice,
        fallback_rate=cfg.sample_rate,
    )
    click.echo(f"Sample rate: {cfg.sample_rate} Hz")
    click.echo("")

    cfg.preview_enabled = click.confirm(
        "Enable the local preview window while running?",
        default=cfg.preview_enabled,
    )

    if click.confirm("Run live speech-threshold tuning now?", default=True):
        cfg.speech_threshold = tune_speech_threshold(
            microphone_device=cfg.microphone_device,
            sample_rate=cfg.sample_rate,
            current_threshold=cfg.speech_threshold,
        )
        click.echo(f"Selected speech threshold: {cfg.speech_threshold:.4f}")
    elif cfg.speech_threshold is None:
        click.echo("Speech threshold left unset. ScrumSurvivor will auto-calibrate at startup.")
    else:
        click.echo(f"Keeping existing speech threshold: {cfg.speech_threshold:.4f}")

    click.echo("")
    click.echo("Panic button — press Ctrl+Shift+P during a meeting to instantly switch to your")
    click.echo("real webcam and route audio without delay (no illusion, useful when something looks wrong).")
    click.echo("")
    panic_webcam_options = list_webcam_options()
    if not panic_webcam_options:
        click.echo("No webcams detected — panic button webcam cannot be configured.")
    else:
        _print_webcam_options(panic_webcam_options)
        panic_index, panic_backend = _prompt_webcam_choice(panic_webcam_options, cfg.panic_webcam_device)
        cfg.panic_webcam_device = panic_index
        cfg.panic_webcam_backend = panic_backend
        cfg.panic_webcam_mirror = click.confirm(
            "Mirror (horizontally flip) the panic cam feed?",
            default=cfg.panic_webcam_mirror,
        )

    save_config(cfg, config_path)
    click.echo("")
    click.echo(f"Configuration saved to {config_path!r}")
    click.echo("Setup complete.")
    return cfg


def list_microphone_options() -> list[DeviceOption]:
    """Return selectable input devices with helpful labels."""
    import sounddevice as sd

    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    options: list[DeviceOption] = []

    default_input_id = _default_input_device_id(sd)
    if default_input_id is not None and 0 <= default_input_id < len(devices):
        default_info = devices[default_input_id]
        if default_info.get("max_input_channels", 0) > 0:
            options.append(
                DeviceOption(
                    value=None,
                    label="System default",
                    details=(
                        f"{default_info['name']} | {_hostapi_name(hostapis, default_info)} | "
                        f"default {_sample_rate_from_device(default_info) or '?'} Hz"
                    ),
                    device_index=default_input_id,
                    default_sample_rate=_sample_rate_from_device(default_info),
                )
            )

    for index, device_info in enumerate(devices):
        if device_info.get("max_input_channels", 0) <= 0:
            continue
        options.append(
            DeviceOption(
                value=index,
                label=str(device_info["name"]),
                details=_device_details(index, device_info, hostapis, channel_key="max_input_channels"),
                device_index=index,
                default_sample_rate=_sample_rate_from_device(device_info),
            )
        )
    return options


def list_virtual_audio_output_options() -> list[DeviceOption]:
    """Return available output devices, with VB-Cable-like devices sorted first."""
    import sounddevice as sd

    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    scored_options: list[tuple[int, DeviceOption]] = []

    for index, device_info in enumerate(devices):
        if device_info.get("max_output_channels", 0) <= 0:
            continue
        name = str(device_info["name"])
        hostapi_name = resolve_hostapi_name(device_info, hostapis)
        details = _device_details(index, device_info, hostapis, channel_key="max_output_channels")
        if any(keyword in name.lower() for keyword in _CABLE_KEYWORDS):
            details = f"{details} | recommended"
        scored_options.append(
            (
                output_device_score(device_info, hostapi_name),
                DeviceOption(
                    value=format_output_device_selector(
                        name=name,
                        hostapi_name=hostapi_name,
                        device_id=index,
                    ),
                    label=f"{name} [{hostapi_name}]",
                    details=details,
                    device_index=index,
                    default_sample_rate=_sample_rate_from_device(device_info),
                ),
            )
        )

    scored_options.sort(key=lambda item: (-item[0], item[1].label.lower()))
    return [option for _, option in scored_options]


def prompt_for_device_choice(
    title: str,
    options: list[DeviceOption],
    current_value: int | str | None,
    prompt_text: str,
) -> DeviceOption:
    """Render a numbered device list and return the selected option."""
    if not options:
        raise click.ClickException(f"No options are available for {title.lower()}.")

    click.echo(title)
    for position, option in enumerate(options, start=1):
        click.echo(f"  {position}. {option.label}")
        if option.details:
            click.echo(f"     {option.details}")

    selection = click.prompt(
        prompt_text,
        type=click.IntRange(1, len(options)),
        default=_default_choice_number(options, current_value),
        show_default=True,
    )
    click.echo("")
    return options[selection - 1]


def resolve_sample_rate(
    microphone_choice: DeviceOption,
    virtual_audio_choice: DeviceOption,
    fallback_rate: int,
) -> int:
    """Pick a sample rate both selected devices accept, preferring the output native rate."""
    import sounddevice as sd

    if microphone_choice.device_index is None or virtual_audio_choice.device_index is None:
        return fallback_rate

    candidates: list[int] = []
    for rate in (
        virtual_audio_choice.default_sample_rate,
        fallback_rate,
        microphone_choice.default_sample_rate,
        48_000,
        44_100,
    ):
        normalized = _normalize_sample_rate(rate)
        if normalized is not None and normalized not in candidates:
            candidates.append(normalized)

    for candidate in candidates:
        try:
            sd.check_input_settings(
                device=microphone_choice.device_index,
                samplerate=candidate,
                channels=1,
                dtype="float32",
            )
            sd.check_output_settings(
                device=virtual_audio_choice.device_index,
                samplerate=candidate,
                channels=1,
                dtype="float32",
            )
        except Exception:
            continue
        return candidate

    click.echo(
        f"Could not verify a common sample rate for the selected devices. Keeping {fallback_rate} Hz."
    )
    return fallback_rate


def tune_speech_threshold(
    microphone_device: int | str | None,
    sample_rate: int,
    current_threshold: float | None,
) -> float:
    """Show a live volume meter and let the user position the threshold marker."""
    threshold = current_threshold if current_threshold is not None else 0.05

    click.echo("Speech threshold tuning")
    click.echo("")
    click.echo("  The bar below shows your live microphone volume.")
    click.echo("  Use Left / Right arrow keys to move the | marker.")
    click.echo("  Position it just above background noise and below your speaking level.")
    click.echo("  Press Enter to accept.")
    click.echo("")

    with MicrophoneCapture(device=microphone_device, sample_rate=sample_rate) as mic:
        threshold = _live_threshold_loop(mic, threshold)

    click.echo("")
    return threshold


# ── Cross-platform keyboard helpers ──────────────────────────────────────

def _kbhit() -> bool:
    """Non-blocking check for a pending keystroke."""
    if sys.platform == "win32":
        import msvcrt

        return msvcrt.kbhit()
    import select

    dr, _, _ = select.select([sys.stdin], [], [], 0)
    return dr != []


def _getch() -> str:
    """Read a single character (or escape sequence) from stdin."""
    if sys.platform == "win32":
        import msvcrt

        return msvcrt.getwch()
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


def _read_key() -> str | None:
    """Read a keypress, normalising arrow-key sequences across platforms.

    Returns:
        'enter' for Enter/Return,
        'left' / 'right' for arrow keys,
        or the raw character for anything else.
    """
    if not _kbhit():
        return None

    ch = _getch()

    # Enter
    if ch in ("\r", "\n"):
        return "enter"

    # Windows function-key prefix
    if sys.platform == "win32":
        if ch in ("\x00", "\xe0"):
            next_ch = _getch()
            if next_ch == "\x4d":
                return "right"
            if next_ch == "\x4b":
                return "left"
        return ch

    # POSIX: ESC sequence for arrow keys  (\x1b [ A/B/C/D)
    if ch == "\x1b":
        second = _getch()
        if second == "[":
            third = _getch()
            if third == "D":
                return "left"
            if third == "C":
                return "right"
    return ch


def _live_threshold_loop(mic: MicrophoneCapture, threshold: float) -> float:
    _SCALE = 1.0  # bar always shows 0..1 range
    current_rms = 0.0

    while True:
        chunk = mic.read(block=True, timeout=0.05)
        if chunk is not None:
            current_rms = MicrophoneCapture.rms(chunk)

        sys.stdout.write("\r" + _format_level_meter(current_rms, threshold, _SCALE).ljust(140))
        sys.stdout.flush()

        key = _read_key()
        if key is None:
            continue
        if key == "enter":
            break
        step = _SCALE / _METER_WIDTH
        if key == "right":
            threshold = min(_SCALE, threshold + step)
        elif key == "left":
            threshold = max(_MIN_SPEECH_THRESHOLD, threshold - step)

    sys.stdout.write("\r" + _CLEAR_LINE + "\r")
    sys.stdout.flush()
    return threshold


def _format_level_meter(level: float, threshold: float, scale: float) -> str:
    scale = max(scale, threshold * 1.25, 0.05)
    threshold_column = min(
        _METER_WIDTH - 1,
        int(round((threshold / scale) * (_METER_WIDTH - 1))),
    )
    filled_columns = min(_METER_WIDTH, int(round((level / scale) * _METER_WIDTH)))

    triggered = level >= threshold
    meter = [" "] * _METER_WIDTH
    for index in range(filled_columns):
        meter[index] = "#"
    meter[threshold_column] = "!" if triggered else "|"

    state = "SPEAKING " if triggered else "quiet    "
    return (
        f"  [{''.join(meter)}]  vol {level:0.4f}  threshold {threshold:0.4f}  {state}"
        f"   <- -> to move"
    )


def _default_choice_number(options: list[DeviceOption], current_value: int | str | None) -> int:
    if current_value is None:
        for position, option in enumerate(options, start=1):
            if option.value is None:
                return position
        return 1

    normalized_current = str(current_value).strip().lower()
    for position, option in enumerate(options, start=1):
        option_value = option.value
        if option_value == current_value:
            return position
        if option_value is None:
            continue
        normalized_option = str(option_value).strip().lower()
        if normalized_option == normalized_current:
            return position
        if normalized_current in normalized_option or normalized_option in normalized_current:
            return position
    return 1


def _default_input_device_id(sounddevice_module: object) -> int | None:
    default_device = getattr(sounddevice_module.default, "device", None)
    if isinstance(default_device, (tuple, list)) and default_device:
        default_input = default_device[0]
    else:
        default_input = default_device
    if default_input is None:
        return None
    try:
        device_id = int(default_input)
    except (TypeError, ValueError):
        return None
    return device_id if device_id >= 0 else None


def _device_details(index: int, device_info: dict, hostapis: list[dict], channel_key: str) -> str:
    channels = int(device_info.get(channel_key, 0))
    sample_rate = _sample_rate_from_device(device_info)
    sample_rate_text = f"default {sample_rate} Hz" if sample_rate is not None else "default rate unknown"
    return (
        f"id {index} | {_hostapi_name(hostapis, device_info)} | "
        f"{channels} channel(s) | {sample_rate_text}"
    )


def _hostapi_name(hostapis: list[dict], device_info: dict) -> str:
    hostapi_name = resolve_hostapi_name(device_info, hostapis)
    return hostapi_name if hostapi_name != "unknown" else "unknown host API"


def _sample_rate_from_device(device_info: dict) -> int | None:
    return _normalize_sample_rate(device_info.get("default_samplerate"))


def _normalize_sample_rate(value: object) -> int | None:
    try:
        sample_rate = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return sample_rate if sample_rate > 0 else None


# ── Panic webcam helpers ──────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class _WebcamOption:
    slot: int
    capture_index: int
    name: str
    backend: int = 0  # cv2 backend constant returned by cv2_enumerate_cameras


def list_webcam_options() -> list[_WebcamOption]:
    """Return available webcam devices enumerated via cv2_enumerate_cameras."""
    try:
        from cv2_enumerate_cameras import enumerate_cameras as _enum
    except ImportError:
        _enum = None

    if _enum is None:
        return []

    try:
        cameras_raw = _enum()
    except Exception:
        return []

    # Deduplicate by device path (same approach as create_assets.py)
    seen: dict[str, _WebcamOption] = {}
    for cam in cameras_raw:
        capture_index = int(getattr(cam, "index", -1))
        name = str(getattr(cam, "name", "")).strip() or f"Camera {capture_index}"
        backend = int(getattr(cam, "backend", 0) or 0)
        # cv2_enumerate_cameras returns composite indices (e.g. 1402 = MSMF:1400 + device:2).
        # Store the raw device index so cv2.VideoCapture(raw, backend) works correctly.
        raw_index = capture_index - backend if backend > 0 and capture_index >= backend else capture_index
        path = str(getattr(cam, "path", "") or "").strip().lower().split("#{", 1)[0]
        key = path if path else f"name:{name.lower()}"
        if key not in seen:
            seen[key] = _WebcamOption(slot=0, capture_index=raw_index, name=name, backend=backend)

    result = []
    for slot, opt in enumerate(seen.values(), start=1):
        result.append(_WebcamOption(slot=slot, capture_index=opt.capture_index, name=opt.name, backend=opt.backend))
    return result


def _print_webcam_options(options: list[_WebcamOption]) -> None:
    click.echo("Webcam for panic button")
    for opt in options:
        click.echo(f"  {opt.slot}. {opt.name}  (OpenCV index {opt.capture_index})")
    click.echo("  0. Disable panic button webcam")
    click.echo("")


def _prompt_webcam_choice(
    options: list[_WebcamOption],
    current_value: int | str | None,
) -> tuple[int, int] | tuple[None, None]:
    """Prompt the user to pick a webcam for the panic button.

    Returns ``(capture_index, backend)`` or ``(None, None)`` when disabled.
    """
    # Determine default slot
    default_slot = 0
    if current_value is not None:
        try:
            current_idx = int(current_value)
            for opt in options:
                if opt.capture_index == current_idx:
                    default_slot = opt.slot
                    break
        except (TypeError, ValueError):
            pass

    valid_slots = {opt.slot for opt in options} | {0}

    while True:
        raw = click.prompt(
            "Select webcam for panic button [0 to disable]",
            default=str(default_slot),
        )
        try:
            choice = int(raw)
        except ValueError:
            click.echo("  Please enter a number.")
            continue
        if choice not in valid_slots:
            click.echo(f"  Please enter one of: {sorted(valid_slots)}")
            continue
        if choice == 0:
            click.echo("  Panic button webcam disabled.")
            return None, None
        for opt in options:
            if opt.slot == choice:
                click.echo(f"  Panic button webcam set to: {opt.name}")
                return opt.capture_index, opt.backend
        break
    return None, None