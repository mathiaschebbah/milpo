import React, { useState, useEffect, useRef } from "react";
import { Box, Text, useStdout } from "ink";
import type { TelemetryState } from "../types.js";
import { ProgressBar } from "./ProgressBar.js";
import { AccuracyPanel } from "./AccuracyPanel.js";
import { EventLog } from "./EventLog.js";

const StatusIndicator: React.FC<{ state: TelemetryState }> = ({ state }) => {
  const { lastActivitySec, phase, rewriteSubPhase } = state;

  let statusColor: string;
  let statusText: string;
  if (lastActivitySec < 10) {
    statusColor = "green";
    statusText = "active";
  } else if (lastActivitySec < 30) {
    statusColor = "yellow";
    statusText = `idle ${lastActivitySec}s`;
  } else {
    statusColor = "red";
    statusText = `IDLE ${lastActivitySec}s`;
  }

  return (
    <Box flexDirection="column">
      <Text>
        {" "}v{state.maxPromptVersion}{"    "}
        err={state.errorBufferSize}/{state.batchSize}{"    "}
        <Text color={statusColor} bold>{statusText}</Text>
        {state.rewritesPromoted > 0 && <Text color="green">{"    "}promoted={state.rewritesPromoted}</Text>}
        {state.rewritesRollback > 0 && <Text color="red">{"    "}rollback={state.rewritesRollback}</Text>}
        {state.skipped > 0 && <Text color="yellow">{"    "}skipped={state.skipped}</Text>}
      </Text>
      {phase !== "classification" && (
        <Text>
          {" "}<Text color="cyan" bold>{phase}</Text>
          {rewriteSubPhase && <Text dimColor>{"  \u2514\u2500 "}{rewriteSubPhase}</Text>}
        </Text>
      )}
    </Box>
  );
};

export const Dashboard: React.FC<{ state: TelemetryState; done: boolean; exitCode?: number | null }> = ({ state, done, exitCode }) => {
  const completed = done && state.cursor >= state.total;
  const failed = done && !completed;
  const { stdout } = useStdout();
  const [termRows, setTermRows] = useState(stdout.rows ?? 24);
  const [, setTick] = useState(0);
  const stateReceivedAt = useRef(Date.now());
  const prevState = useRef(state);

  // Track terminal resize
  useEffect(() => {
    const onResize = () => setTermRows(stdout.rows ?? 24);
    stdout.on("resize", onResize);
    return () => { stdout.off("resize", onResize); };
  }, [stdout]);

  // Track when state changes
  if (prevState.current !== state) {
    stateReceivedAt.current = Date.now();
    prevState.current = state;
  }

  // Tick every second for live clock
  useEffect(() => {
    if (done) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [done]);

  // Locally-interpolated time values
  const sinceLastState = Math.floor((Date.now() - stateReceivedAt.current) / 1000);
  const localState: TelemetryState = {
    ...state,
    elapsedSec: state.elapsedSec + sinceLastState,
    lastActivitySec: state.lastActivitySec + sinceLastState,
    etaSec: state.etaSec !== null ? Math.max(0, state.etaSec - sinceLastState) : null,
  };

  const borderColor = failed ? "red" : done ? "green" : "blue";
  const title = failed
    ? ` MILPO Simulation \u2014 run #${localState.runId} \u2014 CRASHED (${localState.cursor}/${localState.total})`
    : done
      ? ` MILPO Simulation \u2014 run #${localState.runId} \u2014 DONE`
      : ` MILPO Simulation \u2014 run #${localState.runId}`;

  // Fixed header = ~9 lines (progress 2 + separator 1 + accuracy 4 + status 2 + separator 1)
  // Border top/bottom = 2 lines, title = 1 line, flags = 0-1 line, blank = 1 line
  // Total overhead ~14-15 lines
  const hasFlags = localState.flags && localState.flags.length > 0;
  const headerOverhead = hasFlags ? 15 : 14;
  const eventsHeight = Math.max(4, termRows - headerOverhead);

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={borderColor}
      paddingX={1}
      height={termRows}
    >
      <Text bold color={borderColor}>{title}</Text>
      {localState.flags && localState.flags.length > 0 && (
        <Text color="magenta" bold>{" "}{localState.flags.join("  ")}</Text>
      )}
      <Text>{""}</Text>
      <ProgressBar state={localState} />
      <Text dimColor>{" "}{"\u2500".repeat(52)}</Text>
      <AccuracyPanel state={localState} />
      <StatusIndicator state={localState} />
      <Text dimColor>{" "}{"\u2500".repeat(52)}</Text>
      <EventLog events={localState.events} maxLines={eventsHeight} />
    </Box>
  );
};
