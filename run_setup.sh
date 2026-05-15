#!/usr/bin/env bash
# ScrumSurvivor — Full Prerequisites & Installation Wizard
# Run this ONCE on a new machine before anything else.
# Usage:  ./run_setup.sh
#
# What it does (in order, skipping steps that are already done):
#   0.  Install pactl (pulseaudio-utils)
#   1.  Verify Python 3.10+ is available
#   1b. Install python3-dev headers (for building pip packages)
#   2.  Create Python .venv and install pip packages
#   3.  Install PyTorch with CUDA support (auto-detects CUDA version)
#   4.  Set up virtual audio (PulseAudio null-sink or PipeWire)
#   5.  Check / guide v4l2loopback + OBS Virtual Camera installation
#   6.  Check / install ffmpeg
#   7.  Check / download Wav2Lip model weights (models/)
#   8.  Remind user to run ./run_config.sh next

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
GRAY='\033[0;90m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

write_step() {
    local number="$1" title="$2"
    echo ""
    echo -e "  ${CYAN}[$number/7] $title${NC}"
    echo -e "  ${GRAY}────────────────────────────────────────────────────────────${NC}"
}

write_ok()   { echo -e "  ${GREEN}✓ $1${NC}"; }
write_warn() { echo -e "  ${YELLOW}! $1${NC}"; }
write_err()  { echo -e "  ${RED}✗ $1${NC}"; }
write_info() { echo -e "  ${GRAY}$1${NC}"; }

pause_for_user() {
    local prompt="${1:-Press ENTER to continue...}"
    echo ""
    echo -en "  ${WHITE}$prompt${NC}"
    read -r
    echo ""
}

ask_yes_no() {
    local question="$1"
    local default="${2:-true}"
    local hint
    if [[ "$default" == "true" ]]; then
        hint="[Y/n]"
    else
        hint="[y/N]"
    fi
    echo ""
    echo -en "  ${WHITE}$question $hint ${NC}" >&2
    read -r _ASK_ANSWER
    if [[ -z "$_ASK_ANSWER" ]]; then
        _ASK_RESULT="$default"
        return
    fi
    if [[ "${_ASK_ANSWER,,}" == y* ]]; then
        _ASK_RESULT="true"
    else
        _ASK_RESULT="false"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# Banner
# ─────────────────────────────────────────────────────────────────────────────

clear
echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║       ScrumSurvivor — Installation & Setup Wizard        ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${WHITE}This wizard installs all prerequisites for ScrumSurvivor.${NC}"
echo -e "  ${GRAY}Steps that are already complete are skipped automatically.${NC}"
echo ""
echo -e "  ${YELLOW}Prerequisites (ensure these are met before continuing):${NC}"
echo -e "  ${WHITE}• Python 3.10+ must be installed system-wide.${NC}"
echo -e "  ${WHITE}• A package manager (apt / dnf / pacman) is required for system packages.${NC}"
echo ""
pause_for_user "Press ENTER to start..."

# ─────────────────────────────────────────────────────────────────────────────
# Detect package manager
# ─────────────────────────────────────────────────────────────────────────────

PKG_CMD=""
if command -v apt-get &>/dev/null; then
    PKG_CMD="apt-get"
elif command -v dnf &>/dev/null; then
    PKG_CMD="dnf"
elif command -v yum &>/dev/null; then
    PKG_CMD="yum"
elif command -v pacman &>/dev/null; then
    PKG_CMD="pacman"
elif command -v zypper &>/dev/null; then
    PKG_CMD="zypper"
elif command -v apk &>/dev/null; then
    PKG_CMD="apk"
fi

pkg_install() {
    local pkg="$1"
    case "$PKG_CMD" in
        apt-get) sudo apt-get install -y "$pkg" ;;
        dnf|yum) sudo "$PKG_CMD" install -y "$pkg" ;;
        pacman)  sudo pacman -S --noconfirm "$pkg" ;;
        zypper)  sudo zypper install -y "$pkg" ;;
        apk)     sudo apk add "$pkg" ;;
        *)       write_err "No supported package manager found. Install '$pkg' manually." ;;
    esac
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 0 — Install pactl (pulseaudio-utils) + libportaudio2
# ─────────────────────────────────────────────────────────────────────────────

