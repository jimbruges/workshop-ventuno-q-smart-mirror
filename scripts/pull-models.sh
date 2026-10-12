#!/usr/bin/env bash
#
# Pull the two VLM models off one prepared board onto this computer, so the other
# boards can be filled from here instead of each downloading ~11 GB themselves.
#
#   ./scripts/pull-models.sh [adb-serial]
#
# The models land in $VLM_MODELS_DIR (default ~/arduino-workshop-models). Keep
# that directory OUTSIDE the app folder — App Lab syncs the app folder to the
# board, and you do not want 11 GB of model files going along for the ride.

set -euo pipefail

MODELS=(
  qwen3_vl_4b_instruct-genie-w4a16-qualcomm_qcs8275
  qwen2_5_vl_7b_instruct-genie-w4a16-qualcomm_qcs8275
)
REMOTE_MODELS=/var/lib/arduino-app-cli/models/genai
LOCAL_MODELS="${VLM_MODELS_DIR:-$HOME/arduino-workshop-models}"

serial="${1:-}"
if [ -z "$serial" ]; then
  serial=$(adb devices | awk '$2 == "device" { print $1 }')
  if [ "$(printf '%s\n' "$serial" | grep -c .)" != "1" ]; then
    echo "Expected exactly one board. Pass a serial instead: $0 <adb-serial>" >&2
    echo "Connected:" >&2
    adb devices >&2
    exit 1
  fi
fi

echo "Pulling models from $serial into $LOCAL_MODELS"
echo "That is about 11 GB over USB, so expect it to take a while."
mkdir -p "$LOCAL_MODELS"

for model in "${MODELS[@]}"; do
  if [ -d "$LOCAL_MODELS/$model" ]; then
    echo "  $model is already here, skipping"
    continue
  fi

  echo "  pulling $model"
  # Pull into a .part directory first, so an interrupted transfer is not mistaken
  # for a finished one the next time this script runs.
  rm -rf "$LOCAL_MODELS/.$model.part"
  adb -s "$serial" pull "$REMOTE_MODELS/$model" "$LOCAL_MODELS/.$model.part"
  mv "$LOCAL_MODELS/.$model.part" "$LOCAL_MODELS/$model"
done

echo "Done. Now run ./scripts/provision.sh to copy them to the other boards."
