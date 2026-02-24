# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "polars>=0.19.0",
#     "galvani>=0.4.1",
#     "yadg>=6.2.0",
# ]
# ///

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import polars as pl
from galvani.BioLogic import MPRfile
from yadg.subcommands import extract as yadg_extract


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "apps" / "public" / "data"
OUT_DIR = DATA_DIR


def mpr_extract_metadata(path: Path, file_type: Optional[str] = None) -> tuple[dict, dict]:
    if file_type is None:
        suffix = path.suffix.lower()
        if suffix == ".mpr":
            file_type = "eclab.mpr"
        elif suffix == ".mpt":
            file_type = "eclab.mpt"
        else:
            raise ValueError(f"Unsupported suffix {path.suffix!r}. Provide file_type explicitly.")

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "meta.json"
        yadg_extract(filetype=file_type, infile=str(path), outfile=str(out), meta_only=True)
        meta_data = json.loads(out.read_text(encoding="utf-8")).get("/", {}).get("attrs", {})
        meta_settings = json.loads(meta_data.get("original_metadata", {})).get("settings", {})
        return meta_data, meta_settings


def mpr_get_technique(path: Path, file_type: Optional[str] = None) -> Optional[str]:
    _, settings = mpr_extract_metadata(path, file_type)
    return settings.get("technique")


def load_file(file_path: Path, technique_filter: Optional[list[str]] = None) -> Optional[pl.DataFrame]:
    with open(file_path, "rb") as handle:
        if file_path.suffix == ".mpr":
            if technique_filter is not None:
                technique = mpr_get_technique(file_path)
            else:
                technique = None

            if (technique_filter is None) or (technique in technique_filter):
                mpr = MPRfile(handle)
                dataframe = pl.DataFrame(mpr.data)

                if hasattr(mpr, "timestamp") and mpr.timestamp is not None:
                    start_dt = mpr.timestamp
                    dataframe = (
                        dataframe.with_columns(
                            (pl.col("time/s") * 1000).cast(pl.Duration("ms")).alias("time/dt")
                        )
                        .with_columns((pl.lit(start_dt) + pl.col("time/dt")).alias("datetime"))
                        .drop("time/dt")
                    )
                else:
                    created_dt = datetime.fromtimestamp(file_path.stat().st_ctime)
                    dataframe = (
                        dataframe.with_columns(
                            (pl.col("time/s") * 1000).cast(pl.Duration("ms")).alias("time/dt")
                        )
                        .with_columns((pl.lit(created_dt) + pl.col("time/dt")).alias("datetime"))
                        .drop("time/dt")
                    )
            else:
                return None
        elif file_path.suffix == ".csv":
            dataframe = pl.read_csv(handle)
        else:
            raise ValueError(f"Unsupported file type: {file_path.suffix}")

    return dataframe


def build_data_structure_df(data_dir: Path) -> pl.DataFrame:
    rows = [
        {
            "study_phase": study_phase.name,
            "participant": participant.name,
            "repetition": repetition.name,
            "flow_rate": flow_rate.name,
            "technique": technique.name,
            "file_path": str(file_path),
        }
        for study_phase in data_dir.iterdir()
        if study_phase.is_dir() and not study_phase.name.startswith(".")
        for participant in study_phase.iterdir()
        if participant.is_dir() and not participant.name.startswith(".")
        for repetition in participant.iterdir()
        if repetition.is_dir() and (not repetition.name.startswith(".") and "fail" not in repetition.name)
        for flow_rate in repetition.iterdir()
        if flow_rate.is_dir() and not flow_rate.name.startswith(".")
        for technique in flow_rate.iterdir()
        if technique.is_dir() and not technique.name.startswith(".")
        for file_path in technique.iterdir()
        if file_path.is_file() and not file_path.name.startswith(".") and file_path.suffix in [".mpr", ".csv"]
    ]

    dataframe = pl.DataFrame(
        rows,
        schema={
            "study_phase": pl.String,
            "participant": pl.String,
            "repetition": pl.Int16,
            "flow_rate": pl.Float64,
            "technique": pl.String,
            "file_path": pl.String,
        },
    )

    return dataframe.sort(["study_phase", "participant", "repetition", "flow_rate", "technique"])


def build_eis_flat_df(data_structure_df: pl.DataFrame) -> pl.DataFrame:
    dataframe_eis = data_structure_df.filter(pl.col("technique") == "01 eis")
    frames: list[pl.DataFrame] = []

    for row in dataframe_eis.iter_rows(named=True):
        try:
            data = load_file(Path(row["file_path"]), ["PEIS", "GEIS"])
        except Exception:
            continue

        if data is None:
            continue

        data = data.rename({"cycle number": "cycle"}, strict=False)
        frames.append(
            data.with_columns(
                pl.lit(row["study_phase"]).alias("study_phase"),
                pl.lit(row["participant"]).alias("participant"),
                pl.lit(row["repetition"]).alias("repetition"),
                pl.lit(row["flow_rate"]).alias("flow_rate"),
            ).select(
                [
                    "study_phase",
                    "participant",
                    "repetition",
                    "flow_rate",
                    *[
                        col
                        for col in data.columns
                        if col not in ["study_phase", "participant", "repetition", "flow_rate"]
                    ],
                ]
            )
        )

    return pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame()


