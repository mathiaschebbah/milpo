import React, { useState, useEffect, useRef } from "react";
import { render, Box, Text } from "ink";
import { WebSocketServer } from "ws";
import { spawn, type ChildProcess } from "child_process";
import type { AddressInfo } from "net";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import type { TelemetryState } from "./types.js";
import { Dashboard } from "./components/Dashboard.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(__dirname, "..");

const WS_HOST = "127.0.0.1";

interface InitTelemetry {
  init: true;
  phase?: string;
  stage?: string;
  done?: number;
  total?: number;
  unit?: string;
  elapsedSec?: number;
  stageElapsedSec?: number;
  rate?: number;
  etaSec?: number;
}

function isInitMessage(data: unknown): data is InitTelemetry {
  return typeof data === "object" && data !== null && "init" in data && data.init === true;
}

function buildProgressBar(done: number, total: number, width = 32): string {
  if (total <= 0) {
    return "";
  }
  const filled = Math.max(0, Math.min(width, Math.round((done / total) * width)));
  return `${"\u2588".repeat(filled)}${"\u2591".repeat(width - filled)}`;
}

const InitStatus: React.FC<{ progress: InitTelemetry | null; wsUrl: string | null }> = ({
  progress,
  wsUrl,
}) => {
  if (!progress) {
    const msg = wsUrl
      ? `Starting MILPO simulation (waiting for telemetry on ${wsUrl})...`
      : "Starting MILPO simulation...";
    return <Text color="yellow"> {msg}</Text>;
  }

  const label = progress.phase ?? "Initializing...";
  const hasCounts =
    typeof progress.done === "number" &&
    typeof progress.total === "number";

  if (!hasCounts) {
    return <Text color="yellow"> {label}</Text>;
  }

  const done = progress.done ?? 0;
  const total = progress.total ?? 0;
  const unit = progress.unit ?? "items";
  const pct = total > 0 ? Math.floor((done * 100) / total) : 100;
  const bar = buildProgressBar(done, total);

  return (
    <Box flexDirection="column">
      <Text color="yellow"> {label}</Text>
      {total > 0 ? (
        <Text>
          {" "}{bar} {done}/{total} ({pct}%){" "}
          <Text dimColor>{unit}</Text>
        </Text>
      ) : (
        <Text>
          {" "}{done} <Text dimColor>{unit}</Text>
        </Text>
      )}
      {progress.stage && (
        <Text dimColor> {" "}stage={progress.stage}</Text>
      )}
      <Text dimColor>
        {" "}elapsed={progress.stageElapsedSec ?? progress.elapsedSec ?? 0}s
        {typeof progress.rate === "number" ? `  rate=${progress.rate.toFixed(1)} ${unit}/s` : ""}
        {typeof progress.etaSec === "number" ? `  eta=${progress.etaSec}s` : ""}
      </Text>
    </Box>
  );
};

const App: React.FC = () => {
  const [state, setState] = useState<TelemetryState | null>(null);
  const [initProgress, setInitProgress] = useState<InitTelemetry | null>(null);
  const [wsUrl, setWsUrl] = useState<string | null>(null);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [pythonExited, setPythonExited] = useState(false);
  const [exitCode, setExitCode] = useState<number | null>(null);
  const childRef = useRef<ChildProcess | null>(null);

  useEffect(() => {
    let cleanedUp = false;

    // 1. Start WebSocket server on a free local port
    const wss = new WebSocketServer({ host: WS_HOST, port: 0 });

    wss.on("connection", (ws) => {
      ws.on("message", (raw) => {
        try {
          const data = JSON.parse(raw.toString());
          if (isInitMessage(data)) {
            setInitProgress(data);
          } else {
            setState(data as TelemetryState);
            setInitProgress(null);
          }
        } catch {
          // ignore malformed messages
        }
      });
    });

    wss.on("error", (error) => {
      setStartupError(`WebSocket server failed: ${error.message}`);
    });

    wss.on("listening", () => {
      if (cleanedUp) {
        return;
      }

      const address = wss.address();
      if (address === null || typeof address === "string") {
        setStartupError("WebSocket server did not expose a listening address.");
        return;
      }

      const { port } = address as AddressInfo;
      const url = `ws://${WS_HOST}:${port}`;
      setWsUrl(url);

      // 2. Spawn Python simulation once the WebSocket server is actually listening
      const args = process.argv.slice(2).filter((a) => a !== "--");
      const child = spawn("uv", ["run", "python", "scripts/run_simulation.py", ...args], {
        cwd: projectRoot,
        stdio: ["inherit", "ignore", "ignore"],
        env: {
          ...process.env,
          MILPO_WS_HOST: WS_HOST,
          MILPO_WS_PORT: String(port),
        },
      });
      childRef.current = child;

      child.on("error", (error) => {
        setStartupError(`Python process failed to start: ${error.message}`);
      });

      child.on("exit", (code) => {
        setExitCode(code);
        setPythonExited(true);
      });
    });

    // Cleanup on Ctrl+C or unmount
    const cleanup = () => {
      if (cleanedUp) return;
      cleanedUp = true;
      childRef.current?.kill("SIGINT");
      wss.close();
    };

    const onExit = () => {
      cleanup();
      process.exit(0);
    };
    process.on("SIGINT", onExit);
    process.on("SIGTERM", onExit);

    return () => {
      cleanup();
      process.off("SIGINT", onExit);
      process.off("SIGTERM", onExit);
    };
  }, []);

  if (startupError) {
    return <Text color="red"> {startupError}</Text>;
  }

  if (!state && pythonExited) {
    return <Text color="red"> Python process exited (code {exitCode}) without sending telemetry. Run manually to see errors:{"\n"}  uv run python scripts/run_simulation.py</Text>;
  }

  if (!state) {
    return <InitStatus progress={initProgress} wsUrl={wsUrl} />;
  }

  return <Dashboard state={state} done={pythonExited} />;
};

render(<App />);