write_step 0 "pactl (PulseAudio Utilities) + libportaudio2"

# ── pactl ─────────────────────────────────────────────────────────────────────
if command -v pactl &>/dev/null; then
    write_ok "pactl is already available."
else
    write_info "Installing pactl ..."
    case "$PKG_CMD" in
        apt-get)       PACTL_PKG="pulseaudio-utils" ;;
        dnf|yum)       PACTL_PKG="pulseaudio-utils" ;;
        pacman)        PACTL_PKG="pulseaudio" ;;
        zypper)        PACTL_PKG="pulseaudio-utils" ;;
        apk)           PACTL_PKG="pulseaudio-utils" ;;
        *)             PACTL_PKG="" ;;
    esac

    if [[ -n "$PACTL_PKG" ]]; then
        if pkg_install "$PACTL_PKG"; then
            if command -v pactl &>/dev/null; then
                write_ok "pactl installed successfully."
            else
                write_warn "pactl still not found after installing $PACTL_PKG."
            fi
        else
            write_warn "Failed to install $PACTL_PKG — pactl may not be available."
        fi
    else
        write_warn "No supported package manager — install pactl manually."
    fi
fi

# ── libportaudio2 ─────────────────────────────────────────────────────────────
write_info "Checking for libportaudio2 ..."
case "$PKG_CMD" in
    apt-get)       PORTAUDIO_PKG="libportaudio2" ;;
    dnf|yum)       PORTAUDIO_PKG="portaudio" ;;
    pacman)        PORTAUDIO_PKG="portaudio" ;;
    zypper)        PORTAUDIO_PKG="portaudio" ;;
    apk)           PORTAUDIO_PKG="portaudio" ;;
    *)             PORTAUDIO_PKG="" ;;
esac

if [[ -n "$PORTAUDIO_PKG" ]]; then
    # Quick check: see if the package is already installed
    PKG_INSTALLED=false
    case "$PKG_CMD" in
        apt-get)       dpkg -s "$PORTAUDIO_PKG" &>/dev/null && PKG_INSTALLED=true ;;
        dnf)           dnf list installed "$PORTAUDIO_PKG" &>/dev/null && PKG_INSTALLED=true ;;
        yum)           yum list installed "$PORTAUDIO_PKG" &>/dev/null && PKG_INSTALLED=true ;;
        pacman)        pacman -Q "$PORTAUDIO_PKG" &>/dev/null && PKG_INSTALLED=true ;;
        zypper)        zypper se -i "$PORTAUDIO_PKG" &>/dev/null && PKG_INSTALLED=true ;;
        apk)           apk list -I "$PORTAUDIO_PKG" &>/dev/null && PKG_INSTALLED=true ;;
    esac

    if [[ "$PKG_INSTALLED" == "true" ]]; then
        write_ok "libportaudio2 ($PORTAUDIO_PKG) is already installed."
    else
        write_info "Installing libportaudio2 ($PORTAUDIO_PKG) ..."
        if pkg_install "$PORTAUDIO_PKG"; then
            write_ok "libportaudio2 installed successfully."
        else
            write_warn "Failed to install $PORTAUDIO_PKG — libportaudio2 may not be available."
        fi
    fi
else
    write_warn "No supported package manager — install libportaudio2 manually."
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Python version check
# ─────────────────────────────────────────────────────────────────────────────

write_step 1 "Python Version"

if ! command -v python3 &>/dev/null; then
    write_err "python3 not found. Please install Python 3.10+ and re-run this wizard."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR="${PYTHON_VERSION%%.*}"
PYTHON_MINOR="${PYTHON_VERSION##*.}"

