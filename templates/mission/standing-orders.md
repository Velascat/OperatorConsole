# Standing Orders

Operating rules for Claude in this repo.

## Branch Policy

- Do not commit directly to `main` or `master`.
- Before making any changes, confirm you are on a feature branch.
- If on a protected branch, stop and ask the operator to create a working branch.

## Before Acting

1. Read `.fob/active-mission.md` — understand the current objective.
2. Read `.fob/objectives.md` — check what's in progress and what's next.
3. Read `.fob/mission-log.md` — review recent decisions and context.
4. Summarize your plan before making any edits.

## During Work

- Run `fob test` before and after changes.
- Use `fob audit` for linting and static checks.
- Use `fob status` to check repo and session state.
- Prefer small, targeted edits over large rewrites.

## After Meaningful Progress

- Update `.fob/objectives.md` to reflect completed and remaining work.
- Update `.fob/mission-log.md` with decisions made and rationale.
- Summarize what changed and what's next.

## What Not to Do

- Do not run destructive commands (`rm -rf`, `git reset --hard`) without explicit operator confirmation.
- Do not push to remote branches without the operator's explicit request.
- Do not modify files outside the repo root without explicit justification.
