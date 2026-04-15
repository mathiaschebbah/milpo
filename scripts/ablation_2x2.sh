#!/usr/bin/env bash
# Ablation factorielle 2×2×2 : mode (alma, simple) × tier modèle (flash-lite, flash)
# × dataset (alpha, test). 8 runs complets.
#
# Les runs 118 (alma-alpha-flashlite) et 119 (alma-test-flashlite) sont relancés
# pour cohérence : 2 annotations test corrigées le 2026-04-15 (Jaded London,
# Dockers → post_news_legacy), donc on repart d'une GT propre sur les 8 runs.
#
# Lancés séquentiellement pour éviter le throttling Google AI.

set -uo pipefail

cd "$(dirname "$0")/.."

LOG_DIR="/tmp/ablation_2x2_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"

RUNS=(
  # Alpha
  "--alma   --alpha --model flash-lite"
  "--alma   --alpha --model flash"
  "--simple --alpha --model flash-lite"
  "--simple --alpha --model flash"
  # Test
  "--alma   --test  --model flash-lite"
  "--alma   --test  --model flash"
  "--simple --test  --model flash-lite"
  "--simple --test  --model flash"
)

echo "════════════════════════════════════════════════════════════"
echo "  Ablation 2×2×2  —  8 runs séquentiels"
echo "  logs : $LOG_DIR"
echo "════════════════════════════════════════════════════════════"
echo

total_start=$(date +%s)
idx=0
for args in "${RUNS[@]}"; do
  idx=$((idx + 1))
  slug=$(echo "$args" | tr -s ' ' '_' | sed 's/--//g' | sed 's/^_*//')
  log_file="$LOG_DIR/$(printf '%d' $idx)_${slug}.log"

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
echo "  ✓ Ablation 2×2×2 terminée en ${total_elapsed}s ($((total_elapsed / 60)) min)"
echo "  Résumé des runs et accuracies dans $LOG_DIR"
echo "════════════════════════════════════════════════════════════"

# Résumé rapide des accuracies depuis les logs
echo
echo "  Résumé accuracies :"
for log in "$LOG_DIR"/*.log; do
  name=$(basename "$log" .log)
  # Extrait les 3 accuracies + run_id
  acc=$(grep -E "Accuracy|simulation_run_id" "$log" | tr -d '\r' | tail -4 | tr '\n' ' ')
  echo "    $name :"
  echo "      $acc"
done
