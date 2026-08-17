const approval = process.env.OLOVOICE_PUBLISH_APPROVAL;
const npmUserAgent = process.env.npm_config_user_agent ?? '';
const npmVersion = npmUserAgent.match(/(?:^|\s)npm\/([^\s]+)/u)?.[1] ?? 'unknown';

if (process.env.GITHUB_ACTIONS !== 'true') {
  throw new Error(
    'Publishing is restricted to a protected GitHub Actions environment using npm Trusted Publishing.',
  );
}
if (approval !== 'registry-names-reserved') {
  throw new Error(
    'Publishing is disabled until both registry names are reserved and the protected release ' +
      'environment sets OLOVOICE_PUBLISH_APPROVAL=registry-names-reserved.',
  );
}

const [npmMajor = 0, npmMinor = 0, npmPatch = 0] = npmVersion
  .split('.')
  .map((part) => Number.parseInt(part, 10));
const npmSupportsTrustedPublishing =
  npmMajor > 11 ||
  (npmMajor === 11 && (npmMinor > 5 || (npmMinor === 5 && npmPatch >= 1)));
if (!npmSupportsTrustedPublishing) {
  throw new Error(`npm ${npmVersion} is too old for Trusted Publishing; npm >=11.5.1 is required.`);
}

const [nodeMajor = 0, nodeMinor = 0] = process.versions.node
  .split('.')
  .map((part) => Number.parseInt(part, 10));
if (nodeMajor < 22 || (nodeMajor === 22 && nodeMinor < 14)) {
  throw new Error(
    `Node ${process.versions.node} is too old for npm Trusted Publishing; Node >=22.14 is required.`,
  );
}
