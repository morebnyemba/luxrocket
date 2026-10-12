// Generates TypeScript types from /contracts JSON Schemas (source of truth, ADR-001).
// Usage: node scripts/generate.mjs [--check]   (--check fails if committed output is stale)
import { readFileSync, readdirSync, statSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join, relative, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const contracts = join(here, "../../../contracts");
const outDir = join(here, "../src/generated");
const check = process.argv.includes("--check");

const walk = (dir) =>
  readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? walk(p) : p.endsWith(".schema.json") ? [p] : [];
  });

const files = walk(contracts).sort();
const banner = "/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */";
const outputs = new Map();
const index = [];

for (const file of files) {
  const rel = relative(contracts, file); // e.g. ws/v1/place-bet.schema.json
  const schema = JSON.parse(readFileSync(file, "utf8"));
  const name = rel.replace(/\.schema\.json$/, "").replace(/[^a-zA-Z0-9]+/g, "_");
  const typeName = name.replace(/(^|_)([a-z0-9])/g, (_, __, c) => c.toUpperCase());
  delete schema.$id;
  // Name types from the file path, not the human-readable title.
  if (schema.title) {
    schema.description ??= schema.title;
    delete schema.title;
  }
  const ts = await compile(schema, typeName, {
    bannerComment: banner,
    additionalProperties: false,
    strictIndexSignatures: true,
    format: true,
  });
  outputs.set(`${name}.ts`, ts);
  index.push(`export type { ${typeName} } from "./${name}";`);
}
outputs.set("index.ts", `${banner}\n${index.join("\n")}\n`);

let stale = false;
if (!check) mkdirSync(outDir, { recursive: true });
for (const [f, content] of outputs) {
  const p = join(outDir, f);
  if (check) {
    if (!existsSync(p) || readFileSync(p, "utf8") !== content) {
      console.error(`stale: ${f}`);
      stale = true;
    }
  } else writeFileSync(p, content);
}
if (check && stale) {
  console.error("Generated protocol types are out of date. Run: pnpm --filter @luxrocket/protocol generate");
  process.exit(1);
}
console.log(check ? "protocol types up to date" : `generated ${outputs.size} files`);
