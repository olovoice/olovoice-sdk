import { readFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const packageRoot = fileURLToPath(new URL('../', import.meta.url));
const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const requiredFiles = new Set([
  'LICENSE',
  'README.md',
  'package.json',
  'dist/esm/index.js',
  'dist/esm/index.d.ts',
  'dist/cjs/index.js',
  'dist/cjs/index.d.ts',
  'dist/cjs/package.json',
]);

const cjsPackage = JSON.parse(
  await readFile(path.join(packageRoot, 'dist', 'cjs', 'package.json'), 'utf8'),
);
if (cjsPackage.type !== 'commonjs') {
  throw new Error('dist/cjs/package.json must declare {"type":"commonjs"}.');
}

const result = spawnSync(
  npmCommand,
  ['pack', '--dry-run', '--json', '--ignore-scripts'],
  { cwd: packageRoot, encoding: 'utf8' },
);
if (result.status !== 0) {
  process.stderr.write(result.stderr ?? '');
  process.exit(result.status ?? 1);
}

const report = JSON.parse(result.stdout);
const packedFiles = new Set(report[0]?.files?.map(({ path: filePath }) => filePath) ?? []);
const missing = [...requiredFiles].filter((filePath) => !packedFiles.has(filePath));
if (missing.length > 0) {
  throw new Error(`Package would be incomplete; missing: ${missing.join(', ')}`);
}

const forbidden = [...packedFiles].filter(
  (filePath) =>
    filePath.startsWith('src/') ||
    filePath.startsWith('test/') ||
    filePath.includes('node_modules/') ||
    filePath.includes('.env') ||
    filePath.endsWith('.tgz'),
);
if (forbidden.length > 0) {
  throw new Error(`Package contains forbidden development files: ${forbidden.join(', ')}`);
}

console.log(`Package content guard passed: ${packedFiles.size} files.`);
