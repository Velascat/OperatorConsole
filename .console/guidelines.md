# Guidelines

Operating rules for Claude in this repo.

## Branch Policy

- Do not commit directly to `main` or `master`.
- Before making any changes, confirm you are on a feature branch.
- If on a protected branch, stop and ask the operator to create a working branch.

## Before Acting

1. Read `.console/task.md` — understand the active objective.
2. Read `.console/backlog.md` — check what's in progress and what's next.
3. Read `.console/log.md` — review recent decisions and context.
4. Summarize your plan before making edits.

## During Work

- Run `./dev test` before and after changes, not broad validation suites.
- Use `./dev audit` for linting and static checks.
- Prefer `./dev status` over raw git commands to check workspace state.
- Prefer small, targeted edits over large rewrites.

## When to Update log.md

Update **before each commit**. Specifically, add an entry when:
- A decision was made (chose approach A over B, deferred X, excluded Y)
- A bug was fixed and the root cause is non-obvious
- A detector, feature, or API was added or removed
- Work is stopping and will resume next session (note where you left off)

## When to Update backlog.md

- When a task moves In Progress → Done
- When a new task is identified
- When scope or priority changes

## Commit Guard Hook

A pre-commit hook enforces log.md updates. Install once per clone:

```
git config core.hooksPath .hooks
```

The hook blocks commits that stage source files without also staging `.console/log.md`.
Override with `git commit --no-verify` only when the commit genuinely needs no log entry
(e.g. typo fix, lock file bump).

## What Not to Do

- Do not run destructive commands (`rm -rf`, `git reset --hard`) without explicit operator confirmation.
- Do not push to remote branches without the operator's explicit request.
- Do not modify files outside the repo root without explicit justification.
