import React from "react";
import { Box, Text } from "ink";
import type { TelemetryState, ScopeAccuracy } from "../types.js";

function pct(correct: number, total: number): string {
  return total > 0 ? `${Math.round((correct / total) * 100)}%` : "-";
}

const ScopeRow: React.FC<{ label: string; s: ScopeAccuracy }> = ({ label, s }) => {
  if (s.n === 0) return null;
  return (
    <Text>
      {" "}<Text bold>{label.padEnd(5)}</Text> {String(s.n).padStart(3)}{"  "}
      cat={pct(s.category, s.n)}{"  "}
      vf={pct(s.visualFormat, s.n)}{"  "}
      str={pct(s.strategy, s.n)}
    </Text>
  );
};

export const AccuracyPanel: React.FC<{ state: TelemetryState }> = ({ state }) => {
  const { accuracy, loss, rolling50, byScope } = state;

  return (
    <Box flexDirection="column">
      <Text>
        {" "}Loss{"       "}
        <Text color="red">cat={loss.category.toFixed(1)}%</Text>{"  "}
        <Text color="red">vf={loss.visualFormat.toFixed(1)}%</Text>{"  "}
        <Text color="red">str={loss.strategy.toFixed(1)}%</Text>
      </Text>
      <Text>
        {" "}Accuracy{"   "}
        <Text color="green">cat={accuracy.category.toFixed(1)}%</Text>{"  "}
        <Text color="magenta">vf={accuracy.visualFormat.toFixed(1)}%</Text>{"  "}
        <Text color="blue">str={accuracy.strategy.toFixed(1)}%</Text>
      </Text>
      {rolling50 && (
        <Text>
          {" "}Rolling50{"  "}
          cat={rolling50.cat.toFixed(1)}%{"  "}
          vf={rolling50.vf.toFixed(1)}%{"  "}
          str={rolling50.str.toFixed(1)}%
        </Text>
      )}
      <ScopeRow label="FEED" s={byScope.FEED} />
      <ScopeRow label="REELS" s={byScope.REELS} />
    </Box>
  );
};
