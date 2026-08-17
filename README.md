# OloVoice SDKs

Official client SDKs for the [OloVoice Public API](https://docs.olovoice.ai) (`https://api.olovoice.ai`).
The canonical source repository is [olovoice/olovoice-sdk](https://github.com/olovoice/olovoice-sdk).

> **Beta (0.1.x):** these SDKs are public, pre-1.0 releases. Interfaces may
> evolve before 1.0, so pin and test an exact SDK version for production use.

| Package | Language | Directory | Current status |
| --- | --- | --- | --- |
| `olovoice` (npm) | TypeScript / JavaScript (Node 22+) | [typescript/](typescript/) | 0.1.0 beta |
| `olovoice` (PyPI) | Python 3.11+ (sync + async) | [python/](python/) | 0.1.0 beta |

## Install

```bash
npm install olovoice@0.1.0
python -m pip install olovoice==0.1.0
```

Both SDKs are maintained against the [vendored English and Turkish OpenAPI
snapshots](contract-tests/) (spec v2.0.0). In the combined workspace, the
contract gate also requires those snapshots to match the canonical Mintlify
specs byte-for-byte. A release must update both languages together and pass the
contract and cross-language version guards.

Shared behavior:

- Bearer auth via constructor or the `OLOVOICE_API_KEY` environment variable.
- Typed HTTP errors carry the server error, parsed body, and request ID.
- GET requests retry on 429, 5xx, and network errors; mutating requests are not
  retried automatically because replaying `/call` could dial twice.
- SDK paths do not include `/api/v1` or `/api/public`; the gateway maps the
  public paths.

## Development

From this `sdk/` directory:

```bash
# Cross-language version and license consistency
python3 scripts/check_versions.py

# Public OpenAPI structure, language parity, scopes, and rollout metadata
cd contract-tests
npm ci
npm test
cd ..

# TypeScript: clean portable build and mocked unit tests
cd typescript
npm ci
npm test
cd ..

# Python: sync and async tests
cd python
uv sync --frozen --no-build --python 3.11 --extra dev --no-install-project
uv run --frozen --no-sync python -m pytest -p no:cacheprovider
uv run --frozen --no-sync python -m mypy --strict olovoice tests
uv run --frozen --no-sync python -m bandit -q -r olovoice
uv run --frozen --no-sync python -m pip_audit \
  --local --strict --progress-spinner off
uv run --frozen --no-sync python \
  ../scripts/check_python_lowest_dependencies.py --python 3.11
cd ..
```

The TypeScript build uses Node scripts rather than POSIX-only shell commands,
so the declared Node 22 baseline can be tested on macOS, Linux, and Windows.
Python development and release commands use uv 0.12.3 with the committed,
hash-bearing `uv.lock`; `--frozen` prevents dependency re-resolution.

## Release artifact checks

These commands build and inspect artifacts but never upload them.

```bash
# npm: prepack runs version checks, a clean build, tests, and a package-content guard
cd typescript
npm pack --pack-destination /absolute/path/to/an/empty/staging-directory
VERSION="$(node -p "require('./package.json').version")"
node scripts/smoke-package.mjs "/absolute/path/to/staging/olovoice-${VERSION}.tgz"
node scripts/write-sha256-manifest.mjs \
  "/absolute/path/to/staging/olovoice-${VERSION}.tgz"
npm run lint:package -- "/absolute/path/to/staging/olovoice-${VERSION}.tgz"
npm run audit:types -- "/absolute/path/to/staging/olovoice-${VERSION}.tgz"
cd ..

# PyPI: the output directory must be new or empty, preventing stale uploads
cd python
uv sync --frozen --no-build --python 3.11 --extra dev --no-install-project
uv run --frozen --no-sync python \
  ../scripts/check_python_lowest_dependencies.py --python 3.11
uv sync --frozen --no-build --python 3.13 --extra release --no-install-project
uv run --frozen --no-sync python ../scripts/build_python_release.py \
  --out-dir /absolute/path/to/an/empty/staging-directory
cd ..
```

The Python helper creates exactly one wheel and one source distribution, runs
`twine check`, verifies the MIT license and `py.typed` marker, rejects
virtualenv/cache residue, and writes a verified `SHA256SUMS` manifest. It uses
the exact locked Hatchling/build/Twine versions with build isolation disabled.
The npm helper installs the tarball into an isolated consumer and checks ESM,
CommonJS, and TypeScript resolution; its staging directory also receives a
verified `SHA256SUMS` manifest.

## Supply-chain controls

- GitHub Actions are pinned to reviewed full commit SHAs, with their release
  versions recorded in comments. Update a pin only after checking the matching
  tag against the action's official upstream repository with `git ls-remote`.
- CI uses explicit `ubuntu-24.04` and `windows-2025` runner labels so a future
  major image rollover cannot silently change the build environment.
- npm tooling, including publint and AreTheTypesWrong, is an exact
  `devDependency` installed only through `npm ci`; release checks never fetch an
  uncommitted `npx` package. CI also verifies registry signatures and available
  attestations with `npm audit signatures`.
- Python CI installs wheels from the hashed `uv.lock` with uv 0.12.3,
  `--frozen`, and `--no-build`.
  It audits that installed locked environment with pip-audit 2.10.1.
  A separate lowest-supported consumer gate installs `httpx==0.28.1`,
  `httpcore==1.0.9`, and `h11==0.16.0` from wheels and audits that environment;
  Python artifacts cannot build until the Python test matrix, including this
  floor check, succeeds.
  The artifact build runs `python -m build --no-isolation` against exact locked
  backend and validation tools.
- Artifact jobs upload only the resolved tarball/wheel/sdist paths and their
  SHA256 manifests. Normal CI keeps read-only permissions and has no publish or
  OIDC permission.

## Registry release gate

Normal CI cannot publish. Registry releases must use the protected release
workflow and complete these checks:

1. Verify the organization-controlled npm and PyPI accounts have 2FA enabled,
   are the intended package owners, and can use the exact `olovoice` names.
2. Verify the release commit is from the canonical
   `https://github.com/olovoice/olovoice-sdk` repository and that npm/PyPI
   metadata points to that exact repository.
3. Protect the `release` environment with required human approval. Configure a
   PyPI pending Trusted Publisher for the exact repository, workflow, and
   environment. Configure npm Trusted Publishing whenever the npm package
   already exists.
4. For npm publishing, use the reviewed full-SHA pins from CI for checkout and
   Node setup, Node 24, npm 11.19.0, and job-level `id-token: write`.
   npm Trusted Publishing supplies provenance automatically; `publishConfig`
   also fixes public access, the official registry, and provenance. The package
   refuses publishing unless GitHub Actions sets
   `OLOVOICE_PUBLISH_APPROVAL=registry-names-reserved` in that protected job.
5. npm does not support Trusted Publishing for a package's first release. For
   that bootstrap only, place a short-lived granular token in the protected
   environment as `NPM_BOOTSTRAP_TOKEN`. After the first successful publish,
   configure the exact npm Trusted Publisher, delete the environment secret,
   and revoke the token. Subsequent releases must leave the secret absent and
   use OIDC.
6. For PyPI, use the protected environment and job-level `id-token: write`. Pin
   `pypa/gh-action-pypi-publish` to a reviewed full commit SHA corresponding to
   a specific release. Pass only the checksummed artifacts produced by the
   validated build job; do not use a stored API token or a broad `dist/*` glob.
7. Tag the reviewed commit, verify both package versions match the tag, run the
   artifact smokes, verify each `SHA256SUMS` entry, obtain approval, and only
   then publish.

Normal CI intentionally has read-only permissions and cannot publish.
