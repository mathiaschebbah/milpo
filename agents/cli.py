"""TUI pour le runner agentique — affichage temps réel avec Rich Live."""

from __future__ import annotations

import statistics
import threading
import time
from dataclasses import dataclass, field

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TaskProgressColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text


def _percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def _fmt_tokens(n: float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(int(n))


@dataclass
class TuiStats:
    total: int = 0
    started: int = 0
    completed: int = 0
    errors: int = 0
    in_flight_posts: int = 0
    total_executor_requests: int = 0
    total_executor_input_tokens: int = 0
    total_executor_cache_creation_tokens: int = 0
    total_executor_cache_read_tokens: int = 0
    executor_successes: int = 0
    executor_cache_hits: int = 0
    posts_with_advisor: int = 0
    total_tool_calls: int = 0
    total_advisor_calls: int = 0
    total_api_calls: int = 0
    matches: dict[str, int] = field(
        default_factory=lambda: {"category": 0, "visual_format": 0, "strategy": 0}
    )
    latencies_ms: list[int] = field(default_factory=list)


class TuiRenderer:
    """TUI avec Rich Live. Thread-safe via le lock partagé avec le runner."""

    def __init__(
        self,
        stats: TuiStats,
        lock: threading.Lock,
        limiter_snapshot_fn,
        *,
        run_id: int,
        pipeline: str,
        t0: float,
    ):
        self._stats = stats
        self._lock = lock
        self._limiter_snapshot_fn = limiter_snapshot_fn
        self._run_id = run_id
        self._pipeline = pipeline
        self._t0 = t0
        self._console = Console()
        self._progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40, complete_style="green", finished_style="bright_green"),
            TaskProgressColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
            console=self._console,
            expand=False,
        )
        self._task_id = self._progress.add_task(f"classifying {stats.total} posts", total=stats.total)
        self._live: Live | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._live = Live(
            self._build(),
            console=self._console,
            refresh_per_second=4,
            transient=False,
        )
        self._live.start()
        self._thread = threading.Thread(target=self._update_loop, name="tui-updater", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._live:
            self._live.update(self._build())
            self._live.stop()

    def _update_loop(self) -> None:
        while not self._stop.is_set():
            if self._live:
                self._live.update(self._build())
            self._stop.wait(0.5)

    def _build(self) -> Panel:
        with self._lock:
            s = self._stats
            elapsed_s = max(time.monotonic() - self._t0, 0.01)
            elapsed_min = elapsed_s / 60.0
            completed = s.completed
            errors = s.errors
            in_flight = s.in_flight_posts
            ok = max(1, completed)
            acc_cat = s.matches["category"] / ok * 100 if completed else 0.0
            acc_vf = s.matches["visual_format"] / ok * 100 if completed else 0.0
            acc_str = s.matches["strategy"] / ok * 100 if completed else 0.0
            posts_min = completed / elapsed_min
            tok_min = s.total_executor_input_tokens / elapsed_min
            cache_pct = (s.executor_cache_hits / s.executor_successes * 100) if s.executor_successes else 0.0
            p50 = int(statistics.median(s.latencies_ms)) if s.latencies_ms else 0
            p95 = _percentile(s.latencies_ms, 0.95)
            tool_calls = s.total_tool_calls
            advisor_calls = s.total_advisor_calls

        limiter = self._limiter_snapshot_fn()
        self._progress.update(self._task_id, completed=completed)

        table = Table(show_header=False, box=None, padding=(0, 2), expand=False)
        table.add_column("label", style="dim", min_width=10, no_wrap=True)
        table.add_column("value", no_wrap=True)

        # Accuracy
        def _acc_style(v: float, good: float, ok_: float) -> str:
            if v >= good:
                return "bold green"
            if v >= ok_:
                return "bold yellow"
            return "bold red"

        acc = Text()
        acc.append("cat ", style="dim")
        acc.append(f"{acc_cat:>5.1f}%", style=_acc_style(acc_cat, 80, 60))
        acc.append("   vf ", style="dim")
        acc.append(f"{acc_vf:>5.1f}%", style=_acc_style(acc_vf, 60, 40))
        acc.append("   str ", style="dim")
        acc.append(f"{acc_str:>5.1f}%", style=_acc_style(acc_str, 90, 70))
        table.add_row("accuracy", acc)

        # Throughput
        tp = Text()
        tp.append(f"{posts_min:>4.1f}", style="bold")
        tp.append(" posts/min   ", style="dim")
        tp.append(f"{_fmt_tokens(tok_min)}", style="bold")
        tp.append(" tok/min", style="dim")
        table.add_row("throughput", tp)

        # Latency
        lat = Text()
        lat.append("p50 ", style="dim")
        lat.append(f"{p50:>5}ms", style="cyan")
        lat.append("   p95 ", style="dim")
        lat.append(f"{p95:>5}ms", style="cyan")
        table.add_row("latency", lat)

        # Runtime
        rt = Text()
        rt.append("fly ", style="dim")
        rt.append(f"{in_flight}")
        rt.append("  rl ", style="dim")
        rt.append(f"{int(limiter['waiters'])}")
        rt.append("  tools ", style="dim")
        rt.append(f"{tool_calls}")
        rt.append("  advisor ", style="dim")
        rt.append(f"{advisor_calls}")
        rt.append("  cache ", style="dim")
        rt.append(f"{cache_pct:.0f}%")
        if errors:
            rt.append("  err ", style="dim")
            rt.append(f"{errors}", style="bold red")
        table.add_row("runtime", rt)

        content = Group(self._progress, Text(""), table)
        title = f"[bold]{self._pipeline}[/bold]  run={self._run_id}"
        return Panel(content, title=title, border_style="blue", expand=False)
