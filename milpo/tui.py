"""TUI Rich Live pour la simulation MILPO."""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime

from rich.panel import Panel


class SimulationDisplay:
    """Panneau Rich Live mis à jour en place pendant la simulation."""

    def __init__(self, run_id: int, total: int, batch_size: int):
        self.run_id = run_id
        self.total = total
        self.batch_size = batch_size
        self.events: deque[str] = deque(maxlen=8)
        self.t0 = time.monotonic()
        self.cursor = 0
        self.n_processed = 0
        self.matches_by_axis = {"category": 0, "visual_format": 0, "strategy": 0}
        self.error_count = 0
        self.cost = 0.0
        self.prompt_versions: dict = {}
        self.rolling_acc: dict[str, float] = {}
        self.phase = "classification"
        self.skipped = 0
        self.rewrites_promoted = 0
        self.rewrites_rollback = 0

        # Télémétrie rewrite (sous-phase)
        self.rewrite_sub_phase: str | None = None

        # Tokens cumulés
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

        # Accuracy FEED/REELS
        self.matches_by_scope: dict[str, dict[str, int]] = {
            "FEED": {"category": 0, "visual_format": 0, "strategy": 0},
            "REELS": {"category": 0, "visual_format": 0, "strategy": 0},
        }
        self.n_by_scope: dict[str, int] = {"FEED": 0, "REELS": 0}

    def add_event(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.events.appendleft(f"{ts}  {msg}")

    def set_rewrite_phase(self, sub_phase: str | None):
        self.rewrite_sub_phase = sub_phase

    def build(self) -> Panel:
        elapsed = time.monotonic() - self.t0
        rate = self.n_processed / elapsed if elapsed > 0 else 0
        eta = (self.total - self.cursor) / rate if rate > 0 else 0
        pct = self.cursor * 100 // self.total if self.total else 0
        filled = self.cursor * 20 // self.total if self.total else 0
        bar = "\u2588" * filled + "\u2591" * (20 - filled)

        n = self.n_processed or 1
        acc_cat = self.matches_by_axis["category"] / n * 100
        acc_vf = self.matches_by_axis["visual_format"] / n * 100
        acc_str = self.matches_by_axis["strategy"] / n * 100

        max_v = max(self.prompt_versions.values()) if self.prompt_versions else 0

        eta_min, eta_sec = divmod(int(eta), 60)
        eta_str = f"{eta_min}min {eta_sec}s" if eta_min else f"{eta_sec}s"
        elapsed_min, elapsed_sec = divmod(int(elapsed), 60)
        elapsed_str = f"{elapsed_min}min {elapsed_sec}s" if elapsed_min else f"{elapsed_sec}s"

        lines = []
        lines.append(f" {bar}  {self.cursor}/{self.total} ({pct}%)  {rate:.1f}p/s")
        lines.append(f" Elapsed {elapsed_str}    ETA {eta_str}    cost ~${self.cost:.2f}")

        def _fmt_tok(n: int) -> str:
            return f"{n / 1_000_000:.1f}M" if n >= 1_000_000 else f"{n / 1_000:.0f}K"

        lines.append(
            f" Tokens  {_fmt_tok(self.total_input_tokens)} in / "
            f"{_fmt_tok(self.total_output_tokens)} out"
        )
        lines.append("\u2500" * 52)
        lines.append(f" Accuracy   cat={acc_cat:.1f}%  vf={acc_vf:.1f}%  str={acc_str:.1f}%")
        if self.rolling_acc:
            r = self.rolling_acc
            lines.append(
                f" Rolling50  cat={r.get('cat', 0):.1f}%  "
                f"vf={r.get('vf', 0):.1f}%  str={r.get('str', 0):.1f}%"
            )
        for scope in ("FEED", "REELS"):
            ns = self.n_by_scope.get(scope, 0)
            if ns > 0:
                ms = self.matches_by_scope[scope]
                lines.append(
                    f" {scope:5s} {ns:>3d}  "
                    f"cat={ms['category'] / ns * 100:.0f}%  "
                    f"vf={ms['visual_format'] / ns * 100:.0f}%  "
                    f"str={ms['strategy'] / ns * 100:.0f}%"
                )
        lines.append(f" Prompts    v{max_v}    Buffer err={self.error_count}/{self.batch_size}")
        if self.phase != "classification":
            lines.append(f" [bold cyan]{self.phase}[/bold cyan]")
            if self.rewrite_sub_phase:
                lines.append(f"   \u2514\u2500 {self.rewrite_sub_phase}")

        stats_parts = []
        if self.rewrites_promoted:
            stats_parts.append(f"promoted={self.rewrites_promoted}")
        if self.rewrites_rollback:
            stats_parts.append(f"rollback={self.rewrites_rollback}")
        if self.skipped:
            stats_parts.append(f"skipped={self.skipped}")
        if stats_parts:
            lines.append(f" Rewrites   {' '.join(stats_parts)}")

        if self.events:
            lines.append("\u2500 Events " + "\u2500" * 43)
            for ev in list(self.events)[:6]:
                lines.append(f" {ev}")

        content = "\n".join(lines)
        return Panel(
            content,
            title=f"MILPO Simulation \u2014 run #{self.run_id}",
            border_style="blue",
        )

    def update_rolling(self, all_matches, window: int = 50):
        if len(all_matches) < window:
            return
        recent = all_matches[-window:]
        by_axis: dict[str, list[bool]] = {
            "category": [], "visual_format": [], "strategy": [],
        }
        for m in recent:
            by_axis[m.axis].append(m.match)
        self.rolling_acc = {}
        for axis, short in [("category", "cat"), ("visual_format", "vf"), ("strategy", "str")]:
            if by_axis[axis]:
                self.rolling_acc[short] = sum(by_axis[axis]) / len(by_axis[axis]) * 100

    def sync(
        self,
        cursor: int,
        n_processed: int,
        matches_by_axis: dict[str, int],
        error_count: int,
        cost: float,
        prompt_versions: dict,
    ):
        """Met à jour l'état depuis la boucle principale."""
        self.cursor = cursor
        self.n_processed = n_processed
        self.matches_by_axis = matches_by_axis
        self.error_count = error_count
        self.cost = cost
        self.prompt_versions = prompt_versions
