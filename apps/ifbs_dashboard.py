# /// script
# name = "ifbs-data-dashboard"
# version = "0.1.0"
# description = "Notebook for visualizing the IFBS data"
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
    app_title="International Flow Battery Study – Data Dashboard",
)

with app.setup:
    import marimo as mo
    import sys
    from pathlib import Path
    from typing import Any, Optional
    from datetime import datetime

    # detect WASM runtime (deployed marimo notebook in browser/pyodide)
    # must be defined before conditional imports below
    def is_wasm() -> bool:
        return sys.platform == "emscripten"

    # data handling
    import tempfile
    import json
    import polars as pl

    # computation
    from functools import partial
    from scipy.stats import linregress
    import numpy as np

    # visualization
    import altair as alt

    if is_wasm():
        alt.data_transformers.enable("default")
    else:
        alt.data_transformers.enable("vegafusion")


@app.cell(hide_code=True)
def _():
    # FILE I/O HELPERS
    # Isolated in their own cell so that changes to computation helpers
    # do not invalidate the persistent cache for file loading.

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
    
    @mo.persistent_cache
    def load_precomputed_df(name: str) -> pl.DataFrame:
        _relative = f"public/data/{name}.parquet"
        # Use mo.notebook_location() in all modes to resolve relative to notebook dir
        _source = mo.notebook_location() / _relative

        if is_wasm():
            import pyarrow.parquet as pq

            _source_str = str(_source)
            # PurePosixPath collapses https:// to https:/ — restore double slash
            for _scheme in ("https:/", "http:/"):
                if _source_str.startswith(_scheme) and not _source_str.startswith(
                    _scheme + "/"
                ):
                    _source_str = _scheme + "/" + _source_str[len(_scheme) :]
                    break
            _local_path = _ensure_local(_source_str)
            # polars' native parquet reader is not available in Pyodide/WASM,
            # so we use pyarrow to read and convert to polars
            _arrow_table = pq.read_table(str(_local_path))
            return pl.from_arrow(_arrow_table)

        return pl.read_parquet(_source)

    # re-calculate time/s of a dataframe based on datetime
    def recalculate_time(df: pl.DataFrame) -> pl.DataFrame:
        if "datetime" in df.columns:
            df = (
                df
                .sort(["study_phase", "participant", "repetition", "flow_rate", "datetime"])
                .with_columns(
                    (
                        (
                            pl.col("datetime")
                            - pl.col("datetime").first().over(
                                "study_phase",
                                "participant",
                                "repetition",
                                "flow_rate",
                            )
                        )
                        .dt.total_nanoseconds()
                        .cast(pl.Float64)
                        / 1_000_000_000.0
                    ).alias("time/s")
                )
            )

        return df

    return load_precomputed_df, recalculate_time


@app.cell(hide_code=True)
def _():
    # COMPUTATION HELPERS

    def get_x_intercepts(
        df: pl.DataFrame | pl.LazyFrame,
        *,
        x: str = "x",
        y: str = "y",
        group: str = "dataset",
        which: str = "all",  # "all" | "first" | "last" | "closest_to_zero"
        assume_sorted: bool = False,
    ) -> pl.DataFrame:
        """
        Compute x-axis intercept(s) (roots where y == 0) per group via vectorized
        sign-change detection + linear interpolation between adjacent samples.

        Requirements:
          - df must be a Polars DataFrame or LazyFrame (NOT a Series)
          - columns: group, x, y must exist and be numeric (x,y)

        Performance:
          - O(n) if assume_sorted=True and already sorted by [group, x]
          - otherwise includes a sort (O(n log n))
          - runs lazily if df is LazyFrame; collects only at the end
        """

        if isinstance(df, pl.Series):
            raise TypeError(
                "get_x_intercepts expected a Polars DataFrame/LazyFrame, got a Series. "
                "Pass the full table (with group/x/y columns), not df['col']."
            )

        lf = df.lazy() if isinstance(df, pl.DataFrame) else df

        # Ensure we are sorting a frame, not a Series
        if not assume_sorted:
            lf = lf.sort([group, x])

        x_c = pl.col(x)
        y_c = pl.col(y)

        lf = lf.with_columns(
            [
                x_c.shift(1).over(group).alias("_x0"),
                y_c.shift(1).over(group).alias("_y0"),
            ]
        ).filter(pl.col("_y0").is_not_null())

        # Crossing condition (handles exact zeros and sign flips)
        crosses = (
            (y_c == 0) | (pl.col("_y0") == 0) | (y_c.sign() != pl.col("_y0").sign())
        )

        # Interpolation: x0 - y0*(x-x0)/(y-y0) (avoid div0 by handling exact zeros above)
        lf = (
            lf.filter(crosses)
            .with_columns(
                pl.when(y_c == 0)
                .then(x_c)
                .when(pl.col("_y0") == 0)
                .then(pl.col("_x0"))
                .otherwise(
                    pl.col("_x0")
                    - pl.col("_y0") * (x_c - pl.col("_x0")) / (y_c - pl.col("_y0"))
                )
                .alias("x_intercept")
            )
            .select([pl.col(group), pl.col("x_intercept")])
        )

        if which == "all":
            return lf.collect()

        if which == "first":
            return (
                lf.group_by(group)
                .agg(pl.col("x_intercept").min().alias("x_intercept"))
                .collect()
            )

        if which == "last":
            return (
                lf.group_by(group)
                .agg(pl.col("x_intercept").max().alias("x_intercept"))
                .collect()
            )

        if which == "closest_to_zero":
            return (
                lf.group_by(group)
                .agg(
                    pl.col("x_intercept")
                    .sort_by(pl.col("x_intercept").abs())
                    .first()
                    .alias("x_intercept")
                )
                .collect()
            )

        raise ValueError(
            "which must be one of: 'all', 'first', 'last', 'closest_to_zero'."
        )

    # define evaluation parameters
    def get_linregress_params(
        df: pl.DataFrame, x_name: str, y_name: str, with_columns: list
    ) -> pl.DataFrame:

        # sort data by x values for consistent results
        df = df.sort(x_name)

        # linear regression: x vs y
        if df.height > 2:
            x_vals = df[x_name].to_numpy()
            y_vals = df[y_name].to_numpy()

            # perform linear regression
            linregress_res = linregress(x_vals, y_vals)
        else:
            linregress_res = None

        return pl.DataFrame(
            {
                "slope": [linregress_res.slope if linregress_res else None],
                "intercept": [linregress_res.intercept if linregress_res else None],
                "rvalue": [linregress_res.rvalue if linregress_res else None],
                "pvalue": [linregress_res.pvalue if linregress_res else None],
                "stderr": [linregress_res.stderr if linregress_res else None],
            }
        ).join(
            df.select(with_columns).limit(1),
            how="cross",
        )

    return get_linregress_params, get_x_intercepts


@app.cell(hide_code=True)
def _():
    # CHART HELPERS

    # Enable zooming only x or only y as well (using Shift / Alt-Keys)
    # NOTE: Need to add `.add_params(wheel_zoom_xy, wheel_zoom_x, wheel_zoom_y)` to an chart that already has `.interactive()`on it
    wheel_zoom_xy = alt.selection_interval(
        bind="scales", encodings=["x", "y"], zoom="wheel"
    )
    wheel_zoom_x = alt.selection_interval(
        bind="scales", encodings=["x"], zoom="wheel![!event.shiftKey]"
    )
    wheel_zoom_y = alt.selection_interval(
        bind="scales", encodings=["y"], zoom="wheel![!event.altKey]"
    )
    return wheel_zoom_x, wheel_zoom_xy, wheel_zoom_y


@app.cell
def _(study_phase_selector):
    # STUDY META DATA VARIABLES

    # Phase 2a
    phase_2a_theoretical_capacity_mAh = 33.06 * 26.8 * 0.2  # mAh, based on 0.2 M redox species in 33.06 mL electrolyte

    # Phase 2b
    phase_2b_theoretical_capacity_mAh = 100 * 26.8 * 0.2  # mAh, based on 0.2 M redox species in 100 mL electrolyte

    # SELECT VARIABLE SET BASED ON STUDY PHASE SELECTION
    theoretical_capacity_mAh = (
        phase_2a_theoretical_capacity_mAh
        if study_phase_selector.value == "phase_2a"
        else phase_2b_theoretical_capacity_mAh
    )
    return (theoretical_capacity_mAh,)