if [[ "$PYTHON_MAJOR" -lt 3 ]] || { [[ "$PYTHON_MAJOR" -eq 3 ]] && [[ "$PYTHON_MINOR" -lt 10 ]]; }; then
    write_err "Python 3.10+ required, found $PYTHON_VERSION"
    exit 1
fi

write_ok "Python $PYTHON_VERSION detected."

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1b — python3-dev headers
# ─────────────────────────────────────────────────────────────────────────────

write_step 1b "Python Development Headers"

case "$PKG_CMD" in
    apt-get)       DEV_PKG="python3-dev" ;;
    dnf|yum)       DEV_PKG="python3-devel" ;;
    pacman)        DEV_PKG="python" ;;          # Arch bundles dev files in the main package
    zypper)        DEV_PKG="python3-devel" ;;
    apk)           DEV_PKG="python3-dev" ;;
    *)             DEV_PKG="" ;;
esac

if [[ -z "$DEV_PKG" ]]; then
    write_warn "No supported package manager — skipping python3-dev check."
elif dpkg -s "$DEV_PKG" &>/dev/null 2>&1 || \
     rpm -q "$DEV_PKG" &>/dev/null 2>&1 || \
     pacman -Q "$DEV_PKG" &>/dev/null 2>&1 || \
     zypper se -i "$DEV_PKG" &>/dev/null 2>&1 || \
     apk info "$DEV_PKG" &>/dev/null 2>&1; then
    write_ok "$DEV_PKG is already installed."
else
    write_info "Installing $DEV_PKG …"
    if pkg_install "$DEV_PKG"; then
        write_ok "$DEV_PKG installed."
    else
        write_warn "Failed to install $DEV_PKG — some pip packages may fail to build."
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Python venv + pip packages
# ─────────────────────────────────────────────────────────────────────────────

write_step 2 "Python Virtual Environment & Packages"

VENV_ACTIVATE="$SCRIPT_DIR/.venv/bin/activate"

if [[ -f "$VENV_ACTIVATE" ]]; then
    write_ok "Virtual environment already exists."
else
    write_info "Creating virtual environment..."
    python3 -m venv .venv
    if [[ $? -ne 0 ]]; then
        write_err "Failed to create virtual environment. Is Python 3.10+ installed?"
        exit 1
    fi
    write_ok "Virtual environment created."
fi

if [[ ! -f "$VENV_ACTIVATE" ]]; then
    write_err "Virtual environment activate script not found at $VENV_ACTIVATE"
    write_info "Re-run this wizard after ensuring the venv was created successfully."
    exit 1
fi

source "$VENV_ACTIVATE"

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    write_err "Virtual environment activation failed (VIRTUAL_ENV not set)."
    write_info "Re-run this wizard or manually activate with: source .venv/bin/activate"
    exit 1
fi

write_ok "Virtual environment '$VIRTUAL_ENV' is now active."

# Install requirements
if [[ -f "requirements.txt" ]]; then
    write_info "Installing requirements..."
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    if [[ $? -ne 0 ]]; then
        write_err "pip install failed. Check output above."
        exit 1
    fi
    write_ok "All packages installed."
else
    write_err "requirements.txt not found."
    exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — PyTorch with CUDA
# ─────────────────────────────────────────────────────────────────────────────

write_step 3 "PyTorch with CUDA GPU Support"

# Detect CUDA version
CUDA_VER="12.4"
if command -v nvcc &>/dev/null; then
    DETECTED_CUDA=$(nvcc --version | grep -oP 'V\K[0-9]+\.[0-9]+' | head -1)
    if [[ -n "$DETECTED_CUDA" ]]; then
        CUDA_VER="$DETECTED_CUDA"
    fi
fi

