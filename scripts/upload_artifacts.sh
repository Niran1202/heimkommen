#!/usr/bin/env bash
# Copy the small deployable artifacts (model, evaluation, station map) to the VM.
# The timetable is imported on the server itself (scripts/bootstrap_server.sh).
#   scripts/upload_artifacts.sh user@host
set -euo pipefail
target="${1:?usage: upload_artifacts.sh user@host}"
cd "$(dirname "$0")/.."
version="$(python -c "import json; print(json.load(open('ml/artifacts/current.json'))['version'])")"
rsync -avz --relative "ml/artifacts/current.json" "ml/artifacts/delay_model_${version}/" \
  "ml/artifacts/evaluation.json" "ml/artifacts/station_map.csv" "$target:~/heimkommen/"
echo "uploaded delay model ${version}"
