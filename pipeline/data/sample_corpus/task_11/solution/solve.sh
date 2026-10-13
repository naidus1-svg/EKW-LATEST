#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
OUTPUT_DIR="$WORKSPACE_DIR/output"
SOLUTION_DIR="${SOLUTION_DIR:-/solution}"
GOLDEN_DIR="$SOLUTION_DIR/golden_outputs"

mkdir -p "$OUTPUT_DIR"

if [ ! -d "$GOLDEN_DIR" ]; then
  echo "Missing golden outputs directory: $GOLDEN_DIR" >&2
  exit 1
fi

for required_file in \
  clinical_note.pdf \
  patient_education_summary.pdf \
  output_variables.json
do
  if [ ! -f "$GOLDEN_DIR/$required_file" ]; then
    echo "Missing golden output: $GOLDEN_DIR/$required_file" >&2
    exit 1
  fi
  cp -p "$GOLDEN_DIR/$required_file" "$OUTPUT_DIR/$required_file"
done