# Check if torch is installed and has CUDA
TORCH_CUDA_OK=false
if python3 -c "import torch" &>/dev/null; then
    TORCH_VER=$(python3 -c "import torch; print(torch.__version__)")
    CUDA_AVAIL=$(python3 -c "import torch; print(torch.cuda.is_available())")
    if [[ "$CUDA_AVAIL" == "True" ]]; then
        write_ok "PyTorch $TORCH_VER installed with CUDA support."
        TORCH_CUDA_OK=true
    else
        write_warn "PyTorch $TORCH_VER installed but CUDA is NOT available."
        write_info "Installing PyTorch with CUDA support..."
    fi
else
    write_info "PyTorch is not installed. Installing now..."
fi

# Install PyTorch (if not already OK with CUDA)
if [[ "$TORCH_CUDA_OK" != "true" ]]; then
    # Install based on detected CUDA version
    case "$CUDA_VER" in
        12.*)
            pip install --upgrade torch torchvision torchaudio \
                --index-url https://download.pytorch.org/whl/cu121 \
                --extra-index-url https://pypi.org/simple -q
            ;;
        11.*)
            pip install --upgrade torch torchvision torchaudio \
                --index-url https://download.pytorch.org/whl/cu118 \
                --extra-index-url https://pypi.org/simple -q
            ;;
        *)
            write_warn "Could not detect CUDA version. Installing CPU-only PyTorch."
            write_info "To use GPU, install CUDA toolkit first, then re-run this wizard."
            pip install --upgrade torch torchvision torchaudio \
                --index-url https://download.pytorch.org/whl/cpu \
                --extra-index-url https://pypi.org/simple -q
            ;;
    esac

    # Re-check
    if python3 -c "import torch" &>/dev/null; then
        CUDA_AVAIL=$(python3 -c "import torch; print(torch.cuda.is_available())")
        if [[ "$CUDA_AVAIL" == "True" ]]; then
            TORCH_VER=$(python3 -c "import torch; print(torch.__version__)")
            write_ok "PyTorch $TORCH_VER installed with CUDA support."
            TORCH_CUDA_OK=true
        else
            TORCH_VER=$(python3 -c "import torch; print(torch.__version__)")
            write_ok "PyTorch $TORCH_VER installed (CPU-only)."
            write_info "To use GPU, install NVIDIA drivers and CUDA toolkit, then re-run."
        fi
    else
        write_err "PyTorch installation failed. Check pip output above."
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Virtual Audio (PulseAudio null-sink / PipeWire)
# ─────────────────────────────────────────────────────────────────────────────

write_step 4 "Virtual Audio (PulseAudio null-sink / PipeWire)"

# Check if PulseAudio or PipeWire is available
PULSE_OK=false
PIPEWIRE_OK=false
VIRT_AUDIO_OK=false

if command -v pactl &>/dev/null; then
    # Check for a null-sink (virtual cable equivalent)
    if pactl list sinks short 2>/dev/null | grep -qi "null\|virtual\|scrum"; then
        PULSE_OK=true
        VIRT_AUDIO_OK=true
        write_ok "PulseAudio null-sink detected."
    fi
fi

if command -v pw-cli &>/dev/null || command -v pipewire &>/dev/null; then
    PIPEWIRE_OK=true
    # Check for a virtual sink
    if pw-cli list-objects 2>/dev/null | grep -qi "null\|virtual\|scrum"; then
        VIRT_AUDIO_OK=true
        write_ok "PipeWire virtual sink detected."
    fi
fi

if [[ "$VIRT_AUDIO_OK" == "true" ]]; then
    write_ok "Virtual audio is configured."
