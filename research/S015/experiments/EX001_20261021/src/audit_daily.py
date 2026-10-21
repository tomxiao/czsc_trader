"""Recheck retained S015 daily assets through the public DFLS contract.

Run from the repository root. Reads the saved preparation and performs no
provider refresh, strategy evaluation, or cross-batch access.
"""

import json
from pathlib import Path
from uuid import UUID

from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef
from dataflows import DataRequest, Dataset, PreparedDataRef


def main():
    root = Path.cwd()
    source = Path(__file__).resolve().parent.parent / "others/data_audit.json"
    audit = json.loads(source.read_text(encoding="utf-8"))
    saved = audit["prepared_reference"]
    prepared = PreparedDataRef(
        space_id=UUID(saved["space_id"]),
        preparation_id=UUID(saved["preparation_id"]),
        manifest_sha256=saved["manifest_sha256"],
    )
    research = create_research_context(
        RepositoryContext.discover(root), ResearchBatchRef("S015")
    )
    for raw, expected in zip(audit["requests"], audit["items"], strict=True):
        request = DataRequest(**{**raw, "dataset": Dataset(raw["dataset"])})
        result = research.data.fetch(request, prepared=prepared)
        if not result.ready:
            raise RuntimeError(result.error)
        actual = result.identity
        if actual.content_sha256 != expected["identity"]["content_sha256"]:
            raise ValueError("retained asset differs from the audited identity")
        dates = result.dataframe["Date"].astype(str).str[:10]
        warmup = int((dates < "2025-01-02").sum())
        evaluation = int((dates >= "2025-01-02").sum())
        if (len(dates), warmup, evaluation) != (509, 75, 434):
            raise ValueError("audited coverage changed")
        print(json.dumps({"dataset": actual.dataset, "rows": len(dates),
                          "warmup": warmup, "evaluation": evaluation,
                          "content_sha256": actual.content_sha256}))


if __name__ == "__main__":
    main()
