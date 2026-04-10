export interface ScopeAccuracy {
  n: number;
  category: number;
  visualFormat: number;
  strategy: number;
}

export interface TelemetryState {
  runId: number;
  flags: string[];
  cursor: number;
  total: number;
  nProcessed: number;
  rate: number;
  elapsedSec: number;
  etaSec: number | null;

  accuracy: { category: number; visualFormat: number; strategy: number };
  loss: { category: number; visualFormat: number; strategy: number };
  rolling50: { cat: number; vf: number; str: number } | null;
  byScope: {
    FEED: ScopeAccuracy;
    REELS: ScopeAccuracy;
  };

  costUsd: number;
  inputTokens: number;
  outputTokens: number;

  maxPromptVersion: number;
  errorBufferSize: number;
  batchSize: number;
  skipped: number;

  phase: "classification" | "rewrite" | "done" | "failed";
  rewriteSubPhase: string | null;
  rewritesPromoted: number;
  rewritesRollback: number;

  lastActivitySec: number;
  lastActivityLabel: string;

  events: Array<{ ts: string; msg: string; type?: "event" | "api" | "error" }>;
}