else
    write_warn "No virtual audio device detected."
    write_info "ScrumSurvivor needs a virtual audio loopback device."

    if [[ "$PIPEWIRE_OK" == "true" ]]; then
        write_info "PipeWire detected. Creating a virtual sink..."
        write_info "Run the following to create a virtual sink:"
        write_info "  pactl load-module module-null-sink sink_name=scrum_cable sink_properties=device.description='ScrumSurvivor_Virtual_Cable'"
        write_info "To make it persistent, add to ~/.config/pipewire/pipewire.conf.d/99-scrumsurvivor.conf"
    elif [[ "$PULSE_OK" == "true" ]]; then
        write_info "PulseAudio detected. Creating a null-sink..."
        write_info "Run the following to create a virtual cable:"
        write_info "  pactl load-module module-null-sink sink_name=scrum_cable sink_properties=device.description='ScrumSurvivor_Virtual_Cable'"
        write_info "To make it persistent, add to ~/.config/pulse/default.pa:"
        write_info "  load-module module-null-sink sink_name=scrum_cable sink_properties=device.description='ScrumSurvivor_Virtual_Cable'"
    else
        write_warn "Neither PulseAudio nor PipeWire detected."
        write_info "Install PulseAudio or PipeWire first:"
        write_info "  sudo apt install pulseaudio  (Debian/Ubuntu)"
        write_info "  sudo dnf install pulseaudio  (Fedora)"
    fi

    ask_yes_no "Create the virtual audio sink now?"
    if [[ "$_ASK_RESULT" == "true" ]]; then
        if command -v pactl &>/dev/null; then
            pactl load-module module-null-sink \
                sink_name=scrum_cable \
                sink_properties=device.description='ScrumSurvivor_Virtual_Cable' 2>/dev/null || true
            if pactl list sinks short 2>/dev/null | grep -qi "scrum_cable"; then
                write_ok "Virtual audio sink created."
                VIRT_AUDIO_OK=true
            else
                write_warn "Failed to create virtual audio sink."
                write_info "You may need to restart your audio server:"
                write_info "  pulseaudio -k && pulseaudio --start   (PulseAudio)"
                write_info "  systemctl --user restart pipewire pipewire-pulse   (PipeWire)"
            fi
        else
            write_warn "pactl not found. Cannot create virtual sink automatically."
            write_info "Create it manually:"
            write_info "  pactl load-module module-null-sink sink_name=scrum_cable sink_properties=device.description='ScrumSurvivor_Virtual_Cable'"
        fi
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — v4l2loopback + OBS Virtual Camera
# ─────────────────────────────────────────────────────────────────────────────

write_step 5 "v4l2loopback + OBS Virtual Camera"

OBS_OK=false
V4L2_OK=false

# Check v4l2loopback kernel module
if lsmod 2>/dev/null | grep -q v4l2loopback || modinfo v4l2loopback &>/dev/null; then
    V4L2_OK=true
    write_ok "v4l2loopback kernel module is available."
else
    write_warn "v4l2loopback kernel module not detected."
    write_info "v4l2loopback is required for virtual camera output on Linux."

    ask_yes_no "Install v4l2loopback now? (requires sudo)"
    if [[ "$_ASK_RESULT" == "true" ]]; then
        case "$PKG_CMD" in
            apt-get)
                pkg_install "linux-headers-$(uname -r)"
                pkg_install "v4l2loopback-dkms"
                ;;
            dnf|yum)
                # May need RPM Fusion enabled first
                pkg_install "v4l2loopback"
                ;;
            pacman)
                pkg_install "v4l2loopback-dkms"
                ;;
            *)
                write_info "Install v4l2loopback manually for your distro."
                ;;
        esac
        sudo modprobe v4l2loopback 2>/dev/null || true
        if lsmod 2>/dev/null | grep -q v4l2loopback; then
            V4L2_OK=true
            write_ok "v4l2loopback module loaded."
        else
            write_warn "v4l2loopback module could not be loaded."
            write_info "You may need to install kernel headers or DKMS first."
        fi
    fi
fi

# Check OBS Studio
if command -v obs &>/dev/null || [[ -f "/usr/bin/obs" ]] || dpkg -l obs-studio &>/dev/null 2>&1; then
    OBS_OK=true
    write_ok "OBS Studio is installed."
