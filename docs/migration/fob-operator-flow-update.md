# OperatorConsole Operator Flow Update

Historical migration note. The current supported operator flow is selector-first;
this file is retained only to record the cutover from the removed provider-proxy era.

- `console providers` now reports selector and lane readiness instead of treating 9router as the provider control plane.
- `console demo` validates `SwitchBoard /health`, `POST /route`, and the OperationsCenter planning handoff.
- Default help text and operator guidance now point to the selector-first architecture only.
