import { mkdir, rm, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const packageRoot = fileURLToPath(new URL('../', import.meta.url));
const distDir = path.join(packageRoot, 'dist');
const tscBin = path.join(packageRoot, 'node_modules', 'typescript', 'bin', 'tsc');

await rm(distDir, { recursive: true, force: true });

for (const config of ['tsconfig.esm.json', 'tsconfig.cjs.json']) {
  const result = spawnSync(process.execPath, [tscBin, '-p', config], {
    cwd: packageRoot,
    stdio: 'inherit',
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

const cjsDir = path.join(distDir, 'cjs');
await mkdir(cjsDir, { recursive: true });
await writeFile(path.join(cjsDir, 'package.json'), '{"type":"commonjs"}\n', 'utf8');