else
    write_warn "OBS Studio was NOT detected."
    write_info "ScrumSurvivor uses OBS Studio for virtual camera output."
    write_info ""
    write_info "To install:"
    write_info "  sudo apt install obs-studio          (Debian/Ubuntu)"
    write_info "  sudo dnf install obs-studio           (Fedora)"
    write_info "  sudo pacman -S obs-studio             (Arch)"
    write_info "  Or download from https://obsproject.com/"

    ask_yes_no "Open the OBS Studio download page in your browser?"
    if [[ "$_ASK_RESULT" == "true" ]]; then
        if command -v xdg-open &>/dev/null; then
            xdg-open "https://obsproject.com/download" || write_warn "Failed to open browser."
        elif command -v open &>/dev/null; then
            open "https://obsproject.com/download" || write_warn "Failed to open browser."
        else
            write_warn "No browser launcher found. Open https://obsproject.com/download manually."
        fi
    fi

    pause_for_user "After installing OBS Studio, press ENTER to continue..."

    if command -v obs &>/dev/null || [[ -f "/usr/bin/obs" ]]; then
        OBS_OK=true
        write_ok "OBS Studio is now available."
    else
        write_warn "OBS Studio still not detected."
        write_info "Make sure OBS Studio finished installing, then re-run this wizard."
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — ffmpeg
# ─────────────────────────────────────────────────────────────────────────────

write_step 6 "ffmpeg (for Illusion Verifier)"

if command -v ffmpeg &>/dev/null; then
    FFMPEG_VER=$(ffmpeg -version 2>/dev/null | head -1)
    write_ok "ffmpeg found in PATH: $FFMPEG_VER"
else
    write_warn "ffmpeg was NOT found."
    write_info "ffmpeg is required by the Illusion Verifier tool."

    ask_yes_no "Install ffmpeg now? (requires sudo)"
    if [[ "$_ASK_RESULT" == "true" ]]; then
        case "$PKG_CMD" in
            apt-get) pkg_install "ffmpeg" ;;
            dnf|yum) pkg_install "ffmpeg" ;;
            pacman)  pkg_install "ffmpeg" ;;
            zypper)  pkg_install "ffmpeg" ;;
            apk)     pkg_install "ffmpeg" ;;
            *)       write_info "Install ffmpeg manually for your distro." ;;
        esac
        if command -v ffmpeg &>/dev/null; then
            write_ok "ffmpeg installed successfully."
        else
            write_warn "ffmpeg installation may have failed. Install manually."
        fi
    else
        write_info "Skipping ffmpeg installation."
        write_info "Install it later:  sudo apt install ffmpeg  (or your distro's equivalent)"
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Wav2Lip model weights
# ─────────────────────────────────────────────────────────────────────────────

write_step 7 "Wav2Lip Model Weights"

MODELS_DIR="$SCRIPT_DIR/models"
NOGAN_MODEL="$MODELS_DIR/Wav2Lip-SD-NOGAN.pt"
GAN_MODEL="$MODELS_DIR/Wav2Lip-SD-GAN.pt"

NOGAN_OK=false
GAN_OK=false

[[ -f "$NOGAN_MODEL" ]] && NOGAN_OK=true
[[ -f "$GAN_MODEL" ]] && GAN_OK=true

if [[ "$NOGAN_OK" == "true" ]] && [[ "$GAN_OK" == "true" ]]; then
    write_ok "Both Wav2Lip model files found:"
    write_info "  models/Wav2Lip-SD-NOGAN.pt"
    write_info "  models/Wav2Lip-SD-GAN.pt"
