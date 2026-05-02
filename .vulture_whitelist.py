# Vulture whitelist — symbols that are intentional public API not yet called from src/.
# CxRP boundary surface: these are the module's exported functions, called by
# downstream TUI code once the CxRP submission flow is wired up.
from operator_console.cxrp_capture import build_task_proposal, summarize_execution_result

build_task_proposal
summarize_execution_result
