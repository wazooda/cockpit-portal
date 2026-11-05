#!/bin/bash
# Turn the passthrough portal on or off, and confirm it from the compositor layer's log.
#   portal.sh build --centers x,y,x,y --radius R [--soft S]   prebuild, does not apply
#   portal.sh on | off | toggle | status
#   portal.sh check                                           exit 0 if this SteamVR's shader can be patched
# Prints one line: "<requested> confirmed|unconfirmed|FAILED <detail> (<ms> ms)".
# Exit: 0 confirmed, 3 unconfirmed (no stream to confirm against), 1 failed.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SHADER=distort_ps_achromatic_se2.spv
STOCK=/opt/steamvr/resources/shaders/vulkan/$SHADER
STATE="$HOME/.local/share/mrchroma"
CONF="$HOME/.config/mrchroma/mrchroma.conf"
ACTIVE="$STATE/active_se2.spv"
BUILT="$HERE/portal.spv"
VRBIN=/opt/steamvr/bin/linuxarm64
CONFIRM_SECONDS=6

is_on() { grep -q "^override = $SHADER " "$CONF"; }
ms_now() { date +%s%3N; }

# The layer notices config changes by whole-second mtime. Only a change in the same second
# as the previous one would be missed, so wait only then. $1 is the mtime before this edit.
touch_conf() {
  while [ "$(date +%s)" -le "$1" ]; do sleep 0.02; done
  touch "$CONF"
}

set_state() {
  local want="$1" start log before rc pid line prior
  start=$(ms_now)
  prior=$(stat -c %Y "$CONF")
  pid=$(pgrep -o vrcompositor) || { echo "$want FAILED vrcompositor not running"; return 1; }
  log="/tmp/mrchroma-$pid.log"
  before=$(wc -l < "$log" 2>/dev/null || echo 0)

  if [ "$want" = on ]; then
    [ -f "$BUILT" ] || { echo "on FAILED no portal built"; return 1; }
    # An override is matched by filename, so never apply it to a different stock shader.
    if [ "$(sha256sum "$STOCK" | cut -d' ' -f1)" != "$(cat "$BUILT.stocksha")" ]; then
      echo "on FAILED stock shader changed, rebuild after checking the patch"
      return 1
    fi
    cp "$BUILT" "$ACTIVE.new" && mv "$ACTIVE.new" "$ACTIVE"
    is_on || echo "override = $SHADER $ACTIVE" >> "$CONF"
  else
    sed -i "/^override = $SHADER /d" "$CONF"
  fi
  touch_conf "$prior"

  LD_LIBRARY_PATH=$VRBIN timeout 10 "$VRBIN/vrcmd" --reload-shaders >/dev/null 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "$want FAILED reload exit $rc"
    return 1
  fi

  # Each reload recreates the module; the log line says which one the compositor got.
  for _ in $(seq 1 $((CONFIRM_SECONDS * 10))); do
    line=$(tail -n +"$((before + 1))" "$log" 2>/dev/null | grep "$SHADER (" | tail -1)
    if [ -n "$line" ]; then
      if [[ "$line" == *OVERRIDDEN* ]]; then got=on; else got=off; fi
      if [ "$got" = "$want" ]; then
        echo "$want confirmed ($(( $(ms_now) - start )) ms)"
        return 0
      fi
      echo "$want FAILED compositor loaded $got"
      return 1
    fi
    sleep 0.1
  done
  echo "$want unconfirmed no scene shader rebuilt, stream may be down"
  return 3
}

cmd="${1:-status}"; shift || true
case "$cmd" in
  check)
    python3 -I "$HERE/gen_circle_spv.py" --check "$STOCK"
    ;;
  build)
    python3 -I "$HERE/gen_circle_spv.py" "$STOCK" "$BUILT.new" "$@" || exit 1
    mv "$BUILT.new" "$BUILT"
    sha256sum "$STOCK" | cut -d' ' -f1 > "$BUILT.stocksha"
    echo "$*" > "$BUILT.params"
    echo "built $*"
    ;;
  status)
    if is_on; then echo "on"; else echo "off"; fi
    ;;
  on|off|toggle)
    exec 9>"/tmp/cockpit-portal.lock"
    flock -w 15 9 || { echo "$cmd FAILED busy"; exit 1; }
    if [ "$cmd" = toggle ]; then
      if is_on; then cmd=off; else cmd=on; fi
    fi
    set_state "$cmd"
    exit $?
    ;;
  *)
    sed -n '2,5p' "$0"
    exit 2
    ;;
esac
