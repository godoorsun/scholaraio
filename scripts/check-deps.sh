#!/usr/bin/env bash
# ScholarAIO plugin dependency check — runs on SessionStart (startup only)
#
# Goal: after /plugin install, the very first session should "just work".
# This script handles: pip install → global config → directories.
# It NEVER exits non-zero (must not block session startup).

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

if [ -z "$HOME" ]; then
    exit 0
fi

GLOBAL_DIR="$HOME/.scholaraio"
GLOBAL_CFG="$GLOBAL_DIR/config.yaml"

# ---------- helper: find a working pip ----------
find_pip() {
    if command -v pip3 >/dev/null 2>&1; then echo "pip3"; return; fi
    if command -v pip >/dev/null 2>&1; then echo "pip"; return; fi
    if python3 -m pip --version >/dev/null 2>&1; then echo "python3 -m pip"; return; fi
    if python -m pip --version >/dev/null 2>&1; then echo "python -m pip"; return; fi
    echo ""
}

# ================================================================
#  1. Check if scholaraio CLI is already on PATH
# ================================================================

if command -v scholaraio >/dev/null 2>&1; then
    # Already installed — ensure global config exists
    if [ ! -f "$GLOBAL_CFG" ]; then
        mkdir -p "$GLOBAL_DIR"
        if [ -f "$PLUGIN_ROOT/config.yaml" ]; then
            cp "$PLUGIN_ROOT/config.yaml" "$GLOBAL_CFG"
        fi
    fi
    # Ensure data directories exist (may be missing after config-only setup)
    scholaraio setup check --lang en >/dev/null 2>&1 || true
    exit 0
fi

# ================================================================
#  2. Not installed — set up from scratch
# ================================================================

echo ""
echo "[ScholarAIO] First-time setup..."

PIP=$(find_pip)
if [ -z "$PIP" ]; then
    echo "[ScholarAIO] ERROR: pip not found."
    echo "  Install Python 3.10+ with pip, then run:"
    echo "    pip install git+https://github.com/ZimoLiao/scholaraio.git"
    echo ""
    exit 0
fi

# 2a. Install the Python package (core only — fast, <30s)
# Use --user when not inside a virtualenv to avoid permission errors
USER_FLAG=""
if [ -z "$VIRTUAL_ENV" ] && [ -z "$CONDA_PREFIX" ]; then
    USER_FLAG="--user"
fi

echo "[ScholarAIO] Installing scholaraio..."
if [ -f "$PLUGIN_ROOT/pyproject.toml" ]; then
    $PIP install $USER_FLAG "$PLUGIN_ROOT" 2>&1 | tail -3 || true
else
    echo "[ScholarAIO] WARNING: installing from unpinned GitHub source"
    $PIP install $USER_FLAG "git+https://github.com/ZimoLiao/scholaraio.git" 2>&1 | tail -3 || true
fi

if ! command -v scholaraio >/dev/null 2>&1; then
    # --user install may put binary in ~/.local/bin which is not on PATH
    USER_BIN="${HOME}/.local/bin"
    if [ -x "$USER_BIN/scholaraio" ]; then
        export PATH="$USER_BIN:$PATH"
    fi
fi

if ! command -v scholaraio >/dev/null 2>&1; then
    echo ""
    echo "[ScholarAIO] Auto-install failed. Please install manually:"
    echo "  $PIP install git+https://github.com/ZimoLiao/scholaraio.git"
    echo "  After installing, run: scholaraio setup"
    if [ -n "$USER_FLAG" ]; then
        echo "  (You may need to add ~/.local/bin to your PATH)"
    fi
    echo ""
    exit 0
fi

# 2b. Create global config at ~/.scholaraio/config.yaml
mkdir -p "$GLOBAL_DIR"
if [ ! -f "$GLOBAL_CFG" ]; then
    if [ -f "$PLUGIN_ROOT/config.yaml" ]; then
        cp "$PLUGIN_ROOT/config.yaml" "$GLOBAL_CFG"
        echo "[ScholarAIO] Created config at $GLOBAL_CFG"
    fi
fi

# 2c. Create data directories
scholaraio setup check --lang en >/dev/null 2>&1 || true

echo ""
echo "[ScholarAIO] Installed successfully!"
echo ""
echo "  Your config:  $GLOBAL_CFG"
echo "  Your data:    $GLOBAL_DIR/data/papers/"
echo ""
echo "  Optional extras (install when needed):"
echo "    $PIP install 'scholaraio[embed]'    # semantic search (~1.2GB model)"
echo "    $PIP install 'scholaraio[topics]'   # topic modeling"
echo "    $PIP install 'scholaraio[full]'     # everything"
echo ""
echo "  To configure API keys, tell Claude:  /scholaraio:setup"
echo ""

exit 0
