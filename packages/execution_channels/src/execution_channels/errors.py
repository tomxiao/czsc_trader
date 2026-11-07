"""Execution-channel domain errors."""
class RuntimeContractError(ValueError):
    """Execution input violates its declared contract."""

class RuntimeExecutionError(RuntimeError):
    """Execution failed after input validation."""
