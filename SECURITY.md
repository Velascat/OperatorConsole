# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| `main`  | ✅ Yes     |

Only the current `main` branch receives security fixes.

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report security issues privately by emailing **coding.projects.1642@proton.me**.

Include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested mitigations (optional)

You will receive an acknowledgment within 72 hours. We aim to release a fix within 14 days of a confirmed report, depending on severity and complexity.

## Scope

OperatorConsole is a local developer tool — it runs on your machine and does not expose network services. The primary security surface is:

- Shell command injection via profile YAML or CLI arguments
- Zellij session hijacking via KDL layout injection
- Credential exposure via `.console/` state files committed to git

## Out of Scope

- Vulnerabilities in Zellij, Claude Code CLI, lazygit, or other upstream tools
- Issues that require physical access to the developer's machine
