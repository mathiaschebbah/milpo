#!/usr/bin/env bash
# Ablation — alpha uniquement (6 runs)

set -uo pipefail
cd "$(dirname "$0")/.."

LOG_DIR="/tmp/ablation_alpha_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"

RUNS=(
  "--alma   --alpha --model flash-lite"
  "--alma   --alpha --model flash"
  "--alma   --alpha --model full-flash"
  "--alma   --alpha --model qwen"
  "--simple --alpha --model flash-lite"
  "--simple --alpha --model flash"
)

echo "════════════════════════════════════════════════════════════"
echo "  Ablation ALPHA — ${#RUNS[@]} runs séquentiels"
echo "  logs : $LOG_DIR"
echo "════════════════════════════════════════════════════════════"
echo

total_start=$(date +%s)
idx=0
for args in "${RUNS[@]}"; do
  idx=$((idx + 1))
  slug=$(echo "$args" | tr -s ' ' '_' | sed 's/--//g' | sed 's/^_*//')
  log_file="$LOG_DIR/$(printf '%02d' $idx)_${slug}.log"

  echo "────────────────────────────────────────────────────────────"
  echo "  [$idx/${#RUNS[@]}]  $(date '+%H:%M:%S')  classification $args"
  echo "  log: $log_file"
  echo "────────────────────────────────────────────────────────────"

  start=$(date +%s)
  if uv run classification $args 2>&1 | tee "$log_file"; then
    elapsed=$(($(date +%s) - start))
    echo "  ✓ terminé en ${elapsed}s"
  else
    elapsed=$(($(date +%s) - start))
    echo "  ✗ ÉCHEC après ${elapsed}s — on continue au suivant"
  fi
  echo
done

total_elapsed=$(($(date +%s) - total_start))
echo "════════════════════════════════════════════════════════════"
echo "  ✓ Ablation ALPHA terminée en ${total_elapsed}s ($((total_elapsed / 60)) min)"
echo "════════════════════════════════════════════════════════════"

echo
echo "  Résumé :"
for log in "$LOG_DIR"/*.log; do
  name=$(basename "$log" .log)
  acc=$(grep -E "Accuracy|simulation_run_id|Coût" "$log" | tr -d '\r' | tail -5 | tr '\n' ' ')
  echo "    $name : $acc"
done
