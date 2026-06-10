#!/usr/bin/env bash
# Shared helpers for record.sh and live.sh: enumerate avfoundation audio devices
# and prompt for a device index interactively. Source this; don't execute it.

DEVICES=$(ffmpeg -f avfoundation -list_devices true -i "" 2>&1 || true)
DEVICES=$(echo "$DEVICES" \
  | awk '/AVFoundation audio devices:/{flag=1; next} flag && /\[[0-9]+\]/{print}')

pick_device() {
  local prompt="$1"
  local default_name="$2"
  echo "" >&2
  echo "$prompt" >&2
  echo "$DEVICES" | sed -E 's/.*indev @ [^ ]+\] //' >&2
  local default_idx
  default_idx=$(echo "$DEVICES" | grep -i "$default_name" | head -1 | sed -E 's/.*\[([0-9]+)\].*/\1/' || true)
  local prompt_suffix=""
  [[ -n "$default_idx" ]] && prompt_suffix=" [default: $default_idx]"
  local choice
  read -r -p "Enter device index${prompt_suffix}: " choice
  choice="${choice:-$default_idx}"
  if [[ -z "$choice" ]]; then
    echo "no choice and no default" >&2
    exit 1
  fi
  echo ":$choice"
}
