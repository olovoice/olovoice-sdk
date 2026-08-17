import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const packageRoot = fileURLToPath(new URL('../', import.meta.url));
const sdkRoot = path.dirname(packageRoot);

const packageJson = JSON.parse(await readFile(path.join(packageRoot, 'package.json'), 'utf8'));
const packageLock = JSON.parse(
  await readFile(path.join(packageRoot, 'package-lock.json'), 'utf8'),
);
const clientSource = await readFile(path.join(packageRoot, 'src', 'client.ts'), 'utf8');
const pythonClientSource = await readFile(
  path.join(sdkRoot, 'python', 'olovoice', '_client.py'),
  'utf8',
);

const semverPattern =
  /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/u;
const tsVersion = clientSource.match(/const VERSION\s*=\s*['"]([^'"]+)['"]/u)?.[1];
const pythonVersion = pythonClientSource.match(/^__version__\s*=\s*['"]([^'"]+)['"]/mu)?.[1];
const versions = {
  'package.json': packageJson.version,
  'package-lock.json': packageLock.version,
  'package-lock root package': packageLock.packages?.['']?.version,
  'TypeScript User-Agent': tsVersion,
  'Python package/User-Agent': pythonVersion,
};

for (const [source, version] of Object.entries(versions)) {
  if (typeof version !== 'string' || !semverPattern.test(version)) {
    throw new Error(`${source} does not contain a valid SemVer version: ${String(version)}`);
  }
  if (version !== packageJson.version) {
    throw new Error(
      `Version drift: ${source} is ${version}, expected ${packageJson.version}. ` +
        'Both SDKs must be released together.',
    );
  }
}

console.log(`Version guard passed: ${packageJson.version}`);
