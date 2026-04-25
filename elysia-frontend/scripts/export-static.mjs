import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(__dirname, "..");
const sourceDir = resolve(frontendDir, "out");
const destinationDir = resolve(frontendDir, "..", "elysia", "elysia", "api", "static");

if (!existsSync(sourceDir)) {
  console.error("Error: 'out' directory not found. Run 'npm run build' first.");
  process.exit(1);
}

mkdirSync(destinationDir, { recursive: true });
rmSync(destinationDir, { recursive: true, force: true });
mkdirSync(destinationDir, { recursive: true });
cpSync(sourceDir, destinationDir, { recursive: true });

console.log(`Exported static frontend from ${sourceDir} to ${destinationDir}`);
