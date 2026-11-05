#!/bin/bash
# Sets up or removes Cockpit Portal on this headset. The Windows installer runs it, and you can run it by hand.
#   setup.sh install     safe to repeat: anything already in place is left alone
#   setup.sh uninstall   removes what install added
# Everything stays in your home folder, and nothing here needs root.
# Lines starting with @@ are for the installer: STEP name, OK name [note], FAIL name reason, RESTART.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LAYER_REPO=https://github.com/spyjacob/steam-frame-chroma-key
LAYER_COMMIT=535c5f224768f85d7f011fce9e1cf03e0ea802f8
LAYER_SRC="$HERE/mr-chroma"
LAYER_HOME="$HOME/.local/share/mrchroma"
LAYER_FILE="$LAYER_HOME/libVkLayer_mrchroma.so"
LAYER_MANIFEST="$HOME/.local/share/vulkan/implicit_layer.d/mrchroma.json"
MRCTL="$LAYER_HOME/mrctl"
ENABLE="$HOME/.config/mrchroma/enable-compositor"
# Notes of what this script added, so uninstall leaves anything that was already there.
OURS_LAYER="$HERE/.added-layer"
OURS_SETTING="$HERE/.added-setting"
OURS_ENABLE="$HERE/.added-enable"
# The same format slots.py uses, so opening this position first does not rebuild the shader.
FIRST_BUILD=(--centers 754.6,752.5,3563.3,775.7 --radius 228.9 --soft 30.0)

say() { echo "@@ $*"; }
fail() { say FAIL "$1" "$2"; exit 1; }

check_headset() {
  say STEP check
  local tool missing=""
  for tool in git g++ glslc spirv-dis spirv-as spirv-val python3 flock; do
    command -v "$tool" >/dev/null || missing="$missing $tool"
  done
  [ -z "$missing" ] || fail check "This headset is missing:$missing"
  [ -x /opt/steamvr/bin/linuxarm64/vrcmd ] || fail check "SteamVR was not found on this device. Is it a Steam Frame?"
  "$HERE/portal.sh" check || fail check "This SteamVR version is not supported yet, so the layer and setting were not installed. Please check for a newer Cockpit Portal."
  "$HERE/portal.sh" build "${FIRST_BUILD[@]}" || fail check "The shader could not be patched, so the layer and setting were not installed."
  say OK check
}

install_layer() {
  say STEP layer
  if [ -f "$LAYER_FILE" ] && [ -f "$LAYER_MANIFEST" ]; then
    say OK layer "already installed"
    return
  fi
  rm -rf "$LAYER_SRC"
  git clone --quiet "$LAYER_REPO" "$LAYER_SRC" || fail layer "Could not download mr-chroma-frame from GitHub. Is the headset on a network with internet?"
  git -C "$LAYER_SRC" checkout --quiet --detach "$LAYER_COMMIT" || fail layer "The expected version of mr-chroma-frame was not found."
  # Before the first file is installed, so uninstall also cleans up a failed attempt.
  touch "$OURS_LAYER"
  "$LAYER_SRC/build.sh" || fail layer "mr-chroma-frame did not build. The details are in the setup log."
  "$LAYER_SRC/install.sh" || fail layer "mr-chroma-frame did not install. The details are in the setup log."
  say OK layer
}

turn_on_setting() {
  say STEP setting
  local changed=0
  if [ ! -f "$ENABLE" ]; then
    touch "$ENABLE" "$OURS_ENABLE"
    changed=1
  fi
  pgrep -x vrserver >/dev/null || fail setting "SteamVR is not running on the headset. Turn the headset on and try again."
  if ! "$MRCTL" get-bool camera forceSceneAlphaBlending 2>/dev/null | grep -q "= true"; then
    "$MRCTL" set-bool camera forceSceneAlphaBlending 1 || fail setting "SteamVR did not accept the passthrough setting."
    "$MRCTL" get-bool camera forceSceneAlphaBlending | grep -q "= true" || fail setting "The passthrough setting did not stick."
    touch "$OURS_SETTING"
    changed=1
  fi
  say OK setting
  # The compositor writes this log only with the layer loaded, so a missing one means it needs a restart.
  local pid
  pid=$(pgrep -o vrcompositor) || true
  if [ "$changed" = 1 ] || [ -z "$pid" ] || [ ! -f "/tmp/mrchroma-$pid.log" ]; then
    say RESTART
  fi
}

uninstall() {
  "$HERE/portal.sh" off >/dev/null 2>&1
  if [ -f "$OURS_LAYER" ] && [ -x "$LAYER_SRC/uninstall.sh" ]; then
    "$LAYER_SRC/uninstall.sh" --purge
  else
    if [ -f "$OURS_SETTING" ] && pgrep -x vrserver >/dev/null; then
      "$MRCTL" remove camera forceSceneAlphaBlending
    fi
    if [ -f "$OURS_ENABLE" ]; then
      rm -f "$ENABLE"
    fi
  fi
  # In one block because bash reads a script as it runs, and this deletes the script.
  { cd "$HOME" && rm -rf "$HERE"; say OK uninstall; exit 0; }
}

case "${1:-}" in
  install)
    check_headset
    install_layer
    turn_on_setting
    ;;
  uninstall)
    uninstall
    ;;
  *)
    sed -n '2,6p' "$0"
    exit 2
    ;;
esac
