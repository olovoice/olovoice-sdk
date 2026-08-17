# Public API contract gate

This dependency-free Node 22+ test package protects the SDK against public API
contract drift. It validates the vendored English and Turkish OpenAPI snapshots,
internal `$ref` resolution, locale parity, endpoint scopes, rollout metadata,
conditional `/call` fixtures, carrier response variants, assistant persistence
shapes and PATCH clears, concrete metrics responses, provider allowlists, and
call-log nullability.

From the standalone `sdk` repository root:

```bash
cd contract-tests
npm ci
npm test
```

The snapshots make the gate runnable from a standalone SDK checkout. In the
combined voiceSaas workspace, the test also fails if either snapshot differs
byte-for-byte from `../../mintlify/openapi*.json`.

After an intentional Mintlify contract change, update both snapshots and rerun
the gate:

```bash
cd sdk/contract-tests
npm run sync
npm test
```

Commit the canonical Mintlify files and both SDK snapshots together.
