"""TUI Rich Live pour la simulation MILPO."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from rich.panel import Panel


@dataclass
class DisplayEvent:
    """Événement structuré pour l'affichage TUI."""

    ts: str
    msg: str
    type: str = "event"  # "event" | "api" | "error"


class SimulationDisplay:
    """Panneau Rich Live mis à jour en place pendant la simulation."""

    def __init__(self, run_id: int, total: int, batch_size: int, flags: list[str] | None = None):
        self.run_id = run_id
        self.total = total
        self.batch_size = batch_size
        self.flags = flags or []
        self.events: deque[DisplayEvent] = deque(maxlen=200)
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

        # Heartbeat : dernière activité
        self.last_activity = time.monotonic()
        self.last_activity_label = "init"

        # Accuracy FEED/REELS
        self.matches_by_scope: dict[str, dict[str, int]] = {
            "FEED": {"category": 0, "visual_format": 0, "strategy": 0},
            "REELS": {"category": 0, "visual_format": 0, "strategy": 0},
        }
        self.n_by_scope: dict[str, int] = {"FEED": 0, "REELS": 0}

    def heartbeat(self, label: str = ""):
        self.last_activity = time.monotonic()
        if label:
            self.last_activity_label = label

    def add_event(self, msg: str, event_type: str = "event"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.events.appendleft(DisplayEvent(ts=ts, msg=msg, type=event_type))
        self.heartbeat(msg[:30])

    @staticmethod
    def _fmt_tok(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)

    def add_api_log(
        self,
        agent: str,
        model: str,
        latency_ms: int,
        in_tok: int,
        out_tok: int,
        status: str,
    ):
        """Ajoute un log d'appel API formaté au flux d'événements."""
        status_icon = "\u2713" if status == "ok" else "ERR" if status == "error" else "\u21bb"
        short_model = model.split("/")[-1] if "/" in model else model
        if len(short_model) > 20:
            short_model = short_model[:20]
        msg = (
            f"{agent:<12s} {short_model:<20s} "
            f"{latency_ms:>5d}ms  "
            f"{self._fmt_tok(in_tok)}\u2192{self._fmt_tok(out_tok)}  "
            f"{status_icon}"
        )
        self.add_event(msg, event_type="api")

    def set_rewrite_phase(self, sub_phase: str | None):
        self.rewrite_sub_phase = sub_phase

    def build(self) -> Panel:
        elapsed = time.monotonic() - self.t0
        rate = self.n_processed / elapsed if elapsed > 0 else 0
        eta = (self.total - self.cursor) / rate if rate > 0 else None
        pct = self.cursor * 100 // self.total if self.total else 0
        filled = self.cursor * 20 // self.total if self.total else 0
        bar = "\u2588" * filled + "\u2591" * (20 - filled)

        n = self.n_processed or 1
        acc_cat = self.matches_by_axis["category"] / n * 100
        acc_vf = self.matches_by_axis["visual_format"] / n * 100
        acc_str = self.matches_by_axis["strategy"] / n * 100

        max_v = max(self.prompt_versions.values()) if self.prompt_versions else 0

        if eta is not None:
            eta_min, eta_sec = divmod(int(eta), 60)
            eta_str = f"{eta_min}min {eta_sec}s" if eta_min else f"{eta_sec}s"
        else:
            eta_str = "..."
        elapsed_min, elapsed_sec = divmod(int(elapsed), 60)
        elapsed_str = f"{elapsed_min}min {elapsed_sec}s" if elapsed_min else f"{elapsed_sec}s"

        lines = []
        if self.flags:
            lines.append(f" [bold magenta]{' '.join(self.flags)}[/bold magenta]")
        lines.append(f" {bar}  {self.cursor}/{self.total} ({pct}%)  {rate:.1f}p/s")
        lines.append(f" Elapsed {elapsed_str}    ETA {eta_str}    cost ~${self.cost:.2f}")

        def _fmt_tok(n: int) -> str:
            return f"{n / 1_000_000:.1f}M" if n >= 1_000_000 else f"{n / 1_000:.0f}K"

        lines.append(
            f" Tokens  {_fmt_tok(self.total_input_tokens)} in / "
            f"{_fmt_tok(self.total_output_tokens)} out"
        )
        lines.append("\u2500" * 52)
        loss_cat = 100 - acc_cat
        loss_vf = 100 - acc_vf
        loss_str = 100 - acc_str
        lines.append(f" Loss       cat={loss_cat:.1f}%  vf={loss_vf:.1f}%  str={loss_str:.1f}%")
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
        # Heartbeat : temps depuis dernière activité
        idle = time.monotonic() - self.last_activity
        if idle > 30:
            idle_str = f"[bold red]IDLE {int(idle)}s[/bold red] ({self.last_activity_label})"
        elif idle > 10:
            idle_str = f"[yellow]idle {int(idle)}s[/yellow]"
        else:
            idle_str = f"[green]active[/green]"

        lines.append(f" Prompts    v{max_v}    Buffer err={self.error_count}/{self.batch_size}    {idle_str}")
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
                lines.append(f" {ev.ts}  {ev.msg}")

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

    def to_json(self) -> dict:
        """Sérialise l'état complet pour la TUI TypeScript (WebSocket)."""
        elapsed = time.monotonic() - self.t0
        rate = self.n_processed / elapsed if elapsed > 0 else 0
        eta = (self.total - self.cursor) / rate if rate > 0 else None
        n = self.n_processed or 1
        return {
            "runId": self.run_id,
            "flags": self.flags,
            "cursor": self.cursor,
            "total": self.total,
            "nProcessed": self.n_processed,
            "rate": round(rate, 2),
            "elapsedSec": round(elapsed),
            "etaSec": round(eta) if eta is not None else None,
            "accuracy": {
                "category": round(self.matches_by_axis["category"] / n * 100, 1),
                "visualFormat": round(self.matches_by_axis["visual_format"] / n * 100, 1),
                "strategy": round(self.matches_by_axis["strategy"] / n * 100, 1),
            },
            "loss": {
                "category": round(100 - self.matches_by_axis["category"] / n * 100, 1),
                "visualFormat": round(100 - self.matches_by_axis["visual_format"] / n * 100, 1),
                "strategy": round(100 - self.matches_by_axis["strategy"] / n * 100, 1),
            },
            "rolling50": self.rolling_acc if self.rolling_acc else None,
            "byScope": {
                scope: {
                    "n": self.n_by_scope.get(scope, 0),
                    "category": self.matches_by_scope[scope]["category"],
                    "visualFormat": self.matches_by_scope[scope]["visual_format"],
                    "strategy": self.matches_by_scope[scope]["strategy"],
                } for scope in ("FEED", "REELS")
            },
            "costUsd": round(self.cost, 3),
            "inputTokens": self.total_input_tokens,
            "outputTokens": self.total_output_tokens,
            "maxPromptVersion": max(self.prompt_versions.values()) if self.prompt_versions else 0,
            "errorBufferSize": self.error_count,
            "batchSize": self.batch_size,
            "skipped": self.skipped,
            "phase": self.phase,
            "rewriteSubPhase": self.rewrite_sub_phase,
            "rewritesPromoted": self.rewrites_promoted,
            "rewritesRollback": self.rewrites_rollback,
            "lastActivitySec": round(time.monotonic() - self.last_activity),
            "lastActivityLabel": self.last_activity_label,
            "events": [{"ts": e.ts, "msg": e.msg, "type": e.type} for e in list(self.events)],
        }
