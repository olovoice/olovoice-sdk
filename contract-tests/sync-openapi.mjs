import { copyFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const contractDir = dirname(fileURLToPath(import.meta.url));
const mintlifyDir = resolve(contractDir, "../../mintlify");

for (const name of ["openapi.json", "openapi.tr.json"]) {
  await copyFile(resolve(mintlifyDir, name), resolve(contractDir, name));
}

console.log("Synced EN/TR OpenAPI snapshots from ../../mintlify.");
