# Security Policy

PhoneVision Lab is a learning project that runs fully locally. There is no
cloud service, no account, and no telemetry.

## Supported versions

The project is pre-release (0.1.0-alpha). Security fixes land on `main` first and
are included in the next tagged release. Only the latest tagged version is
supported for security fixes.

## Reporting a vulnerability

Please **do not** report vulnerabilities through a public issue — that discloses
the issue to everyone before it can be fixed.

After the repository is public, use **GitHub Private Vulnerability Reporting**:

1. Go to the repository's **Security** tab → **Report a vulnerability**.
2. Describe the issue and, if possible, how to reproduce it.
3. For secrets or credentials, rotate/revoke them immediately and report via the
   private path — do not paste tokens into issues or commits.

> Note: private vulnerability reporting needs to be enabled on the repository.
> Enabling it is tracked in the P0-5C release checklist.

## What to include in a report

- Version / commit the issue affects
- Platform (Windows / Android / other) and environment
- A minimal description of the vulnerability
- Reproduction steps (no sensitive data, no full logs required)

## Scope

Security-sensitive areas include: the HTTP MJPEG stream has **no
authentication** — anyone on the same LAN can read the stream while the app is
streaming; use only on a trusted local network. Logs are local-only and do not
record image content, screenshots, parameter values, or secrets.
