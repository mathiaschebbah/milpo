#!/usr/bin/env node
import { spawn } from "child_process";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");

const cmd = process.argv[2];
const args = process.argv.slice(3);

if (cmd === "run") {
  const child = spawn("npx", ["tsx", "tui/index.tsx", "--", ...args], {
    cwd: root,
    stdio: "inherit",
  });
  child.on("exit", (code) => process.exit(code ?? 0));
} else {
  console.log("Usage: milpo run [--dry-run] [--limit N] [--batch-size N] ...");
  process.exit(1);
}
