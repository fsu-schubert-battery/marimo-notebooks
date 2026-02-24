# /// script
# name = "parquet-test"
# version = "0.1.0"
# description = "Minimal test: load precomputed parquet files and display them"
# requires-python = ">=3.12"
# dependencies = [
#     "marimo[recommended]>=0.20.1",
#     "polars>=0.19.0",
#     "scipy>=1.11.0",
#     "numpy>=1.24.0",
#     "altair>=5.0.0",
# ]
#
# [tool.marimo.runtime]
# output_max_bytes = 100_000_000
# ///

import marimo

__generated_with = "0.20.2"
app = marimo.App(
    width="medium",
    app_title="Parquet Loading Test",
)

with app.setup:
    import marimo as mo
    import sys
    import tempfile
    from pathlib import Path
    import polars as pl

    def is_wasm() -> bool:
        return "pyodide" in sys.modules


@app.cell
def _():
    mo.md(
        f"""
        # Parquet Loading Test

        **Runtime:** `{"WASM/Pyodide" if is_wasm() else "Native Python"}`

        **Notebook location:** `{mo.notebook_location()}`
        """
    )
    return


@app.cell
def _():
    def _ensure_local(file_path: str | Path) -> Path:
        _path_str = str(file_path)
        if _path_str.startswith(("http://", "https://")):
            import urllib.request

            _suffix = Path(_path_str.split("?")[0].split("/")[-1]).suffix
            _fd = tempfile.NamedTemporaryFile(suffix=_suffix, delete=False)
            with urllib.request.urlopen(_path_str) as _response:
                _fd.write(_response.read())
            _fd.close()
            return Path(_fd.name)
        return Path(file_path)

    def _fix_wasm_url(source) -> str:
        """PurePosixPath collapses https:// to https:/ — restore double slash."""
        _s = str(source)
        for _scheme in ("https:/", "http:/"):
            if _s.startswith(_scheme) and not _s.startswith(_scheme + "/"):
                return _scheme + "/" + _s[len(_scheme):]
        return _s

    def load_precomputed_df(name: str) -> pl.DataFrame:
        _relative = f"public/data/{name}.parquet"
        _source = mo.notebook_location() / _relative

        if is_wasm():
            import pyarrow.parquet as pq
            import io

            _source_str = _fix_wasm_url(_source)
            mo.output.append(mo.md(f"**Loading:** `{_source_str}`"))
            _local_path = _ensure_local(_source_str)
            # polars' native parquet reader is not available in Pyodide/WASM,
            # so we use pyarrow to read and convert to polars
            _arrow_table = pq.read_table(str(_local_path))
            return pl.from_arrow(_arrow_table)

        mo.output.append(mo.md(f"**Loading:** `{_source}`"))
        return pl.read_parquet(_source)

    return (load_precomputed_df,)


@app.cell
def _(load_precomputed_df):
    _names = [
        "data_structure_df",
        "eis_flat_df",
        "polarisation_flat_df",
        "cd_cycling_flat_df",
        "temperature_data_df",
    ]
    results = {}
    for _name in _names:
        try:
            _df = load_precomputed_df(_name)
            results[_name] = {"status": "✅", "rows": _df.height, "cols": _df.width}
        except Exception as e:
            results[_name] = {"status": "❌", "error": str(e)}

    return (results,)


@app.cell
def _(results):
    _rows = []
    for _name, _info in results.items():
        if "error" in _info:
            _rows.append(f"| {_info['status']} | `{_name}` | ERROR | {_info['error']} |")
        else:
            _rows.append(f"| {_info['status']} | `{_name}` | {_info['rows']} × {_info['cols']} | OK |")

    mo.md(
        "## Results\n\n"
        "| Status | DataFrame | Shape | Details |\n"
        "|--------|-----------|-------|----------|\n"
        + "\n".join(_rows)
    )
    return


@app.cell
def _(results):
    # Show first rows of successfully loaded DataFrames
    _tabs = {}
    for _name, _info in results.items():
        if "error" not in _info:
            _df = load_precomputed_df(_name)
            _tabs[_name] = mo.ui.table(_df.head(10))

    mo.ui.tabs(_tabs) if _tabs else mo.md("*No DataFrames loaded successfully.*")
    return


if __name__ == "__main__":
    app.run()
