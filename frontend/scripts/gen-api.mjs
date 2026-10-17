// Exports the backend OpenAPI schema to ../contracts/openapi.json (no server or DB needed:
// importing app.main only builds the FastAPI app), then generates src/lib/api/schema.d.ts.
// Set SKIP_EXPORT=1 to generate types from the committed contracts/openapi.json only.
import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const specPath = path.join(root, "contracts", "openapi.json");
const isWindows = process.platform === "win32";

if (!process.env.SKIP_EXPORT) {
  const env = { ...process.env };
  if (isWindows && !env.UV_PYTHON_INSTALL_DIR)
    env.UV_PYTHON_INSTALL_DIR = path.join(homedir(), "uv-python");
  const python = process.env.PYTHON ?? (isWindows ? "python" : "python3");
  const code =
    "import json; from app.main import app; print(json.dumps(app.openapi(), indent=2, sort_keys=True))";
  const res = spawnSync(python, ["-m", "uv", "run", "python", "-c", code], {
    cwd: path.join(root, "backend"),
    env,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  if (res.status !== 0) {
    console.error(res.stderr || res.error);
    process.exit(res.status ?? 1);
  }
  mkdirSync(path.dirname(specPath), { recursive: true });
  writeFileSync(specPath, res.stdout.trimEnd() + "\n");
  console.log(`wrote ${path.relative(root, specPath)}`);
}

const out = path.join("src", "lib", "api", "schema.d.ts");
const bin = path.join("node_modules", "openapi-typescript", "bin", "cli.js");
const gen = spawnSync(process.execPath, [bin, specPath, "-o", out], { stdio: "inherit" });
process.exit(gen.status ?? 1);