@app.cell
def _(
    cd_cycling_filtered_capacity_fade_time,
    cd_cycling_initial_discharge_capacity,
    data_structure_df,
    study_phase_selector,
    theoretical_capacity_mAh,
):
    # STUDY METRICS SUMMARY

    stat_phase = mo.stat(
        value=f"{study_phase_selector.value.capitalize().replace("_", " ")}",
        label="Study Phase",
        caption="Number of participants",
    ).style(
        padding="0px",          # optional, damit der Rahmen nicht “auf Kante” sitzt
        border="1px solid #aaaaaa",
        border_radius="5px",
        background_color="#f8f8f8",
    )

    stat_participants = mo.stat(
        value=f"{data_structure_df['participant'].unique().len()}",
        label="Participants",
        caption="Number of participants",
    ).style(
        padding="0px",          # optional, damit der Rahmen nicht “auf Kante” sitzt
        border="1px solid #aaaaaa",
        border_radius="5px",
        background_color="#f8f8f8",
    )

    stat_experiments = mo.stat(
        value=f"{len(
            data_structure_df
            .filter(
                pl.col("study_phase").is_in([study_phase_selector.value])
            )
            .group_by(
                "study_phase",
                "participant",
                "repetition",
            )
            .count()
            .sort(["study_phase", "participant", "repetition"])
        )}",
        label="Experiments",
        caption="Number of experiments",
    ).style(
        padding="0px",          # optional, damit der Rahmen nicht “auf Kante” sitzt
        border="1px solid #aaaaaa",
        border_radius="5px",
        background_color="#f8f8f8",
    )

    stat_capacity = mo.stat(
        value=f"{(
            cd_cycling_initial_discharge_capacity["capacity/mAh"].mean()
        ):.1f} ± {(
            cd_cycling_initial_discharge_capacity["capacity/mAh"].std()
        ):.1f}",
        label="Initial Capacity (mAh)",
        caption="Average over all experiments",
    ).style(
        padding="0px",          # optional, damit der Rahmen nicht “auf Kante” sitzt
        border="1px solid #aaaaaa",
        border_radius="5px",
        background_color="#f8f8f8",
    )

    stat_capacity_utilization = mo.stat(
        value=f"{(
            (cd_cycling_initial_discharge_capacity["capacity/mAh"] / theoretical_capacity_mAh * 100).mean()
        ):.1f} ± {(
        (cd_cycling_initial_discharge_capacity["capacity/mAh"] / theoretical_capacity_mAh * 100).std()
        ):.1f}",
        label="Capacity Utilization (%)",
        caption="Average over all experiments",
    ).style(
        padding="0px",          # optional, damit der Rahmen nicht “auf Kante” sitzt
        border="1px solid #aaaaaa",
        border_radius="5px",
        background_color="#f8f8f8",
    )

    stat_fade_rate = mo.stat(
        value=f"{(
            cd_cycling_filtered_capacity_fade_time['capacity_fade_rate/%/d'].mean()
        ):.2f} ± {(
            cd_cycling_filtered_capacity_fade_time['capacity_fade_rate/%/d'].std()
        ):.2f}",
        label="Capacity Fade (% d⁻¹)",
        caption="Average over all experiments",
        direction=f"{"increase" if cd_cycling_filtered_capacity_fade_time['capacity_fade_rate/%/d'].mean() > 0 else "decrease"}",
    ).style(
        padding="0px",          # optional, damit der Rahmen nicht “auf Kante” sitzt
        border="1px solid #aaaaaa",
        border_radius="5px",
        background_color="#f8f8f8",
    )

    mo.vstack([

        mo.hstack([
            stat_phase,
            stat_participants,
            stat_experiments,
            stat_capacity, 
            stat_capacity_utilization,
            stat_fade_rate,
        ], justify="start", gap="1"),

    ])
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # International Flow Battery Study

    ## Data Visualization Dashboard

    This notebook is designed to visualize the data from the experiments of the international flow battery reproducibility study (internal data of FSU Jena and HIPOLE Jena). It includes three main sections representing the performed experiments: Impedance Spectroscopy, Polarisation, and Charge-Discharge Cycling. First, select a study phase and then the relevant data from the list of participants, repetitions, and flow rates to visualize the corresponding data in the sections below.
    """)
    return


@app.cell
def _(load_precomputed_df):
    # main data directory
    # Note: The expected folder structure is the following:
    #
    # data_dir/
    # ├── phase_1/
    # │   ├── participant_1/
    # │   │   ├── 1/
    # │   │   │   ├── flow_rate_1/
    # │   │   │   │   ├── test_technique_1/
    # │   │   │   │   │   ├── file_1
    # │   │   │   │   │   ├── file_2
    # │   │   │   │   ├── test_technique_2/
    # │   │   │   │   │   ├── file_1
    # │   │   │   │   │   ├── file_2
    # │   │   │   ├── flow_rate_2/
    # │   │   │   │   ├── test_technique_1/
    # │   │   │   │   │   ├── file_1
    # │   │   │   │   │   ├── file_2
    # │   │   │   │   ├── test_technique_2/
    # │   │   │   │   │   ├── file_1
    # │   │   │   │   │   ├── file_2
    # │   │   ├── 2/
    # │   │   │   ├── [...]
    # │   ├── participant_2/
    # │   │   ├── [...]
    # ├── phase_2/
    # │   ├── [...]
    data_dir = Path(str(mo.notebook_location() / "data"))
    if not data_dir.exists():
        data_dir = Path(str(mo.notebook_location() / "public" / "data"))

    data_structure_df = load_precomputed_df("data_structure_df").with_columns(
        pl.col("study_phase").cast(pl.String),
        pl.col("participant").cast(pl.String),
        pl.col("repetition").cast(pl.Int16),
        pl.col("flow_rate").cast(pl.Float64),
        pl.col("technique").cast(pl.String),
        pl.col("file_path").cast(pl.String),
        )
 
    # sort the dataframe
    data_structure_df = data_structure_df.sort(
        ["study_phase", "participant", "repetition", "flow_rate", "technique"]
    )
    return data_dir, data_structure_df

@app.cell
def _(data_structure_df):
    # create dropdown for study phase selection
    study_phase_selector = mo.ui.dropdown(
        options={
            v: v for v in data_structure_df["study_phase"].unique().sort().to_list()
        },
        value=data_structure_df["study_phase"].unique().sort().first(),
        label="**Study phase selection:**",
        full_width=True,
        searchable=True,
    )
    return (study_phase_selector,)


@app.cell
def _(data_structure_df, study_phase_selector):
    # filter based on study phase selection
    _data_structure_df_filtered = (
        data_structure_df
            .filter(
                pl.col("study_phase").is_in([study_phase_selector.value])
            )["participant"]
            .unique()
            .sort()
    )

    # create multiselector for participant selection
    participant_selector = mo.ui.multiselect(
        options=_data_structure_df_filtered.to_list(),
        value=_data_structure_df_filtered.to_list(),
        label="**Participant selection:**",
        full_width=True,
    )
    return (participant_selector,)


@app.cell
def _(data_structure_df, participant_selector, study_phase_selector):
    # filter based on study phase and participants selection
    _data_structure_df_filtered = (
        data_structure_df
            .filter(
                pl.col("study_phase") == study_phase_selector.value,
                pl.col("participant").is_in(participant_selector.value),
            )["repetition"]
            .unique()
            .sort()
    )

    # create multiselectors for repetitions selection
    repetition_selector = mo.ui.multiselect(
        options=_data_structure_df_filtered,
        value=_data_structure_df_filtered,
        label="**Repetition selection:**",
        full_width=True,
    )
    return (repetition_selector,)


@app.cell
def _(
    data_structure_df,
    participant_selector,
    repetition_selector,
    study_phase_selector,
):
    # filter based on study phase and participants selection
    _data_structure_df_filtered = (
        data_structure_df
            .filter(
                pl.col("study_phase").is_in([study_phase_selector.value]),
                pl.col("participant").is_in(participant_selector.value),
                pl.col("repetition").is_in(repetition_selector.value),
            )["flow_rate"]
            .unique()
            .sort()
    )

    flow_rate_selector = mo.ui.multiselect(
        options=_data_structure_df_filtered.to_list(),
        value=_data_structure_df_filtered.to_list(),
        label="**Flow rate selection:**",
        full_width=True,
    )
    return (flow_rate_selector,)


@app.cell
def _(
    flow_rate_selector,
    participant_selector,
    repetition_selector,
    study_phase_selector,
):
    # display the selectors in a row
    mo.vstack(
        [
            mo.md("### Data filter"),
            mo.md(
                "Use the selectors below to filter the study data based on the study phase, participant, repetition, and flow rate. You can select multiple options for each category to compare different conditions. The visualizations in the sections below will update accordingly to reflect the selected data."
            ),
            mo.hstack(
                [
                    study_phase_selector,
                    participant_selector,
                    repetition_selector,
                    flow_rate_selector,
                ],
                gap=0,
            ),
        ]
    )
    return


@app.cell
def _(
    data_structure_df,
    flow_rate_selector,
    participant_selector,
    repetition_selector,
    study_phase_selector,
):
    mo.lazy(
        data_structure_df.filter(
            pl.col("study_phase").is_in([study_phase_selector.value])
            & pl.col("participant").is_in(participant_selector.value)
            & pl.col("repetition").is_in(repetition_selector.value)
            & pl.col("flow_rate").is_in(flow_rate_selector.value)

        ), show_loading_indicator=True

    )
    return


@app.cell
def _(load_precomputed_df, study_phase_selector):
    # PARTICIPANT SCHEDULES & TEMPERATURE DATA EVALUATION
    # STEP 1: Load the temperature data from the file and prepare it for visualization

    temperature_data_df = (
        load_precomputed_df("temperature_data_df")
        .filter(pl.col("study_phase") == study_phase_selector.value)
        .select(
            pl.col("datetime").cast(pl.Datetime),
            pl.col("time/s").cast(pl.Float64),
            pl.col("temperature/°C").cast(pl.Float64),
        )
    )
    
    return (temperature_data_df,)


@app.cell
def _(load_precomputed_df):
    # LOAD DATA FROM PRECOMPUTED DATAFRAMES

    eis_flat_df = load_precomputed_df("eis_flat_df")
    polarisation_flat_df = load_precomputed_df("polarisation_flat_df")
    cd_cycling_flat_df = load_precomputed_df("cd_cycling_flat_df")
    
    return (eis_flat_df, polarisation_flat_df, cd_cycling_flat_df,)


@app.cell
def _(temperature_data_df):
    # PARTICIPANT SCHEDULES & TEMPERATURE DATA EVALUATION
    # STEP 2a: Build an area chart to visualize the temperature data over time

    # reduce data to mean, min, and max values per 12h
    temperature_data_filtered_df = (
        temperature_data_df
        .with_columns(
            # truncate datetime to 12h bins for grouping
            # (e.g., 2024-01-01 08:15 -> 2024-01-01 00:00, 
            #        2024-01-01 14:30 -> 2024-01-01 12:00, 
            # etc.)
            pl.col("datetime").dt.truncate("12h").alias("t_bin")
        )
        .group_by(["t_bin"])
        .agg(
            # aggregate mean, min, and max value per 12h bin
            pl.col("temperature/°C").mean().alias("temp_mean"),
            pl.col("temperature/°C").min().alias("temp_min"),
            pl.col("temperature/°C").max().alias("temp_max"),
        )
        .sort(["t_bin"])
    )

    # get domain for the temperature values with some padding for better visualization
    _all_min = temperature_data_filtered_df["temp_min"]
    _all_max = temperature_data_filtered_df["temp_max"]
    _temperature_domain = [_all_min.min() - 0.1, _all_max.max() + 0.1]

    # build chart with mean value as line and min-max range as band
    # A) Base chart to add mean line and band
    base = alt.Chart(
        temperature_data_filtered_df
    ).encode(
        x=alt.X("t_bin:T", title=""),
    )

    # B) Band for min-max range
    band = base.mark_area(
        interpolate="monotone",
        color="orange",
        opacity=0.35,
    ).encode(
        y=alt.Y("temp_min:Q", title="Temperature / °C", scale=alt.Scale(domain=_temperature_domain), stack=None),
        y2=alt.Y2("temp_max:Q"),
    )

    # C) Mean line
    mean_line = base.mark_line(
        point=alt.OverlayMarkDef(
            shape="circle",
            size=50,
            color="darkorange",
        ),
        color="darkorange",
        interpolate="monotone",
    ).encode(
        y=alt.Y("temp_mean:Q", title="Temperature / °C", scale=alt.Scale(domain=_temperature_domain), stack=None),
        tooltip=[
        alt.Tooltip("t_bin:T", title="Datetime", format="%Y-%m-%d %H:%M:%S"),
        alt.Tooltip("temp_max:Q", title="Max / °C", format=".2f"),
        alt.Tooltip("temp_mean:Q", title="Mean / °C", format=".2f"),
        alt.Tooltip("temp_min:Q", title="Min / °C", format=".2f"),
        ],
    )

    temperature_time_chart = (
        alt.layer(band + mean_line)
        .properties(
            width=975,
            height=150,
        )
    )

    return (temperature_time_chart,)


@app.cell
def _(
    cd_cycling_filtered_df,
    eis_filtered_df,
    flow_rate_selector,
    participant_selector,
    polarisation_filtered_df,
    repetition_selector,
    study_phase_selector,
    temperature_time_chart,
    wheel_zoom_x,
    wheel_zoom_xy,
    wheel_zoom_y,
):
    # PARTICIPANT SCHEDULES & TEMPERATURE DATA EVALUATION
    # STEP 2b: Build a Gantt chart showing the experiment time ranges for each participant and experiment technique, and overlay it with the temperature data

    # create a dataframe containing the start times of the first experiment of a participant and the end time of the last experiment of a participant (within a study phase) over all repetitions for each of the experiment phases (Impedance, Polarisation, Charge-discharge cycling)). The dataframe should have columns (study_phase, participant, technique, start_time/s, end_time/s), where technique is the experiment technique.
    def _ranges(df, typ):
        return (
            df.filter(
                pl.col("study_phase").is_in([study_phase_selector.value])
                & pl.col("participant").is_in(participant_selector.value)
                & pl.col("repetition").is_in(repetition_selector.value)
                & pl.col("flow_rate").is_in(flow_rate_selector.value)
            )
            .group_by(
                "study_phase", 
                "participant",
                "repetition",
            ).agg(
                pl.col("datetime").min().alias("start_datetime"),
                pl.col("datetime").max().alias("end_datetime"),
            )
            .with_columns(
                pl.lit(typ).alias("technique")
            )
            .select(
                "study_phase",
                "participant",
                "repetition",
                "technique",
                pl.col("start_datetime").cast(pl.Datetime),
                pl.col("end_datetime").cast(pl.Datetime),
            )
        )

    _experiment_schedules = (
        pl.DataFrame(schema={
            "study_phase": pl.String,
            "participant": pl.String,
            "repetition": pl.Int32,
            "technique": pl.String,
            "start_datetime": pl.Datetime,
            "end_datetime": pl.Datetime,
        })
        .vstack(_ranges(eis_filtered_df, "Impedance"))
        .vstack(_ranges(polarisation_filtered_df, "Polarisation"))
        .vstack(_ranges(cd_cycling_filtered_df, "Charge-discharge"))
        .sort(["study_phase", "start_datetime"])
    )

    # create a Gantt chart visualizing the experiment time ranges for each participant and experiment technique, with the x-axis showing the time in days and the y-axis showing the participant. The bars should be colored by experiment technique and have tooltips showing the study phase, participant, experiment technique, start time, and end time.
    experiment_schedule_chart = (
        alt.Chart(_experiment_schedules)
        .mark_bar()
        .encode(
            x=alt.X("start_datetime:T", title=""),
            x2="end_datetime:T",
            y=alt.Y("participant:N", title=""),
            yOffset=alt.YOffset("technique:N", sort=["01 impedance", "02 polarisation", "03 charge-discharge"]),
            color=alt.Color("technique:N", title="Technique"),
            tooltip=[
                "study_phase:N",
                "participant:N",
                "technique:N",
                alt.Tooltip("start_datetime:T", title="Start time"),
                alt.Tooltip("end_datetime:T", title="End time"),
            ],
        )
        .properties(
            width=975,
            height=150,
        )
    )

    # create a combined chart overlaying the temperature data on the experiment schedule chart
    combined_temperature_chart = (
        alt.vconcat(
            experiment_schedule_chart,
            temperature_time_chart,
        )
        .resolve_scale(x="shared")
        .properties(
            title=alt.TitleParams(
                text="Figure 13. Experiment time ranges with temperature data",
                subtitle=[
                    "Combined Gantt chart and line chart visualizing the experiment schedules per participant, along with the temperature data over time. The Gantt chart displays the time ranges of the different", 
                    "techniques: Impedance spectroscopy (orange), polarisation (red), and charge-discharge cycling (blue) for each participant. while the line chart shows the temperature data over time.The x-axis", 
                    " is shared between the two charts to allow for easy comparison of the experiment schedules with the temperature data.",
                ],
                anchor="start",
                orient="top",
                offset=20,
            )
        )
        .interactive()
        .add_params(wheel_zoom_xy, wheel_zoom_x, wheel_zoom_y)
        .configure_legend(
            title=None,
            orient="top",
            direction='horizontal',
            disable=True,
        )
    )

    return (combined_temperature_chart,)


@app.cell
def _(combined_temperature_chart, temperature_data_df):
    # PARTICIPANT SCHEDULES & TEMPERATURE DATA EVALUATION
    # STEP 3: Display the content of the section and explain what it does

    mo.vstack(
        [
            mo.md("## Participant schedules and temperature data"),
            mo.md("""
                This section displays the participant schedules and the temperature data recorded during the experiments. It was recorded by a Voltcraft DL-200T temperature logger at a sampling rate of one measurement every 60 s. The sensor was positioned at a central spot on a shelf within the laboratory (approximately 1 – 1.5 m away from each of the RFB experiments).
            """),
            mo.md("<br>"),
            mo.md("### Raw data exploration"),
            mo.md("""
                The expandable sections enables you to explore the raw temperature data in more detail. You can view the data in a tabular format and apply filter and custom computations or use the interactive data explorer to filter, sort, and visualize the data as needed. While the functions are limited, it may help you gain a better understanding of the underlying data beyond the prepared visualizations below.
            """),
            mo.accordion(
                {
                    "Data table": temperature_data_df,
                    # "Data explorer": mo.ui.data_explorer(temperature_data_df),
                },
                lazy=True,
                multiple=True,
            ),
            mo.md("<br>"),
            mo.md("### Participant schedules and temperature over time"),
            mo.md(f"""
                The plot shows the participant schedules and the temperature data over time. You can use this plot to analyze the temperature behavior during the experiments and identify trends or differences between different time periods. The **average temperature** over the recorded time period was **{temperature_data_df["temperature/°C"].mean():.1f} °C ± {(temperature_data_df["temperature/°C"].std() if len(temperature_data_df) > 1 else 0):.1f} °C** (uncertainty: standard deviation) with a **minimum temperature of {temperature_data_df["temperature/°C"].min()} °C** and **maximum temperature of {temperature_data_df["temperature/°C"].max()} °C**.
            """),
            mo.md("<br>"),
            mo.lazy(combined_temperature_chart, show_loading_indicator=True),
        ]
    )
    return

@app.cell
def _(
    eis_flat_df,
    flow_rate_selector,
    participant_selector,
    recalculate_time,
    repetition_selector,
    study_phase_selector,
):
    # IMPEDANCE SPECTROSCOPY EVALUATION
    # STEP 1b: Filter the EIS data according to the UI selectors

    # apply UI filter to the flat EIS DataFrame
    eis_filtered_df = eis_flat_df.filter(
        pl.col("study_phase").is_in([study_phase_selector.value])
        & pl.col("participant").is_in(participant_selector.value)
        & pl.col("repetition").is_in(repetition_selector.value)
        & pl.col("flow_rate").is_in(flow_rate_selector.value)
    )
    mo.stop(
        eis_filtered_df.is_empty(),
    )

    # recalculate time/s from datetime column for each group (study_phase, participant, repetition, flow_rate)
    # NOTE: We do this to properly handle multiple files in one experiment folder and then keep only the last cycle in the next step
    eis_filtered_df = recalculate_time(eis_filtered_df)

    # keep only the last cycle of each group
    eis_filtered_df = (

        eis_filtered_df.with_columns(
            pl.col("cycle").max().over(
                "study_phase", 
                "participant", 
                "repetition", 
                "flow_rate"
            )
            .alias("max_cycle")
        ).filter(
            pl.col("cycle") == pl.col("max_cycle")
        ).drop("max_cycle")
    )
    return (eis_filtered_df,)


@app.cell
def _(eis_filtered_df, wheel_zoom_x, wheel_zoom_xy, wheel_zoom_y):
    # IMPEDANCE SPECTROSCOPY EVALUATION
    # STEP 2: Plot the Nyquist plots for the selected files

    # compute per-axis data ranges, then build centered domains with equal span
    _re_min = eis_filtered_df["Re(Z)/Ohm"].min()
    _re_max = eis_filtered_df["Re(Z)/Ohm"].max()
    _im_min = eis_filtered_df["-Im(Z)/Ohm"].min()
    _im_max = eis_filtered_df["-Im(Z)/Ohm"].max()

    # use the larger of the two ranges so both axes cover the same span
    _re_range = _re_max - _re_min
    _im_range = _im_max - _im_min
    _max_range = max(_re_range, _im_range)
    _padding = _max_range * 0.05

    # center each axis's domain around its own midpoint
    _re_mid = (_re_min + _re_max) / 2
    _im_mid = (_im_min + _im_max) / 2
    _half = (_max_range / 2) + _padding
    _re_domain = [_re_mid - _half, _re_mid + _half]
    _im_domain = [_im_mid - _half, _im_mid + _half]

    # create selectors and bind them to the legend
    _participant_selection = alt.selection_point(fields=["participant"], bind="legend")
    _repetition_selection = alt.selection_point(fields=["repetition"], bind="legend")
    _flow_rate_selection = alt.selection_point(fields=["flow_rate"], bind="legend")

    # select only columns needed for the chart
    _chart_data = eis_filtered_df.select(
        [
            "study_phase",
            "participant",
            "repetition",
            "flow_rate",
            "cycle",
            "Re(Z)/Ohm",
            "-Im(Z)/Ohm",
            "freq/Hz",
        ]
    )

    # build Nyquist plot from single flat DataFrame
    nyquist_plots = (
        (
            alt.Chart(_chart_data)
            .mark_point()
            .encode(
                x=alt.X(
                    "Re(Z)/Ohm:Q",
                    title="Re(Z) / Ω",
                    scale=alt.Scale(domain=_re_domain),
                ),
                y=alt.Y(
                    "-Im(Z)/Ohm:Q",
                    title="-Im(Z) / Ω",
                    scale=alt.Scale(domain=_im_domain),
                ),
                color=alt.Color("participant:N", title="Participant"),
                shape=alt.Shape("repetition:N", title="Repetition"),
                size=alt.Size(
                    "flow_rate:N",
                    title="Flow Rate (mL min⁻¹)",
                    scale=alt.Scale(range=[30, 150]),
                ),
                opacity=alt.condition(
                    _participant_selection
                    & _repetition_selection
                    & _flow_rate_selection,
                    alt.value(1.0),
                    alt.value(0.025),
                ),
                tooltip=[
                    "study_phase:O",
                    "participant:N",
                    "repetition:O",
                    "flow_rate:O",
                    "cycle:O",
                    alt.Tooltip("freq/Hz:Q", format=".1f"),
                    "Re(Z)/Ohm:Q",
                    "-Im(Z)/Ohm:Q",
                ],
            )
            .properties(
                title="Nyquist Plot",
                width=400,
                height=400,
            )
            .add_params(
                _participant_selection,
                _repetition_selection,
                _flow_rate_selection,
            )
        )
        .properties(
            title=alt.TitleParams(
                text="Figure 1. Nyquist plots for selected participants and repetitions",
                subtitle="Nyquist plots showing the real and imaginary parts of the impedance for each selected file.",
                anchor="start",
                orient="top",
                offset=20,
            )
        )
        .interactive()
        .add_params(wheel_zoom_xy, wheel_zoom_x, wheel_zoom_y)
    )
    return (nyquist_plots,)


@app.cell
def _(eis_filtered_df, get_x_intercepts):
    # IMPEDANCE SPECTROSCOPY EVALUATION
    # STEP 3a: Extract the ohmic series resistance from the EIS data into a separate dataframe

    # partition by metadata columns and compute x-intercepts per group,
    # since get_x_intercepts uses .over(group) internally and "cycle number"
    # values repeat across different files
    _meta_cols = ["study_phase", "participant", "repetition", "flow_rate"]
    series_resistance_df = pl.concat(
        [
            get_x_intercepts(
                df=group_df,
                x="Re(Z)/Ohm",
                y="-Im(Z)/Ohm",
                group="cycle",
                which="last",
                assume_sorted=False,
            )
            .with_columns(pl.lit(group_df[col][0]).alias(col) for col in _meta_cols)
            .select(
                *_meta_cols,
                pl.col("cycle"),
                pl.col("x_intercept").alias("ESR/Ohm"),
            )
            for group_df in eis_filtered_df.partition_by(_meta_cols, as_dict=False)
        ],
        how="vertical_relaxed",
    )
    return (series_resistance_df,)


@app.cell
def esr_per_participant_1(series_resistance_df):
    # IMPEDANCE SPECTROSCOPY EVALUATION
    # STEP 3b: Plot series resistance values per participants (mean value over repetitions)
    #          with error bars representing the standard deviation of the mean)

    # create a bar chart to compare the ESR values across participants and repetitions
    series_resistance_per_participant = series_resistance_df.group_by(
        "study_phase",
        "participant",
        "flow_rate",
    ).agg(
        pl.col("ESR/Ohm").mean().alias("mean_esr"),
        pl.col("ESR/Ohm").std().alias("std_esr"),
        pl.len().alias("cycles"),
    ).sort(["study_phase", "participant", "flow_rate"])

    _bars = (
        alt.Chart(series_resistance_per_participant)
        .mark_bar(
            opacity=1
        )
        .encode(
            x=alt.X("participant:N", title="Participant"),
            y=alt.Y("mean_esr:Q", title="Mean ESR / Ohm"),
            xOffset=alt.XOffset("flow_rate:O", title="Flow Rate"),
            color=alt.Color("participant:N", title="Participant"),
            opacity=alt.Opacity("flow_rate:N", title="Flow Rate", scale=alt.Scale(range=[0.33, 1.0])),
            tooltip=[
                "study_phase:N",
                "participant:N",
                "flow_rate:O",
                alt.Tooltip("mean_esr:Q", format=".4f"),
                alt.Tooltip("std_esr:Q", format=".4f"),
                "cycles:O",
            ],
        )
    )

    _errs = (
        alt.Chart(series_resistance_per_participant)
        .mark_errorbar(
            ticks=True,
            size=10,
        )
        .encode(
            x="participant:N",
            y=alt.Y("mean_esr:Q", title="Mean ESR / Ohm"),
            yError="std_esr:Q",
            xOffset="flow_rate:O",
            color=alt.value("#000000"),
        )
    )

    series_resistance_per_participant_plot = (
        alt.layer(_bars, _errs)
        .properties(
            title=alt.TitleParams(
                text="Figure 2. ESR per participant",
                subtitle="ESR values for each participant across selected repetitions.",
                anchor="start",
                orient="top",
                offset=20,
            ),
            width=325,
        )
        .configure_axisX(
            labelAngle=-45
        )
    )
    return (series_resistance_per_participant_plot,)


@app.cell
def esr_per_repetition(series_resistance_df):
    # IMPEDANCE SPECTROSCOPY EVALUATION
    # STEP 3c: Plot series resistance values over repetition (mean value over participants)
    #          with error bars representing the standard deviation of the mean)

    # create a bar chart to compare the ESR values across participants and repetitions
    series_resistance_per_repetition = series_resistance_df.group_by(
        "study_phase",
        "repetition",
        "flow_rate",
    ).agg(
        pl.col("ESR/Ohm").mean().alias("mean_esr"),
        pl.col("ESR/Ohm").std().alias("std_esr"),
        pl.len().alias("cycles"),
    ).sort(["study_phase", "repetition", "flow_rate"])

    # build domains for the ESR values
    _all_esr = series_resistance_df["ESR/Ohm"]
    _all_mean_esr = series_resistance_per_repetition["mean_esr"]
    _esr_domain = [_all_esr.min() / 1.1, _all_esr.max() * 1.1]
    _mean_esr_domain = [_all_mean_esr.min() / 1.1, _all_mean_esr.max() * 1.1]

    # construct a box plot
    _boxplot = (
        alt.Chart(
            series_resistance_df,
        )
        .mark_boxplot(
            size=25,
            ticks={"size": 10},
            median={"color": "black", "thickness": 2},
            outliers={"size": 15, "shape": "circle"},
        )
        .encode(
            x=alt.X("repetition:O", title="Repetition"),
            y=alt.Y(
                "ESR/Ohm:Q", title="ESR / Ohm", scale=alt.Scale(domain=_esr_domain)
            ),
            xOffset=alt.XOffset("flow_rate:O", title="Flow Rate"),
            color=alt.Color("repetition:O", title="Repetition"),
            opacity=alt.Opacity("flow_rate:O", title="Flow Rate", scale=alt.Scale(range=[1, 0.33])),
        )
    )

    _mean = (
        alt.Chart(series_resistance_per_repetition)
        .mark_point(
            color="black",
            opacity=0.75,
            shape="circle",
            size=50,
        )
        .encode(
            x=alt.X("repetition:O", title="Repetition"),
            y=alt.Y(
                "mean_esr:Q",
                title="Mean ESR / Ohm",
                scale=alt.Scale(domain=_esr_domain),
            ),
            xOffset="flow_rate:O",
            tooltip=[
                "study_phase:N",
                "flow_rate:O",
                alt.Tooltip("mean_esr:Q", format=".4f"),
                alt.Tooltip("std_esr:Q", format=".4f"),
                "cycles:Q",
            ],
        )
    )

    series_resistance_per_repetition_plot = (
        alt.layer(_boxplot, _mean)
        .resolve_scale(y="shared")
        .resolve_axis(y="shared")
        .properties(
            title=alt.TitleParams(
                text="Figure 3. ESR per repetition",
                subtitle="ESR values for each repetition across selected participants.",
                anchor="start",
                orient="top",
                offset=20,
            ),
            width=325,
        )
        .configure_axisX(labelAngle=0)
    )
    return (series_resistance_per_repetition_plot,)


@app.cell
def section_impedance_spectroscopy(
    eis_filtered_df,
    nyquist_plots,
    series_resistance_per_participant_plot,
    series_resistance_per_repetition_plot,
):
    # IMPEDANCE SPECTROSCOPY EVALUATION
    # STEP 4: Display the content of the section and explain what it does

    # display section content
    mo.vstack(
        [
            mo.md("## Impedance Spectroscopy"),
            mo.md("""
                This section allows you to visualize the results of the Impedance Spectroscopy experiments. You can select one or more files containing the EIS data, and the notebook will generate Nyquist plots, extract ohmic series resistances for each selected file, and compare different repetitions and runs.
            """),
            mo.md("<br>"),
            mo.md("### Raw data exploration"),
            mo.md("""
                The expandable sections enables you to explore the raw EIS data of all selected datasets in more detail. You can view the data in a tabular format and apply filter and computations or use the interactive data explorer to filter, sort, and visualize the data as needed. While the functions are limited, it may help you gain a better understanding of the underlying data beyond the prepared visualizations below.
            """),
            mo.accordion(
                {
                    "Data table": mo.ui.dataframe(eis_filtered_df),
                    # "Data explorer": mo.ui.data_explorer(eis_filtered_df),
                },
                lazy=True,
                multiple=True,
            ),
            mo.md("<br>"),
            mo.md("### Nyquist plots"),
            mo.md("""
                These Nyquist plots show the relationship between the real and imaginary parts of the impedance grouped by participant. Each point on the plot corresponds to a specific frequency, and the shape of the plot can provide insights into the electrochemical processes occurring in the system.
            """),
            mo.md("<br>"),
            mo.lazy(nyquist_plots, show_loading_indicator=True),
            mo.md("<br>"),
            mo.md("### Ohmic series resistance (ESR) comparison"),
            mo.md("""
                These plots compare the extracted ohmic series resistance (ESR) values across participants and repetitions. To keep it simple, the ESR was not fitted via a Randles circuit but simply estimated from the intercept of the Nyquist plots with the Re(Z)-axis. The first plot shows the mean ESR values for each participant with error bars representing the standard deviation across repetitions. The second plot shows the mean ESR values for each repetition with error bars representing the standard deviation across participants. You can use these plots to identify trends or differences in ESR values between participants and repetitions.
            """),
            mo.md("<br>"),
            mo.lazy(
                mo.hstack(
                    [
                        series_resistance_per_participant_plot,
                        series_resistance_per_repetition_plot,
                    ],
                    widths="equal",
                    gap=0,
                ),
                show_loading_indicator=True
            ),
            mo.md("<br>"),
        ]
    )
    return


@app.cell
def _(
    flow_rate_selector,
    participant_selector,
    polarisation_flat_df,
    recalculate_time,
    repetition_selector,
    study_phase_selector,
):
    # POLARISATION DATA EVALUATION
    # STEP 1b: Filter the polarisation data according to the UI selectors

    # apply UI filter
    polarisation_filtered_df = polarisation_flat_df.filter(
        pl.col("study_phase").is_in([study_phase_selector.value])
        & pl.col("participant").is_in(participant_selector.value)
        & pl.col("repetition").is_in(repetition_selector.value)
        & pl.col("flow_rate").is_in(flow_rate_selector.value)
    )
    mo.stop(
        polarisation_filtered_df.is_empty(),
    )

    # recalculate time/s from datetime column for each group (study_phase, participant, repetition, flow_rate)
    # NOTE: We do this to properly handle multiple files in one experiment folder
    polarisation_filtered_df = recalculate_time(polarisation_filtered_df)
    return (polarisation_filtered_df,)


@app.cell
def _(polarisation_filtered_df):
    # POLARISATION DATA EVALUATION
    # STEP 2a: Plot the time-voltage curves

    # shift time to start at 0 per file (identified by metadata group)
    _meta_cols = ["study_phase", "participant", "repetition", "flow_rate"]
    _chart_data = polarisation_filtered_df.with_columns(
        (pl.col("time/s") - pl.col("time/s").min()).over(_meta_cols).alias("time/s"),
    ).select(
        [
            *_meta_cols,
            "Ns",
            "time/s",
            "voltage/V",
            "current/mA",
        ]
    )

    # downsample the data for better performance in the plot to a maximum of 20000 points
    for n in range(1, 100, 1):

        # bin width
        bin_w = n * 1  # time bin width in s (e.g., 1 s, 2 s, etc.)
    
        _downsampled_chart_data = (
            _chart_data.with_columns(
                # build time-based bins
                ((pl.col("time/s") / bin_w).round() * bin_w).alias("time_bin"),
            )
            .with_columns(
                # compute median time within each bin per sequence (Ns)
                pl.col("time/s").median().over([
                    *_meta_cols, 
                    "Ns", 
                    "time_bin",
                ]).alias("_t_med"),
            )
            .with_columns(
                # compute distance to median time within each bin per sequence (Ns)
                # to keep the closest-to-median point for better curve representation after downsampling
                (pl.col("time/s") - pl.col("_t_med")).abs().alias("_t_dist")
            )
            .sort([
                *_meta_cols, 
                "Ns", 
                "time_bin", 
                "_t_dist",
            ])
            .group_by([
                *_meta_cols, 
                "Ns", 
                "time_bin"
            ])
            .agg(
                # keep the first row after sorting by distance to median time as the representative point for each bin
                pl.all().first()
            )
            .drop(["_t_med", "_t_dist"])
            .sort([
                *_meta_cols,
                "Ns", 
                "time/s"
            ])
        )

        #print(n, bin_w, len(_downsampled_chart_data), len(_chart_data))
        if len(_downsampled_chart_data) <= 20000:
            break

    # create selectors and bind them to the legend
    _participant_selection = alt.selection_point(fields=["participant"], bind="legend")
    _repetition_selection = alt.selection_point(fields=["repetition"], bind="legend")
    _flow_rate_selection = alt.selection_point(fields=["flow_rate"], bind="legend")

    # build polarisation plot from single flat DataFrame
    polarisation_plots = (
        alt.Chart(_downsampled_chart_data)
        .mark_point()
        .encode(
            x=alt.X("time/s", title="Time / s"),
            y=alt.Y("voltage/V", title="Voltage / V"),
            color=alt.Color("participant:N", title="Participant"),
            shape=alt.Shape("repetition:N", title="Repetition"),
            size=alt.Size(
                "flow_rate:N",
                title="Flow Rate (mL/min⁻¹)",
                scale=alt.Scale(range=[30, 150]),
            ),
            opacity=alt.condition(
                _participant_selection 
                & _repetition_selection
                & _flow_rate_selection,
                alt.value(1.0),
                alt.value(0.0),
            ),
            tooltip=[
                "participant:N",
                "repetition:O",
                "flow_rate:Q",
                alt.Tooltip("time/s:Q", format=".1f"),
                alt.Tooltip("voltage/V:Q", format=".4f"),
            ],
        )
        .properties(
            title="Polarisation Plot",
        )
        .add_params(_participant_selection, _repetition_selection, _flow_rate_selection)
    ).properties(
        title=alt.TitleParams(
            text="Figure 4. Current-overvoltage curves for selected participants and repetitions",
            subtitle="Current-overvoltage curves showing the relationship between current and overvoltage for each selected file.",
            anchor="start",
            orient="top",
            offset=20,
        ),
        height=400,
    )
    return (polarisation_plots,)


@app.cell
def _(get_linregress_params, polarisation_filtered_df):
    # POLARISATION DATA EVALUATION
    # STEP 3a: Calculate the polarisation resistances based on the step voltages and applied currents (using a linear regression)

    # define evaluation parameters
    step_evaluation_tail_length = 10  # number of samples from the end of each step to consider for the evaluation
    rest_current_tolerance = 1        # rest current tolerance (± X mA) to filter out rest steps

    # aggregate the data: group_by now includes metadata columns alongside Ns
    _meta_cols = ["study_phase", "participant", "repetition", "flow_rate"]
    polarisation_current_voltage_df = (
        polarisation_filtered_df.group_by(
            *_meta_cols,
            "Ns",
            maintain_order=True,
        )
        .agg(
            pl.col("voltage/V")
            .tail(step_evaluation_tail_length)
            .median()
            .alias("voltage/V"),
            pl.col("current/mA")
            .tail(step_evaluation_tail_length)
            .median()
            .alias("current/mA"),
        )
        .with_columns(
            (pl.col("voltage/V") / pl.col("current/mA") * 1000).alias(
                "polarisation_resistance/Ohm"
            ),
        )
        .select(
            [
                *_meta_cols,
                "Ns",
                "voltage/V",
                "current/mA",
                "polarisation_resistance/Ohm",
            ]
        )
    )

    # drop rows where current is close to zero (rest steps) based on the defined tolerance
    polarisation_current_voltage_df = polarisation_current_voltage_df.filter(
        (pl.col("current/mA").abs() > rest_current_tolerance)
    ).sort([*_meta_cols, "Ns"])

    # perform linear regression on grouped data to get polarisation resistance as slope of the voltage-current curve for each participant, repetition, and flow rate
    polarisation_resistance_df = (
        polarisation_current_voltage_df.group_by(
            *_meta_cols,
        )
        .map_groups(
            lambda df: get_linregress_params(
                df=df,
                x_name="current/mA",
                y_name="voltage/V",
                with_columns=[
                    *_meta_cols,
                    "Ns",
                    "current/mA",
                    "voltage/V",
                ],
            )
        )
        .with_columns(
            (pl.col("slope") * 1000).alias("polarisation_resistance/Ohm"),
            (pl.col("stderr") * 1000).alias("polarisation_resistance_stderr/Ohm"),
        )
        .select(
            [
                *_meta_cols,
                "Ns",
                "voltage/V",
                "current/mA",
                "polarisation_resistance/Ohm",
                "polarisation_resistance_stderr/Ohm",
            ]
        )
        .sort([*_meta_cols, "Ns"])
    )
    return (
        polarisation_current_voltage_df,
        polarisation_resistance_df,
        step_evaluation_tail_length,
    )


@app.cell
def _(polarisation_current_voltage_df):
    # POLARISATION DATA EVALUATION
    # STEP 3b: Plot the step voltage over the step current

    # compute per-axis data ranges, then build domains with some padding
    _all_currents = polarisation_current_voltage_df["current/mA"].abs()
    _current_max = _all_currents.max()
    _current_domain = [-_current_max * 1.1, _current_max * 1.1]

    # selectors bound to legends
    _participant_selection = alt.selection_point(encodings=["color"], bind="legend")
    _repetition_selection = alt.selection_point(encodings=["shape"], bind="legend")
    _flow_rate_selection = alt.selection_point(encodings=["size"], bind="legend")

    points = (
        alt.Chart(polarisation_current_voltage_df)
        .mark_point(filled=True, size=50)
        .encode(
            x=alt.X(
                "current/mA:Q",
                title="Current / mA",
                scale=alt.Scale(domain=_current_domain),
            ),
            y=alt.Y("voltage/V:Q", title="Voltage / V"),
            color=alt.Color("participant:N", title="Participant"),
            shape=alt.Shape("repetition:N", title="Repetition"),
            size=alt.Size(
                "flow_rate:N",
                title="Flow Rate (mL min⁻¹)",
                scale=alt.Scale(range=[30, 150]),
            ),
            opacity=alt.condition(
                _participant_selection
                & _repetition_selection
                & _flow_rate_selection,
                alt.value(1.0),
                alt.value(0.05),
            ),
            tooltip=[
                "participant:N",
                "repetition:O",
                "flow_rate:Q",
                alt.Tooltip("current/mA:Q", format=".1f"),
                alt.Tooltip("voltage/V:Q", format=".4f"),
            ],
        )
    )

    regression_lines = (
        alt.Chart(polarisation_current_voltage_df)
        .transform_regression(
            "current/mA", "voltage/V", groupby=["participant", "repetition"]
        )
        .mark_line()
        .encode(
            x="current/mA:Q",
            y="voltage/V:Q",
            color=alt.Color("participant:N", title="Participant"),
            strokeDash=alt.StrokeDash(
                "repetition:N", title="Repetition", legend=None
            ),  # dash in plot
            opacity=alt.condition(
                _participant_selection
                & _repetition_selection
                & _flow_rate_selection,
                alt.value(1.0),
                alt.value(0.05),
            ),
        )
    )

    polarisation_voltage_current_plots = (
        alt.layer(points, regression_lines)
        .add_params(_participant_selection, _repetition_selection, _flow_rate_selection)
        .resolve_legend(color="shared", shape="shared", strokeDash="shared")
    )

    # polarisation_voltage_current_plots
    return (polarisation_voltage_current_plots,)


@app.cell
def _(polarisation_resistance_df):
    # POLARISATION DATA EVALUATION
    # STEP 3c: Plot polarisation resistance values per participants (mean value over repetitions)
    #          with error bars representing the standard deviation of the mean)

    # create a bar chart to compare the ESR values across participants and repetitions
    polarisation_resistance_per_participant = polarisation_resistance_df.group_by(
        "study_phase",
        "participant",
        "flow_rate",
    ).agg(
        pl.col("polarisation_resistance/Ohm").mean().alias("mean_resistance"),
        pl.col("polarisation_resistance/Ohm").std().alias("std_resistance"),
        pl.len().alias("cycles"),
    )

    # create selectors and bind them to the legend
    _participant_selection = alt.selection_point(fields=["participant"], bind="legend")

    _bars = (
        alt.Chart(polarisation_resistance_per_participant)
        .mark_bar()
        .encode(
            x=alt.X("participant:O", title="Participant"),
            y=alt.Y("mean_resistance:Q", title="Polarisation Resistance / Ohm"),
            xOffset=alt.XOffset("flow_rate:O", title="Flow Rate"),
            color=alt.Color("participant:N", title="Study Phase"),
            opacity=alt.Opacity("flow_rate:N", title="Flow Rate", scale=alt.Scale(range=[1.0, 0.5])),
            tooltip=[
                "study_phase:O",
                "participant:O",
                "flow_rate:O",
                alt.Tooltip("mean_resistance:Q", format=".4f"),
                alt.Tooltip("std_resistance:Q", format=".4f"),
                "cycles:Q",
            ],
        )
        .add_params(
            _participant_selection,
        )
    )

    _errs = (
        alt.Chart(polarisation_resistance_per_participant)
        .mark_errorbar(
            ticks=True,
            size=10,
        )
        .encode(
            x="participant:O",
            y=alt.Y("mean_resistance:Q", title="Polarisation Resistance / Ohm"),
            yError="std_resistance:Q",
            xOffset="flow_rate:O",
            color=alt.value("#000000"),
        )
        .add_params(
            _participant_selection,
        )
    )

    polarisation_resistance_per_participant_plot = (
        alt.layer(_bars, _errs)
        .properties(
            title=alt.TitleParams(
                text="Figure 6. Polarisation resistance per participant",
                subtitle="Mean polarisation resistance values for each participant across selected repetitions.",
                anchor="start",
                orient="top",
                offset=20,
            ),
            width=325,
        )
        .configure_axisX(labelAngle=-45)
    )
    return (polarisation_resistance_per_participant_plot,)


@app.cell
def _(polarisation_resistance_df):
    # POLARISATION DATA EVALUATION
    # STEP 3d: Plot polarisation resistance values over repetition (mean value over participants)
    #          with error bars representing the standard deviation of the mean)

    # create a bar chart to compare the ESR values across participants and repetitions
    polarisation_resistance_per_repetition = polarisation_resistance_df.group_by(
        "study_phase",
        "repetition",
        "flow_rate",
    ).agg(
        pl.col("polarisation_resistance/Ohm").mean().alias("mean_resistance"),
        pl.col("polarisation_resistance/Ohm").std().alias("std_resistance"),
        pl.len().alias("cycles"),
    )

    # build domains for the polarisation resistance values
    _all_resistance = polarisation_resistance_df["polarisation_resistance/Ohm"]
    _all_mean_resistance = polarisation_resistance_per_repetition["mean_resistance"]
    _resistance_domain = [_all_resistance.min() / 1.1, _all_resistance.max() * 1.1]
    _mean_resistance_domain = [
        _all_mean_resistance.min() / 1.1,
        _all_mean_resistance.max() * 1.1,
    ]

    # construct a box plot
    _boxplot = (
        alt.Chart(
            polarisation_resistance_df,
        )
        .mark_boxplot(
            size=25,
            ticks={"size": 10},
            median={"color": "black", "thickness": 2},
            outliers={"size": 15, "shape": "circle"},
        )
        .encode(
            x=alt.X("repetition:O", title="Repetition"),
            y=alt.Y(
                "polarisation_resistance/Ohm:Q",
                title="Polarisation Resistance / Ohm",
                scale=alt.Scale(domain=_resistance_domain),
            ),
            xOffset=alt.XOffset("flow_rate:O", title="Flow Rate"),
            color=alt.Color("repetition:O", title="Repetition"),
            opacity=alt.Opacity("flow_rate:O", title="Flow Rate", scale=alt.Scale(range=[1, 0.33])),
        )
    )

    _mean = (
        alt.Chart(polarisation_resistance_per_repetition)
        .mark_point(
            color="black",
            opacity=0.75,
            shape="circle",
            size=50,
        )
        .encode(
            x=alt.X("repetition:O", title="Repetition"),
            y=alt.Y(
                "mean_resistance:Q",
                title="Polarisation Resistance / Ohm",
                scale=alt.Scale(domain=_mean_resistance_domain),
            ),
            xOffset="flow_rate:O",
            tooltip=[
                "study_phase:O",
                "flow_rate:O",
                alt.Tooltip("mean_resistance:Q", format=".4f"),
                alt.Tooltip("std_resistance:Q", format=".4f"),
                "cycles:Q",
            ],
        )
    )

    polarisation_resistance_per_repetition_plot = (
        alt.layer(_boxplot, _mean)
        .properties(
            title=alt.TitleParams(
                text="Figure 7. Polarisation resistance per repetition",
                subtitle="Polarisation resistance values for each repetition across selected participants.",
                anchor="start",
                orient="top",
                offset=20,
            ),
            width=325,
        )
        .configure_axisX(labelAngle=0)
    )
    return (polarisation_resistance_per_repetition_plot,)


@app.cell
def section_polarisation(
    polarisation_filtered_df,
    polarisation_plots,
    polarisation_resistance_per_participant_plot,
    polarisation_resistance_per_repetition_plot,
    polarisation_voltage_current_plots,
    step_evaluation_tail_length,
):
    # display section content
    mo.vstack(
        [
            mo.md("## Polarisation experiments"),
            mo.md("""
                This section allows you to visualize the results of the data from the polarisation experiments. You can select one or more files containing the polarisation data, and the notebook will generate visualizations to help you analyze the results and compare different repetitions and runs.
            """),
            mo.md("<br>"),
            mo.md("### Raw data exploration"),
            mo.md("""
                The expandable sections enables you to explore the raw polarisation data of all selected datasets in more detail. You can view the data in a tabular format and apply filter and custom computations or use the interactive data explorer to filter, sort, and visualize the data as needed. While the functions are limited, it may help you gain a better understanding of the underlying data beyond the prepared visualizations below.
            """),
            mo.accordion(
                {
                    "Data table": polarisation_filtered_df,
                    # "Data explorer": mo.ui.data_explorer(polarisation_filtered_df),
                },
                lazy=True,
                multiple=True,
            ),
            mo.md("<br>"),
            mo.md("### Current-overvoltage curves"),
            mo.md("""
                These plots show the relationship between the current and the overvoltage (i.e., applied voltage - OCV) for each selected file. The shape of the curves can provide insights into the electrochemical processes occurring in the system, such as activation losses, ohmic losses, and mass transport limitations. You can compare the curves across different participants and repetitions to identify trends or differences in the polarisation behavior.
            """),
            mo.md("<br>"),
            mo.lazy(polarisation_plots, show_loading_indicator=True),
            mo.lazy(polarisation_voltage_current_plots, show_loading_indicator=True),
            mo.md("<br>"),
            mo.md("### Polarisation resistance comparison"),
            mo.md(f"""
                These plots compare the extracted polarisation resistance values across participants and repititions. The polarisation resistance was calculated from the voltage and current values of the polarisation steps by first collecting the median voltage _versus_ median current of the last {step_evaluation_tail_length} points of each polarisation step. Subsequently, a linear regression was performed over the collected data. The first plot shows the mean polarisation resistance values for each participant with error bars representing the standard deviation across all selected repetitions. The second plot shows the mean polarisation resistance values for each repetition with error bars representing the standard deviation across all selected participants. You can use these plots to identify trends or differences in polarisation resistance values between participants and repetitions.
            """),
            mo.md("<br>"),
            mo.lazy(
                mo.hstack(
                    [
                        polarisation_resistance_per_participant_plot,
                        polarisation_resistance_per_repetition_plot,
                    ],
                    widths="equal",
                    gap=0,
                ),
                show_loading_indicator=True,
            ),
            mo.md("<br>"),
        ]
    )
    return


@app.cell
def _(
    cd_cycling_flat_df,
    flow_rate_selector,
    participant_selector,
    repetition_selector,
    study_phase_selector,
):
    # CHARGE-DISCHARGE CYCLING EVALUATION
    # STEP 1b: Filter the charge-discharge data according to the UI selectors

    # apply UI filter
    cd_cycling_filtered_df = cd_cycling_flat_df.filter(
        pl.col("study_phase").is_in([study_phase_selector.value])
        & pl.col("participant").is_in(participant_selector.value)
        & pl.col("repetition").is_in(repetition_selector.value)
        & pl.col("flow_rate").is_in(flow_rate_selector.value)
    )
    mo.stop(
        cd_cycling_filtered_df.is_empty(),
    )
    return (cd_cycling_filtered_df,)


@app.cell
def _(cd_cycling_filtered_df):
    # CHARGE-DISCHARGE CYCLING EVALUATION
    # STEP 2a: Prepare dataframes for the voltage-capacity as well as voltage-dQ/dV curves from the charge-discharge cycling data

    # compute derived columns using .over() to keep per-file semantics
    _meta_cols = ["study_phase", "participant", "repetition", "flow_rate"]
    # Step 1: compute diff-based columns within each file group
    _cd_with_diffs = cd_cycling_filtered_df.with_columns(
        pl.col("time/s").diff().over(_meta_cols).alias("dt/s"),
        pl.col("Q charge/discharge/mA.h").alias("capacity/mAh"),
        (
            pl.col("Q charge/discharge/mA.h").diff().over(_meta_cols)
            / pl.col("voltage/V").diff().over(_meta_cols)
        ).alias("_dQ_dV_raw"),
    )
    # Step 2: smooth dQ/dV with rolling median within each file group
    df_filtered_cd_cycling_data = _cd_with_diffs.with_columns(
        pl.col("_dQ_dV_raw").rolling_median(25).over(_meta_cols).alias("dQ/dV"),
    ).select(
        [
            *_meta_cols,
            "half cycle",
            "time/s",
            "voltage/V",
            "current/mA",
            "capacity/mAh",
            "dQ/dV",
        ]
    )

    # downsample the data for better performance in the plot
    # bin voltage to every 10 mV per half cycle and keep only keep median values within each voltage bin 
    # to preserve the overall curve shape while reducing the number of points
    df_filtered_cd_cycling_chart_data = (
        df_filtered_cd_cycling_data.with_columns(
            (pl.col("voltage/V") / 0.01).round().alias("voltage_bin"),
        ).group_by(
            *_meta_cols,
            "half cycle",
            "voltage_bin",
        ).agg(
            pl.col("voltage/V").median().alias("voltage/V"),
            pl.col("current/mA").median().alias("current/mA"),
            pl.col("capacity/mAh").median().alias("capacity/mAh"),
            pl.col("dQ/dV").median().alias("dQ/dV"),
        ).sort(
            [
                *_meta_cols,
                "half cycle",
                "voltage_bin",
            ]
        ).drop("voltage_bin")
    )

    # create a ui slider to chose the half-cycle to display
    # (removed stray mo.ui.slider(start=1, stop=10, step=1))
    slider_half_cycle = mo.ui.slider(
        label="",
        start=int(df_filtered_cd_cycling_chart_data["half cycle"].min() / 2),
        stop=int(df_filtered_cd_cycling_chart_data["half cycle"].max() / 2),
        step=1,
        full_width=True,
        show_value=True,
    )
    return (
        df_filtered_cd_cycling_chart_data,
        df_filtered_cd_cycling_data,
        slider_half_cycle,
    )


@app.cell
def _(
    df_filtered_cd_cycling_chart_data,
    df_filtered_cd_cycling_data,
    slider_half_cycle,
    wheel_zoom_x,
    wheel_zoom_xy,
    wheel_zoom_y,
):
    # CHARGE-DISCHARGE CYCLING EVALUATION
    # STEP 2b: Build the voltage-time as well as voltage-dQ/dV curves for the charge-discharge cycling data

    # create selectors and bind them to the legend
    _participant_selection = alt.selection_point(fields=["participant"], bind="legend")
    _repetition_selection = alt.selection_point(fields=["repetition"], bind="legend")

    # filter the data for the selected cycle (i.e., half cycle) 
    _cd_cycling_capacity_voltage_data = df_filtered_cd_cycling_chart_data.filter(
        (pl.col("half cycle") == slider_half_cycle.value)
        | (pl.col("half cycle") == slider_half_cycle.value + 1)
    ).with_columns(
        pl.col("capacity/mAh").abs().alias("capacity/mAh"),
    )

    # compute per-axis data ranges, then build domains with some padding
    _all_voltage = _cd_cycling_capacity_voltage_data["voltage/V"]
    _voltage_domain = [_all_voltage.min(), _all_voltage.max()]
    _dqdv_domain = [0, df_filtered_cd_cycling_data["dQ/dV"].max()]

    # build a plot of voltage vs. capacity for the selected cycle
    cd_cycling_capacity_voltage = (
        alt.Chart(
            _cd_cycling_capacity_voltage_data
        )
        .mark_point()
        .encode(
            x=alt.X("capacity/mAh:Q", title="Capacity / mAh"),
            y=alt.Y(
                "voltage/V:Q",
                title="Voltage / V",
                scale=alt.Scale(domain=_voltage_domain),
            ),
            color=alt.Color("participant:N", title="Participant"),
            shape=alt.Shape("repetition:N", title="Repetition"),
            opacity=alt.condition(
                _participant_selection & _repetition_selection,
                alt.value(1.0),
                alt.value(0.0),
            ),
            tooltip=[
                "participant:N",
                "repetition:O",
                "flow_rate:Q",
                alt.Tooltip("capacity/mAh:Q", format=".1f"),
                alt.Tooltip("voltage/V:Q", format=".4f"),
            ],
        )
        .properties(width=720)
    )

    # build a plot of dQ/dV vs. voltage for the selected cycle
    cd_cycling_dqdv_charts = (
        alt.Chart(
            _cd_cycling_capacity_voltage_data
        )
        .mark_bar(
            orient="horizontal",
        )
        .encode(
            x=alt.X(
                "dQ/dV:Q", title="dQ/dV / mAh/V", scale=alt.Scale(domain=_dqdv_domain)
            ),
            y=alt.Y(
                "voltage/V:Q",
                title="",
                scale=alt.Scale(domain=_voltage_domain),
                axis=alt.Axis(title=None, labels=False, ticks=False),
            ),
            color=alt.Color("participant:N", title="Participant"),
            opacity=alt.condition(
                _participant_selection & _repetition_selection,
                alt.value(1.0),
                alt.value(0.0),
            ),
            tooltip=[
                "participant:N",
                "repetition:O",
                "flow_rate:Q",
                alt.Tooltip("dQ/dV:Q", format=".2f"),
                alt.Tooltip("voltage/V:Q", format=".4f"),
            ],
        )
        .properties(
            width=170,
        )
    )

    cd_cycling_charts = (
        alt.hconcat(cd_cycling_capacity_voltage, cd_cycling_dqdv_charts)
        .resolve_legend(color="shared")
        .properties(
            title=alt.TitleParams(
                text="Figure 8. Charge-discharge cycling data",
                subtitle="Voltage-capacity curves and dQ/dV plots for the selected cycle.",
                anchor="start",
                orient="top",
                offset=20,
            ),
        )
        .interactive()
        .add_params(_participant_selection, _repetition_selection)
        .add_params(wheel_zoom_xy, wheel_zoom_x, wheel_zoom_y)
    )

    return (cd_cycling_charts,)


@app.cell
def _(df_filtered_cd_cycling_data, get_linregress_params):
    # CHARGE-DISCHARGE CYCLING EVALUATION
    # STEP 3a: Aggregate the capacity data for each cycle as charge and discharge capacity and compute the coulombic efficiency

    # filter out each half-cycle's end capacity
    cd_cycling_filtered_cycle_data = (
        df_filtered_cd_cycling_data.group_by(
            "study_phase",
            "participant",
            "repetition",
            "flow_rate",
            "half cycle",
        )
        .agg(
            (pl.col("time/s") / 3600).last().alias("time/h"),
            pl.col("capacity/mAh").last().alias("capacity/mAh"),
        )
        .sort(["study_phase", "participant", "repetition", "flow_rate", "half cycle"])
    )

    # separate capacity values for charge and discharge steps by filtering positive (charge) and negative (discharge) capacity values
    cd_cycling_filtered_cycle_data = (
        cd_cycling_filtered_cycle_data.with_columns(
            pl.when(pl.col("capacity/mAh") > 0)
            .then(pl.col("capacity/mAh"))
            .otherwise(None)
            .alias("charge_capacity/mAh"),
            pl.when(pl.col("capacity/mAh") < 0)
            .then(pl.col("capacity/mAh").abs())
            .otherwise(None)
            .alias("discharge_capacity/mAh"),
        )
        .drop("capacity/mAh")
        .group_by(
            "study_phase",
            "participant",
            "repetition",
            "flow_rate",
            (pl.col("half cycle") // 2).alias("cycle"),
        )
        .agg(
            pl.col("time/h").last().alias("time/h"),
            pl.col("charge_capacity/mAh").first().alias("charge_capacity/mAh"),
            pl.col("discharge_capacity/mAh").last().alias("discharge_capacity/mAh"),
        )
        .sort(["study_phase", "participant", "repetition", "flow_rate", "cycle"])
    )

    # calculate coulombic efficiency for each cycle
    cd_cycling_filtered_cycle_data = cd_cycling_filtered_cycle_data.with_columns(
        (pl.col("discharge_capacity/mAh") / pl.col("charge_capacity/mAh") * 100).alias(
            "coulombic_efficiency/%"
        ),
    ).sort(["study_phase", "participant", "repetition", "flow_rate", "cycle"])

    # drop all cycles with:
    # - undefined coulombic efficiency
    # - coulombic efficiency smaller than 60% greater than 140%
    cd_cycling_filtered_cycle_data = cd_cycling_filtered_cycle_data.drop_nans(
        "coulombic_efficiency/%"
    ).filter(
        (pl.col("coulombic_efficiency/%") > 60)
        & (pl.col("coulombic_efficiency/%") < 140)
    )

    # calculate capacity retention relative to the initial discharge capacity for each group
    cd_cycling_filtered_cycle_data = cd_cycling_filtered_cycle_data.with_columns(
        (
            pl.col("discharge_capacity/mAh")
            / pl.col("discharge_capacity/mAh")
            .first()
            .over(
                "study_phase",
                "participant",
                "repetition",
                "flow_rate",
            )
            * 100
        ).alias("capacity_retention/%")
    ).sort(["study_phase", "participant", "repetition", "flow_rate", "cycle"])

    # get the initial discharge capacity for each group
    cd_cycling_initial_discharge_capacity = cd_cycling_filtered_cycle_data.group_by(
        "study_phase",
        "participant",
        "repetition",
        "flow_rate",
    ).agg(
        pl.col("discharge_capacity/mAh").first().alias("capacity/mAh"),
    )

    # compute the capacity fade relative to the initial discharge capacity for each group by performing a group mapping of get_linregress_params over the capacity-time data and extracting the slope of the linear regression as capacity fade rate
    cd_cycling_filtered_capacity_fade_time = (
        cd_cycling_filtered_cycle_data.group_by(
            "study_phase",
            "participant",
            "repetition",
            "flow_rate",
        )
        .map_groups(
            lambda df: get_linregress_params(
                df=df,
                x_name="time/h",
                y_name="capacity_retention/%",
                with_columns=[
                    "study_phase",
                    "participant",
                    "repetition",
                    "flow_rate",
                    "time/h",
                    "cycle",
                    "capacity_retention/%",
                ],
            )
        )
        .sort(
            ["study_phase", "participant", "repetition", "flow_rate", "time/h", "cycle"]
        )
        .with_columns(
            (pl.col("slope") * 24).alias("capacity_fade_rate/%/d"),
        )
        .select(
            [
                "study_phase",
                "participant",
                "repetition",
                "flow_rate",
                "capacity_fade_rate/%/d",
            ]
        )
        .sort(["study_phase", "participant", "repetition", "flow_rate"])
    )

    # compute the capacity fade relative to the initial discharge capacity for each group by performing a group mapping of get_linregress_params over the capacity-cycle data and extracting the slope of the linear regression as capacity fade rate
    cd_cycling_filtered_capacity_fade_cycle = (
        cd_cycling_filtered_cycle_data.group_by(
            "study_phase",
            "participant",
            "repetition",
            "flow_rate",
        )
        .map_groups(
            lambda df: get_linregress_params(
                df=df,
                x_name="cycle",
                y_name="capacity_retention/%",
                with_columns=[
                    "study_phase",
                    "participant",
                    "repetition",
                    "flow_rate",
                    "time/h",
                    "cycle",
                    "capacity_retention/%",
                ],
            )
        )
        .sort(
            ["study_phase", "participant", "repetition", "flow_rate", "time/h", "cycle"]
        )
        .with_columns(
            (pl.col("slope")).alias("capacity_fade_rate/cycle"),
        )
        .select(
            [
                "study_phase",
                "participant",
                "repetition",
                "flow_rate",
                "capacity_fade_rate/cycle",
            ]
        )
        .sort(["study_phase", "participant", "repetition", "flow_rate"])
    )
    return (
        cd_cycling_filtered_capacity_fade_cycle,
        cd_cycling_filtered_capacity_fade_time,
        cd_cycling_filtered_cycle_data,
        cd_cycling_initial_discharge_capacity,
    )


@app.cell
def _(
    cd_cycling_filtered_capacity_fade_cycle,
    cd_cycling_filtered_cycle_data,
    wheel_zoom_x,
    wheel_zoom_xy,
    wheel_zoom_y,
):
    # CHARGE-DISCHARGE CYCLING EVALUATION
    # STEP 3b: Build the capacity-cycle curves for the charge-discharge cycling data

    # create selectors and bind them to the legend
    _participant_selection = alt.selection_point(fields=["participant"], bind="legend")
    _repetition_selection = alt.selection_point(fields=["repetition"], bind="legend")

    # build domains for the capacity retention values and time values
    _all_capacity_retention = cd_cycling_filtered_cycle_data["capacity_retention/%"]
    _capacity_retention_domain = [
        _all_capacity_retention.min() / 1.02,
        _all_capacity_retention.max() * 1.02,
    ]

    _capacity_cycle_chart = (
        alt.Chart(cd_cycling_filtered_cycle_data)
        .mark_point()
        .encode(
            x=alt.X("cycle:Q", title="Cycle"),
            y=alt.Y(
                "capacity_retention/%",
                title="(Discharge) Capacity Retention / %",
                scale=alt.Scale(domain=_capacity_retention_domain),
            ),
            color=alt.Color("participant:N", title="Participant"),
            shape=alt.Shape("repetition:N", title="Repetition"),
            opacity=alt.condition(
                _participant_selection & _repetition_selection,
                alt.value(1.0),
                alt.value(0.0),
            ),
            tooltip=[
                "participant:N",
                "repetition:O",
                "flow_rate:Q",
                alt.Tooltip("cycle:Q", format=".0f"),
                alt.Tooltip("charge_capacity/mAh:Q", format=".1f"),
                alt.Tooltip("discharge_capacity/mAh:Q", format=".1f"),
            ],
        )
        .properties(
            width=720,
            height=300,
        )
    )

    # CHARGE-DISCHARGE CYCLING EVALUATION
    # STEP 3c: Build bar chart for cycle-based capacity fade rates per participant and repetition
    _capacity_fade_cycle_chart = (
        alt.Chart(cd_cycling_filtered_capacity_fade_cycle)
        .mark_bar()
        .encode(
            x=alt.X(
                "capacity_fade_rate/cycle:Q", title="Capacity fade rate / % cycle⁻¹"
            ),
            y=alt.Y(
                "participant:N", axis=alt.Axis(title=None, labels=False, ticks=False)
            ),
            yOffset=alt.YOffset("repetition:O", title="Repetition"),
            color=alt.Color("participant:N", title="Participant"),
            opacity=alt.Opacity("repetition:O", title="Repetition", scale=alt.Scale(range=[1, 0.33])),
            tooltip=[
                "study_phase:O",
                "participant:N",
                "repetition:O",
                "flow_rate:Q",
                alt.Tooltip("capacity_fade_rate/cycle:Q", format=".4f"),
            ],
        )
        .properties(
            width=170,
            height=300,
        )
    )

    # build the final chart by concatenating the capacity-time and capacity fade rate charts and resolving the legends
    cd_cycling_capacity_cycle_chart = (
        alt.hconcat(_capacity_cycle_chart, _capacity_fade_cycle_chart)
        .resolve_legend(color="shared")
        .properties(
            title=alt.TitleParams(
                text="Figure 9. Capacity retention over cycle (left) and corresponding capacity fade rate (right).",
                subtitle=[
                    "Data is shown for the selected participants and repetitions. Capacity fade rate was calculated as the slope of a linear regression over the (discharge) capacity retention vs. cycle data of",
                    "each repetition individually.",
                ],
                anchor="start",
                orient="top",
                offset=20,
            ),
        )
        .interactive()
        .add_params(_participant_selection, _repetition_selection)
        .add_params(wheel_zoom_xy, wheel_zoom_x, wheel_zoom_y)
    )
    return (cd_cycling_capacity_cycle_chart,)


@app.cell
def _(
    cd_cycling_filtered_capacity_fade_time,
    cd_cycling_filtered_cycle_data,
    wheel_zoom_x,
    wheel_zoom_xy,
    wheel_zoom_y,
):
    # CHARGE-DISCHARGE CYCLING EVALUATION
    # STEP 3b: Build the capacity-time curves for the charge-discharge cycling data

    # create selectors and bind them to the legend
    _participant_selection = alt.selection_point(fields=["participant"], bind="legend")
    _repetition_selection = alt.selection_point(fields=["repetition"], bind="legend")

    # build domains for the capacity retention values and time values
    _all_capacity_retention = cd_cycling_filtered_cycle_data["capacity_retention/%"]
    _capacity_retention_domain = [
        _all_capacity_retention.min() / 1.02,
        _all_capacity_retention.max() * 1.02,
    ]

    # build a chart of capacity vs. time for the selected cycle
    _capacity_time_chart = (
        alt.Chart(cd_cycling_filtered_cycle_data)
        .mark_point()
        .encode(
            x=alt.X("time/h:Q", title="Time / h"),
            y=alt.Y(
                "capacity_retention/%:Q",
                title="(Discharge) Capacity Retention / %",
                scale=alt.Scale(domain=_capacity_retention_domain),
            ),
            color=alt.Color("participant:N", title="Participant"),
            shape=alt.Shape("repetition:N", title="Repetition"),
            opacity=alt.condition(
                _participant_selection & _repetition_selection,
                alt.value(1.0),
                alt.value(0.0),
            ),
            tooltip=[
                "participant:N",
                "repetition:O",
                "flow_rate:Q",
                "cycle:O",
                alt.Tooltip("time/h:Q", format=".0f"),
                alt.Tooltip("discharge_capacity/mAh:Q", format=".1f"),
            ],
        )
        .properties(
            width=720,
            height=300,
        )
    )

    # build a chart of capacity fade rate vs. time for the selected cycle
    _capacity_fade_time_chart = (
        alt.Chart(cd_cycling_filtered_capacity_fade_time)
        .mark_bar()
        .encode(
            x=alt.X("capacity_fade_rate/%/d:Q", title="Capacity fade rate / % d⁻¹"),
            y=alt.Y(
                "participant:N", axis=alt.Axis(title=None, labels=False, ticks=False)
            ),
            yOffset=alt.YOffset("repetition:O", title="Repetition"),
            color=alt.Color("participant:N", title="Participant"),
            opacity=alt.Opacity("repetition:O", title="Repetition",scale=alt.Scale(range=[1, 0.33])),
            tooltip=[
                "study_phase:N",
                "participant:N",
                "repetition:O",
                "flow_rate:Q",
                alt.Tooltip("capacity_fade_rate/%/d:Q", format=".4f"),
            ],
        )
        .properties(
            width=170,
            height=300,
        )
    )

    # build the final chart by concatenating the capacity-time and capacity fade rate charts and resolving the legends
    cd_cycling_capacity_time_chart = (
        alt.hconcat(_capacity_time_chart, _capacity_fade_time_chart)
        .resolve_legend(color="shared")
        .properties(
            title=alt.TitleParams(
                text="Figure 10. Capacity retention over time (left) and corresponding capacity fade rate (right).",
                subtitle=[
                    "Data is shown for the selected participants and repetitions. Capacity fade rate was calculated as the slope of a linear regression over the (discharge) capacity retention vs. time data of ",
                    "each repetition individually.",
                ],
                anchor="start",
                orient="top",
                offset=20,
            )
        )
        .interactive()
        .add_params(_participant_selection, _repetition_selection)
        .add_params(wheel_zoom_xy, wheel_zoom_x, wheel_zoom_y)
    )
    return (cd_cycling_capacity_time_chart,)


@app.cell
def _(cd_cycling_filtered_cycle_data):
    # CHARGE-DISCHARGE CYCLING EVALUATION
    # STEP 3b: Build boxplots from capacity data per participant to compare the capacity distributions between participants

    # build domains for the capacity values
    _all_capacity = cd_cycling_filtered_cycle_data["discharge_capacity/mAh"].abs()
    _capacity_domain = [_all_capacity.min(), _all_capacity.max()]

    # construct a box plot
    cd_cycling_capacity_participant = (
        (
            alt.Chart(
                cd_cycling_filtered_cycle_data,
            )
            .mark_boxplot(
                size=50,
                ticks={"size": 30},
                median={"color": "black", "thickness": 2},
                outliers={"size": 10, "shape": "circle"},
            )
            .encode(
                x=alt.X("participant:N", title="Participant"),
                y=alt.Y(
                    "discharge_capacity/mAh:Q",
                    title="(Discharge) Capacity / mAh",
                    scale=alt.Scale(domain=_capacity_domain),
                ),
                color=alt.Color("participant:N", title="Participant"),
                # opacity=alt.condition(_legend_sel, alt.value(1.0), alt.value(0.05)),
            )
        )
        .properties(
            title=alt.TitleParams(
                text="Figure 11. Capacity distribution per participant",
                subtitle=[
                    "Boxplots showing the distribution of discharge capacity values for each participant",
                    "across all cycles and all repetitions.",
                ],
                anchor="start",
                orient="top",
                offset=20,
            ),
            width=325,
        )
        .configure_axisX(labelAngle=-45)
    )
    return (cd_cycling_capacity_participant,)


@app.cell
def _(cd_cycling_filtered_cycle_data):
    # CHARGE-DISCHARGE CYCLING EVALUATION
    # STEP 3b: Build boxplots from capacity data per repetition to compare the capacity distributions between repetitions

    # build domains for the capacity values
    _all_capacity = cd_cycling_filtered_cycle_data["discharge_capacity/mAh"].abs()
    _capacity_domain = [_all_capacity.min(), _all_capacity.max()]

    # construct a box plot
    cd_cycling_capacity_repetition = (
        (
            alt.Chart(
                cd_cycling_filtered_cycle_data,
            )
            .mark_boxplot(
                size=50,
                ticks={"size": 30},
                median={"color": "black", "thickness": 2},
                outliers={"size": 10, "shape": "circle"},
            )
            .encode(
                x=alt.X("repetition:O", title="Repetition"),
                y=alt.Y(
                    "discharge_capacity/mAh:Q",
                    title="(Discharge) Capacity / mAh",
                    scale=alt.Scale(domain=_capacity_domain),
                ),
                color=alt.Color("repetition:O", title="Repetition"),
                # opacity=alt.condition(_legend_sel, alt.value(1.0), alt.value(0.05)),
            )
        )
        .properties(
            title=alt.TitleParams(
                text="Figure 12. Capacity distribution per repetition",
                subtitle=[
                    "Boxplots showing the distribution of discharge capacity values for each repetition",
                    "across all cycles and all participants.",
                ],
                anchor="start",
                orient="top",
                offset=20,
            ),
            width=325,
        )
        .configure_axisX(labelAngle=0)
    )
    return (cd_cycling_capacity_repetition,)


@app.cell
def section_charge_discharge_cycling(
    cd_cycling_capacity_cycle_chart,
    cd_cycling_capacity_participant,
    cd_cycling_capacity_repetition,
    cd_cycling_capacity_time_chart,
    cd_cycling_charts,
    cd_cycling_filtered_df,
    cd_cycling_initial_discharge_capacity,
    slider_half_cycle,
    theoretical_capacity_mAh,
):
    mo.vstack(
        [
            mo.md("## Charge-Discharge Cycling"),
            mo.md("""
                This section allows you to visualize the results of the charge-discharge cycling experiments. You can select one or more files containing the charge-discharge data, and the notebook will generate visualizations to help you analyze the results and compare different repetitions and runs.
            """),
            mo.md("<br>"),
            mo.md("### Raw data exploration"),
            mo.md("""
                The expandable sections enables you to explore the raw charge-discharge cycling data of all selected datasets in more detail. You can view the data in a tabular format and apply filter and custom computations or use the interactive data explorer to filter, sort, and visualize the data as needed. While the functions are limited, it may help you gain a better understanding of the underlying data beyond the prepared visualizations below.
            """),
            mo.accordion(
                {
                    "Data table": cd_cycling_filtered_df,
                    # "Data explorer": mo.ui.data_explorer(cd_cycling_filtered_df),
                },
                lazy=True,
                multiple=True,
            ),
            mo.md("<br>"),
            mo.md("### Voltage-capacity data"),
            mo.md("""
                These plots show the relationship between the voltage and the capacity for each selected file. The shape of the curves can provide insights into the electrochemical processes occurring in the system, such as the presence of different plateaus corresponding to different electrochemical reactions, changes in internal resistance, and capacity fade over cycles. You can compare the curves across different participants and repetitions to identify trends or differences in the charge-discharge behavior. Use the slider to select the cycle to display.
            """),
            mo.lazy(
                mo.vstack(
                    [
                        mo.md("**Select cycle:**"),
                        slider_half_cycle,
                        cd_cycling_charts,
                    ]
                ),
                show_loading_indicator=True,
            ),
            mo.md("<br>"),
            mo.md("### Capacity distribution per participant and repetition"),
            mo.md(f"""
                These plots show the distribution of capacity values across all cycles for each participant and repetition, respectively. The boxplots display the median, interquartile range, and outliers of the capacity values, allowing you to compare the capacity distributions between participants and repetitions and identify trends or differences in the capacity performance. The average **initial (discharge) capacity** over the selected dataset ({len(cd_cycling_initial_discharge_capacity)} experiments) is **{cd_cycling_initial_discharge_capacity["capacity/mAh"].mean():.1f} mAh ± {(cd_cycling_initial_discharge_capacity["capacity/mAh"].std() if len(cd_cycling_initial_discharge_capacity) > 1 else 0):.1f} mAh** (uncertainty: standard deviation), which represents an average **capacity utilization of {(cd_cycling_initial_discharge_capacity["capacity/mAh"].mean() / theoretical_capacity_mAh):.1%}** with respect to the theoretical capacity as per the protocol defined electrolyte composition (0.2 M redox-active species).
            """),
            mo.md("<br>"),
            mo.lazy(
                mo.hstack(
                    [
                        cd_cycling_capacity_participant,
                        cd_cycling_capacity_repetition,
                    ]
                ),
                show_loading_indicator=True,
            ),
            mo.md("<br>"),
            mo.md("### Capacity fade"),
            mo.md("""
                These plots show the capacity retention over cycles and time for each selected file. The first plot shows the capacity at the end of each half cycle (i.e., after each charge and discharge step, respectively) over the cycle number, while the second plot shows the capacity over time. You can use these plots to analyze the capacity fade behavior of the system and identify trends or differences between participants and repetitions.
            """),
            mo.md("<br>"),
            mo.lazy(cd_cycling_capacity_cycle_chart, show_loading_indicator=True),
            mo.md("<br>"),
            mo.lazy(cd_cycling_capacity_time_chart, show_loading_indicator=True),
            mo.md("<br>"),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