def build_polarisation_flat_df(data_structure_df: pl.DataFrame) -> pl.DataFrame:
    dataframe_pol = data_structure_df.filter(pl.col("technique") == "02 polarisation")
    frames: list[pl.DataFrame] = []

    for row in dataframe_pol.iter_rows(named=True):
        try:
            data = load_file(Path(row["file_path"]), ["CP"])
        except Exception:
            continue

        if data is None:
            continue

        data = data.rename(
            {
                "<I>/mA": "current/mA",
                "I/mA": "current/mA",
                "<Ewe>/V": "voltage/V",
                "Ewe/V": "voltage/V",
                "cycle number": "cycle",
            },
            strict=False,
        )

        frames.append(
            data.with_columns(
                pl.lit(row["study_phase"]).alias("study_phase"),
                pl.lit(row["participant"]).alias("participant"),
                pl.lit(row["repetition"]).alias("repetition"),
                pl.lit(row["flow_rate"]).alias("flow_rate"),
            ).select(
                [
                    "study_phase",
                    "participant",
                    "repetition",
                    "flow_rate",
                    *[
                        col
                        for col in data.columns
                        if col not in ["study_phase", "participant", "repetition", "flow_rate"]
                    ],
                ]
            )
        )

    return pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame()


def build_cd_cycling_flat_df(data_structure_df: pl.DataFrame) -> pl.DataFrame:
    dataframe_cd = data_structure_df.filter(pl.col("technique") == "03 charge-discharge")
    frames: list[pl.DataFrame] = []

    for row in dataframe_cd.iter_rows(named=True):
        try:
            data = load_file(Path(row["file_path"]), ["GCPL"])
        except Exception:
            continue

        if data is None:
            continue

        data = data.rename(
            {
                "<I>/mA": "current/mA",
                "I/mA": "current/mA",
                "<Ewe>/V": "voltage/V",
                "Ewe/V": "voltage/V",
            },
            strict=False,
        )

        if "current/mA" not in data.columns and "dq/mA.h" in data.columns:
            data = data.with_columns(
                (
                    pl.col("dq/mA.h").diff().fill_null(0)
                    / pl.col("time/s").diff().fill_null(1)
                    * 3600
                ).alias("current/mA")
            )

        frames.append(
            data.with_columns(
                pl.lit(row["study_phase"]).alias("study_phase"),
                pl.lit(row["participant"]).alias("participant"),
                pl.lit(row["repetition"]).alias("repetition"),
                pl.lit(row["flow_rate"]).alias("flow_rate"),
            ).select(
                [
                    "study_phase",
                    "participant",
                    "repetition",
                    "flow_rate",
                    *[
                        col
                        for col in data.columns
                        if col not in ["study_phase", "participant", "repetition", "flow_rate"]
                    ],
                ]
            )
        )

    return pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame()


def build_temperature_data_df(data_dir: Path) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    for study_phase in data_dir.iterdir():
        if not study_phase.is_dir() or study_phase.name.startswith("."):
            continue

        temp_dir = study_phase / "Temperature"
        if not temp_dir.exists() or not temp_dir.is_dir():
            continue

        target_csv = temp_dir / "DL-200T_temperature.csv"
        if not target_csv.exists():
            csv_candidates = sorted(temp_dir.glob("*.csv"))
            if not csv_candidates:
                continue
            target_csv = csv_candidates[0]

        temperature_data_df = pl.read_csv(
            target_csv,
            try_parse_dates=True,
            decimal_comma=True,
        ).with_columns(
            (
                pl.col("datetime").cast(pl.Datetime)
                - pl.col("datetime").cast(pl.Datetime).min()
            )
            .dt.total_seconds(fractional=True)
            .alias("time/s"),
            pl.lit(study_phase.name).alias("study_phase"),
        ).select(
            pl.col("study_phase"),
            pl.col("datetime"),
            pl.col("time/s"),
            pl.col("temperature_C").cast(pl.Float64).alias("temperature/°C"),
        )
        frames.append(temperature_data_df)

    return pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    data_structure_df = build_data_structure_df(DATA_DIR)
    eis_flat_df = build_eis_flat_df(data_structure_df)
    polarisation_flat_df = build_polarisation_flat_df(data_structure_df)
    cd_cycling_flat_df = build_cd_cycling_flat_df(data_structure_df)
    temperature_data_df = build_temperature_data_df(DATA_DIR)

    data_structure_df.write_parquet(OUT_DIR / "data_structure_df.parquet")
    eis_flat_df.write_parquet(OUT_DIR / "eis_flat_df.parquet")
    polarisation_flat_df.write_parquet(OUT_DIR / "polarisation_flat_df.parquet")
    cd_cycling_flat_df.write_parquet(OUT_DIR / "cd_cycling_flat_df.parquet")
    temperature_data_df.write_parquet(OUT_DIR / "temperature_data_df.parquet")

    print("✅ Precompute finished")
    print(f"  data_structure_df: {data_structure_df.height} rows")
    print(f"  eis_flat_df: {eis_flat_df.height} rows")
    print(f"  polarisation_flat_df: {polarisation_flat_df.height} rows")
    print(f"  cd_cycling_flat_df: {cd_cycling_flat_df.height} rows")
    print(f"  temperature_data_df: {temperature_data_df.height} rows")


if __name__ == "__main__":
    main()
