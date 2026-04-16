#!/usr/bin/env bash
# Ablation — test uniquement (8 runs)

set -uo pipefail
cd "$(dirname "$0")/.."

LOG_DIR="/tmp/ablation_test_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"

RUNS=(
  "--alma   --test --model flash-lite"
  "--alma   --test --model flash"
  "--alma   --test --model full-flash"
  "--alma   --test --model qwen"
  "--simple --test --model flash-lite"
  "--simple --test --model flash"
  "--simple --test --model flash-lite --no-assist"
  "--simple --test --model flash --no-assist"
)

echo "════════════════════════════════════════════════════════════"
echo "  Ablation TEST — ${#RUNS[@]} runs séquentiels"
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
echo "  ✓ Ablation TEST terminée en ${total_elapsed}s ($((total_elapsed / 60)) min)"
echo "════════════════════════════════════════════════════════════"

echo
echo "  Résumé :"
for log in "$LOG_DIR"/*.log; do
  name=$(basename "$log" .log)
  acc=$(grep -E "Accuracy|simulation_run_id|Coût" "$log" | tr -d '\r' | tail -5 | tr '\n' ' ')
  echo "    $name : $acc"
done
