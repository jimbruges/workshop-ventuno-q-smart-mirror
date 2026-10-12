#!/usr/bin/env bash
#
# Copy the models fetched by pull-models.sh, plus this app, onto every board that
# is currently connected over ADB.
#
#   ./scripts/provision.sh
#
# Models already present on a board are skipped, so re-running this is cheap.
# The app directory on each board is REPLACED, so do not point this at a board
# whose copy of the app has changes you want to keep.

set -euo pipefail

MODELS=(
  qwen3_vl_4b_instruct-genie-w4a16-qualcomm_qcs8275
  qwen2_5_vl_7b_instruct-genie-w4a16-qualcomm_qcs8275
)
REMOTE_MODELS=/var/lib/arduino-app-cli/models/genai
REMOTE_APPS=/home/arduino/ArduinoApps
APP_NAME=ai-smart-mirror

# Everything the app needs, listed explicitly so the .cache directory (the venv
# and build output) never gets pushed.
APP_PARTS=(app.yaml README.md python assets sketch scripts)

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_MODELS="${VLM_MODELS_DIR:-$HOME/arduino-workshop-models}"

devices=$(adb devices | awk '$2 == "device" { print $1 }')
if [ -z "$devices" ]; then
  echo "No boards connected over ADB." >&2
  exit 1
fi

echo "Boards to provision:"
printf '  %s\n' $devices
echo

for serial in $devices; do
  echo "=== $serial ==="

  for model in "${MODELS[@]}"; do
    if [ ! -d "$LOCAL_MODELS/$model" ]; then
      echo "  $model is not in $LOCAL_MODELS — run ./scripts/pull-models.sh first" >&2
      continue
    fi

    present=$(adb -s "$serial" shell "test -d $REMOTE_MODELS/$model && echo yes" | tr -d '\r\n')
    if [ "$present" = "yes" ]; then
      echo "  $model already on this board, skipping"
      continue
    fi

    echo "  pushing $model (this is the slow part)"
    adb -s "$serial" shell "mkdir -p $REMOTE_MODELS"
    adb -s "$serial" push "$LOCAL_MODELS/$model" "$REMOTE_MODELS/$model"
  done

  echo "  pushing $APP_NAME"
  adb -s "$serial" shell "rm -rf ${REMOTE_APPS:?}/${APP_NAME:?} && mkdir -p $REMOTE_APPS/$APP_NAME"
  for part in "${APP_PARTS[@]}"; do
    if [ -e "$APP_ROOT/$part" ]; then
      adb -s "$serial" push "$APP_ROOT/$part" "$REMOTE_APPS/$APP_NAME/$part"
    fi
  done

  echo "  done"
done

echo
echo "Restart Arduino App Lab on each board so it picks up the new models and app."
