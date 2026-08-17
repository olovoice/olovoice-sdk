# Security policy

## Supported versions

The SDKs are currently public beta releases. Until 1.0, security fixes target
the latest published minor line; users should pin a tested version and upgrade
promptly when a security release is published.

| Version | Supported |
| --- | --- |
| `0.1.x` | Yes |
| `< 0.1` | No |

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's
[private vulnerability reporting](https://github.com/olovoice/olovoice-sdk/security/advisories/new)
to contact the maintainers privately.

Include the affected package and version, impact, reproduction steps, and any
suggested mitigation. Do not include live OloVoice API keys, customer data, or
call recordings. Revoke any credential that may have been exposed before
submitting the report.
