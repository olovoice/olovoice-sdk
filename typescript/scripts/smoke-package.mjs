import { access, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = fileURLToPath(new URL('../', import.meta.url));
const tarballArgument = process.argv[2];
if (!tarballArgument) {
  throw new Error('Usage: node scripts/smoke-package.mjs /absolute/path/to/package.tgz');
}

const tarball = path.resolve(tarballArgument);
await access(tarball);
const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), 'olovoice-npm-smoke-'));

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: temporaryRoot,
    encoding: 'utf8',
    stdio: 'pipe',
  });
  if (result.status !== 0) {
    process.stdout.write(result.stdout ?? '');
    process.stderr.write(result.stderr ?? '');
    process.exitCode = result.status ?? 1;
    throw new Error(`${command} ${args.join(' ')} failed.`);
  }
}

try {
  await writeFile(
    path.join(temporaryRoot, 'package.json'),
    '{"name":"olovoice-package-smoke","private":true,"type":"module"}\n',
    'utf8',
  );
  run(npmCommand, ['install', '--ignore-scripts', '--no-audit', '--no-fund', tarball]);

  run(process.execPath, [
    '--input-type=module',
    '--eval',
    "import DefaultClient,{OloVoice} from 'olovoice';" +
      "if(DefaultClient!==OloVoice)throw new Error('ESM default export mismatch');" +
      "new OloVoice({apiKey:'package-smoke'});",
  ]);
  run(process.execPath, [
    '--input-type=commonjs',
    '--eval',
    "const pkg=require('olovoice');" +
      "if(pkg.default!==pkg.OloVoice)throw new Error('CJS default export mismatch');" +
      "new pkg.OloVoice({apiKey:'package-smoke'});",
  ]);

  const consumerSource = [
    "import DefaultClient, { OloVoice, ConnectionError } from 'olovoice';",
    'const client: OloVoice = new DefaultClient({ apiKey: \'package-smoke\' });',
    'const error: ConnectionError | undefined = undefined;',
    'void client;',
    'void error;',
    '',
  ].join('\n');
  await writeFile(path.join(temporaryRoot, 'consumer.mts'), consumerSource, 'utf8');
  await writeFile(path.join(temporaryRoot, 'consumer.cts'), consumerSource, 'utf8');
  await writeFile(
    path.join(temporaryRoot, 'tsconfig.json'),
    JSON.stringify(
      {
        compilerOptions: {
          target: 'ES2020',
          module: 'NodeNext',
          moduleResolution: 'NodeNext',
          lib: ['ES2020', 'DOM'],
          strict: true,
          noEmit: true,
        },
        include: ['consumer.mts', 'consumer.cts'],
      },
      null,
      2,
    ) + '\n',
    'utf8',
  );
  const tscBin = path.join(packageRoot, 'node_modules', 'typescript', 'bin', 'tsc');
  run(process.execPath, [tscBin, '-p', 'tsconfig.json']);

  const installedPackage = JSON.parse(
    await readFile(path.join(temporaryRoot, 'node_modules', 'olovoice', 'package.json'), 'utf8'),
  );
  await access(path.join(temporaryRoot, 'node_modules', 'olovoice', 'LICENSE'));
  console.log(`Installed package smoke passed: olovoice@${installedPackage.version}`);
} finally {
  await rm(temporaryRoot, { recursive: true, force: true });
}
