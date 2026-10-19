"""Export authenticated existing preparation contents for independent execution audit."""

from dataclasses import asdict
from pathlib import Path
import sys
from uuid import UUID

from dataflows import DataRequest, Dataset, PreparedDataRef

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EX / "src/revision02"))
from run_accounts import context, publish_file, read, write  # noqa: E402


def main():
    ctx = context()
    binding = read(EX / "others/bindings/003.json")
    source = binding["execution_prepared"]
    prepared = PreparedDataRef(
        UUID(source["space_id"]), UUID(source["preparation_id"]), source["manifest_sha256"]
    )
    rows = []
    for key, item in binding["execution_requests"].items():
        assert item["parameters"] == {} and item["coverage"] is None
        request = DataRequest(
            Dataset(item["dataset"]),
            item["symbol"],
            item["start"],
            item["end"],
            item["required_cutoff"],
            item["frequency"],
        )
        result = ctx.data.fetch(request, prepared=prepared)
        assert (
            result.ready and result.identity.content_sha256 == binding["execution_identities"][key]
        )
        path = EX / f"others/input_exports/{key}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        assert not path.exists()
        result.dataframe.to_csv(path, index=False, lineterminator="\n", float_format="%.17g")
        rows.append(
            {
                "name": key,
                "request": asdict(request),
                "prepared": source,
                "content_sha256": result.identity.content_sha256,
                "csv_ref": publish_file(ctx, path, "ex040-authenticated-input-" + key),
                "row_count": len(result.dataframe),
                "columns": list(result.dataframe),
                "float_read_contract": "round_trip binary64, values exported with %.17g",
                "supplier_calls": 0,
            }
        )
    path = EX / "others/input_exports.json"
    write(
        path,
        {
            "status": "PASS",
            "records": rows,
            "input_prepare_calls": 0,
            "account_dispatches": 0,
            "supplier_calls": 0,
            "purpose": "same authenticated evaluation input content for independent fill/price constraint audit",
            "source": publish_file(ctx, Path(__file__), "ex040-input-export-source"),
        },
    )
    write(
        EX / "others/input_exports_ref.json",
        publish_file(ctx, path, "ex040-authenticated-input-exports"),
    )
    print("EXISTING_INPUT_CONTENTS_AUTHENTICATED_AND_PUBLIC", len(rows), flush=True)


if __name__ == "__main__":
    main()
