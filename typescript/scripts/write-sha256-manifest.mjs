import { createHash } from 'node:crypto';
import { access, readFile, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';

const artifactArguments = process.argv.slice(2);
if (artifactArguments.length === 0) {
  throw new Error('Usage: node scripts/write-sha256-manifest.mjs /absolute/path/to/artifact');
}

const artifacts = artifactArguments.map((artifact) => path.resolve(artifact)).sort();
const directories = new Set(artifacts.map((artifact) => path.dirname(artifact)));
if (directories.size !== 1) {
  throw new Error('All artifacts must share one staging directory.');
}

const names = artifacts.map((artifact) => path.basename(artifact));
if (new Set(names).size !== names.length || names.includes('SHA256SUMS')) {
  throw new Error('Artifact names must be unique and may not be SHA256SUMS.');
}

const entries = [];
for (const artifact of artifacts) {
  await access(artifact);
  if (!(await stat(artifact)).isFile()) {
    throw new Error(`Artifact is not a regular file: ${artifact}`);
  }
  const digest = createHash('sha256').update(await readFile(artifact)).digest('hex');
  entries.push({ artifact, digest, name: path.basename(artifact) });
}

const stagingDirectory = [...directories][0];
const manifestPath = path.join(stagingDirectory, 'SHA256SUMS');
await writeFile(
  manifestPath,
  entries.map(({ digest, name }) => `${digest}  ${name}`).join('\n') + '\n',
  'utf8',
);

for (const { artifact, digest } of entries) {
  const actual = createHash('sha256').update(await readFile(artifact)).digest('hex');
  if (actual !== digest) {
    throw new Error(`SHA256 verification failed for ${artifact}.`);
  }
}

console.log(`SHA256 manifest verified: ${manifestPath}`);
