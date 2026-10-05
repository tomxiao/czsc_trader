"""Write boundaries for caller-selected research locations."""

from pathlib import Path

from .context import RepositoryContext


def require_research_write(context: RepositoryContext, target: Path) -> None:
    """Reject writes into sealed ancestors or overlapping the runtime registry."""
    target = target.resolve()
    root = context.root.resolve()
    if not target.is_relative_to(root):
        raise ValueError("research write escapes repository")
    runtime = context.strategy_root.resolve()
    if target.is_relative_to(runtime) or runtime.is_relative_to(target):
        raise ValueError("research write overlaps platform runtime publication space")
    for parent in (target, *target.parents):
        if (parent / "experiment_manifest.json").exists():
            raise ValueError("cannot write into a sealed experiment")
        if parent == root:
            break