else
    if [[ "$NOGAN_OK" == "true" ]]; then
        write_ok "Wav2Lip-SD-NOGAN.pt  ✓ (standard model — used by default)"
    else
        write_warn "Wav2Lip-SD-NOGAN.pt  MISSING  ← required"
    fi
    if [[ "$GAN_OK" == "true" ]]; then
        write_ok "Wav2Lip-SD-GAN.pt    ✓ (GAN variant — optional)"
    else
        write_info "Wav2Lip-SD-GAN.pt    not found  (optional)"
    fi

    if [[ "$NOGAN_OK" == "false" ]]; then
        echo ""
        write_info "The Wav2Lip model weights must be downloaded manually from Google Drive."
        write_info "These are large files (~360 MB each) and are not included in the repository."
        echo ""
        write_info "Download links (from the official Wav2Lip README):"
        write_info "  Wav2Lip (NOGAN, required):"
        write_info "    https://drive.google.com/drive/folders/153HLrqlBNxzZcHi17PEvP09kkAfzRshM?usp=share_link"
        write_info "  Wav2Lip + GAN (optional — higher quality, slower):"
        write_info "    https://drive.google.com/file/d/15G3U08c8xsCkOqQxE38Z2XXDnPcOptNk/view?usp=share_link"
        echo ""
        write_info "After downloading, rename the files to EXACTLY:"
        write_info "  Wav2Lip-SD-NOGAN.pt   (the NOGAN / standard model)"
        write_info "  Wav2Lip-SD-GAN.pt     (the GAN model, optional)"
        echo ""
        write_info "Place the renamed file(s) in:"
        write_info "  $MODELS_DIR/"

        mkdir -p "$MODELS_DIR"

        ask_yes_no "Open the Wav2Lip (NOGAN) Google Drive download page in your browser?"
        if [[ "$_ASK_RESULT" == "true" ]]; then
            URL="https://drive.google.com/drive/folders/153HLrqlBNxzZcHi17PEvP09kkAfzRshM"
            BROWSER_OPENED=false

            for OPENER in xdg-open gnome-open kde-open open; do
                if command -v "$OPENER" &>/dev/null; then
                    nohup "$OPENER" "$URL" </dev/null >/dev/null 2>&1 &
                    BROWSER_OPENED=true
                    write_ok "Opening browser..."
                    break
                fi
            done

            if [[ "$BROWSER_OPENED" != "true" ]]; then
                write_warn "No browser launcher found. Please open the link manually:"
                write_info "  $URL"
            fi
        fi

        pause_for_user "After placing the model file(s) in models/, press ENTER to continue..."

        if [[ -f "$NOGAN_MODEL" ]]; then
            NOGAN_OK=true
            write_ok "Wav2Lip-SD-NOGAN.pt found."
        else
            write_warn "Wav2Lip-SD-NOGAN.pt still not found. ScrumSurvivor will not start without it."
            write_info "Re-run this wizard after placing the file, or copy it in manually."
        fi
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║                  Setup Complete!                         ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Quick status recap
echo -e "  ${GREEN}✓ Python venv${NC}"

if [[ "$VIRT_AUDIO_OK" == "true" ]]; then
    echo -e "  ${GREEN}✓ Virtual audio${NC}"
else
    echo -e "  ${RED}✗ Virtual audio  ← not complete${NC}"
fi

if [[ "$OBS_OK" == "true" ]]; then
    echo -e "  ${GREEN}✓ OBS Virtual Camera${NC}"
else
    echo -e "  ${RED}✗ OBS Virtual Camera  ← not complete${NC}"
fi

if command -v ffmpeg &>/dev/null; then
    echo -e "  ${GREEN}✓ ffmpeg${NC}"
else
    echo -e "  ${RED}✗ ffmpeg  ← not complete${NC}"
fi

if [[ "$NOGAN_OK" == "true" ]]; then
    echo -e "  ${GREEN}✓ Wav2Lip model${NC}"
else
    echo -e "  ${RED}✗ Wav2Lip model  ← not complete${NC}"
fi

echo ""
echo -e "  ${WHITE}Next steps:${NC}"
echo -e "  ${GRAY}1. Capture your avatar photo + idle clips:   ./run_create_assets.sh${NC}"
echo -e "  ${GRAY}2. Configure microphone & audio settings:    ./run_config.sh${NC}"
echo -e "  ${GRAY}3. Start ScrumSurvivor before a meeting:     ./run.sh${NC}"
echo ""
