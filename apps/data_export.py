# /// script
# name = "ifbs-evaluation"
# version = "0.1.0"
# description = "Notebook for extracting data from .mpr files for the Interlaboratory Study – Phase 2b"
# requires-python = ">=3.12"
# dependencies = [
#     "marimo[recommended]>=0.19.11",
#     "galvani>=0.4.1",
#     "polars>=0.19.0"
# ]
#
# [tool.marimo.runtime]
# output_max_bytes = 30_000_000
# ///

import marimo

__generated_with = "0.19.11"
app = marimo.App(width="medium")


@app.cell
def _():
    import io, json
    import marimo as mo
    from datetime import datetime
    # from pathlib import Path
    #import altair as alt
    from galvani.BioLogic import MPRfile
    import polars as pl
    return io, json, mo, pl, datetime, MPRfile

@app.cell
def _(mo):
    # --------------------------------------------------------------------------------------
    # Utility functions
    # --------------------------------------------------------------------------------------

    # CUSTOM CALLOUT
    CALLOUT_STYLES = {
        "success": dict(bg="#eaffea", border="#145a14", text="#145a14"),
        "info": dict(bg="#eef6ff", border="#1a3aa6", text="#1a3aa6"),
        "warn": dict(bg="#fffbe6", border="#8a5a00", text="#8a5a00"),
        "danger": dict(bg="#fff0f0", border="#b00000", text="#b00000"),
    }

    def custom_callout(message: str, kind: str = "info"):
        if message is None:
            return None

        style = CALLOUT_STYLES.get(kind, CALLOUT_STYLES["info"])
        return mo.md(
            f"""
            <div style="
              border-left: 4px solid {style["border"]};
              background: {style["bg"]};
              color: {style["text"]};
              padding: 8px 12px;
              border-radius: 8px;
              box-shadow: 0 2px 6px rgba(0,0,0,0.08);
              margin: 8px 0;
            ">
              {mo.md(message).text}
            </div>
            """
        )

    return (custom_callout,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## **Data extractor for Phase 2b**
    This notebook is here to facilitate data extraction from `.mpr` files
    measured for the _Interlaboratory Study – Phase 2b_. It uses the
    `galvani` library to read `.mpr` files and displays the data in a
    tabular format, which then can be copied into the
    [data entry template](https://docs.google.com/spreadsheets/d/1W0j3OcJP7UGOxwwBOAo0UCVApscNUr5z/edit?usp=sharing&ouid=103887018913708710245&rtpof=true&sd=true).
    """)
    return


@app.cell
def _(mo):
    step1_form = (
        mo.md(
            """
            ### **Step 1** – Import experimental data

            Please select the experiment type and the corresponding `.mpr` file to load the data. 
            The file should be located in the `data/phase_2b` subfolder of this repository.

            **Experiment type**  
            {experiment}

            **File**  
            {file}
            """
        )
        .batch(
            experiment=mo.ui.dropdown(
                options=["Impedance", "Polarisation", "Charge-Discharge Cycling"],
                label="",
            ),
            #        file=mo.ui.file_browser(
            #            initial_path=Path("data/phase_2b"),
            #            filetypes=[".mpr"],
            #            selection_mode="file",
            #            multiple=False,
            #            restrict_navigation=False,
            #        ),
            file=mo.ui.file(
                kind="button", 
                filetypes=[".mpr"], 
                label="Select file")
            ,
        ).form(
            submit_button_label="Load"
        )
    )

    step1_form
    return (step1_form,)


@app.cell
def _(MPRfile, custom_callout, io, mo, pl, step1_form):
    # wait for user input and check if form data is available
    mo.stop(
        step1_form.value is None,
        custom_callout(
            "Please select both a file and experiment type and click 'Load'.",
            kind="info",
        ),
    )

    # get form data
    form_data = step1_form.value

    # wait for user input and check if form data is available
    mo.stop(
        (form_data["file"] is None)
        | (len(form_data["file"]) == 0)
        | (form_data["experiment"] is None),
        custom_callout("Please select both a file and experiment type.", kind="info"),
    )

    # extract the required information from the form
    # file_path = form_data["file"][0].path
    experiment_type = form_data["experiment"]
    file_upload = form_data["file"]

    # load data from selected file
    # with open(file_path, "rb") as handle:
    #    mpr = MPRfile(handle)
    #    df = pl.DataFrame(mpr.data)#
    #
    #    # rename columns
    #    df = df.rename({
    #        "<Ewe>/V": "Ewe/V",
    #        "<I>/mA": "I/mA",
    #    }, strict=False)

    # load data from uploaded file
    with io.BytesIO(file_upload[0].contents) as handle:
        mpr = MPRfile(handle)
        df = pl.DataFrame(mpr.data)

        # rename columns
        df = df.rename(
            {
                "<Ewe>/V": "Ewe/V",
                "<I>/mA": "I/mA",
            },
            strict=False,
        )

    # check if the dataframe was loaded successfully
    if df is None or df.is_empty():
        raise Exception("Data loading failed")
    file_token = f"{file_upload[0].name}:{len(file_upload[0].contents)}"
    return df, experiment_type, file_upload, mpr


@app.cell
def _(custom_callout, df, experiment_type, mo, pl):
    callout = None
    callout_kind = None

    # select the relevant columns
    match experiment_type:
        case "Impedance":
            # filter for last cycle and required columns
            df_filtered = df.filter(
                pl.col("cycle number") == pl.col("cycle number").max()
            )["time/s", "freq/Hz", "-Im(Z)/Ohm", "Re(Z)/Ohm"]

        case "Charge-Discharge Cycling" | "Polarisation":
            # remove last half cycle using the half cycle column
            if experiment_type == "Charge-Discharge Cycling":
                df_filtered = df.filter(
                    pl.col("half cycle") < pl.col("half cycle").max()
                )
            else:
                df_filtered = df

            # filter columns
            if "I/mA" in df.columns:
                df_filtered = df_filtered["time/s", "I/mA", "Ewe/V"]

            elif "dq/mA.h" in df_filtered.columns:
                callout_kind = "warn"
                callout = """
                            **Warning:** Missing current column `I/mA`. Calculating it manually from `dq/mA.h` and `time/s` instead.
                          """

                # Calculate current in mA from dq/mA.h and time/s using derivative
                df_filtered = df_filtered.with_columns(
                    (pl.col("dq/mA.h") * 3600 / pl.col("time/s").diff()).alias("I/mA")
                )["time/s", "I/mA", "Ewe/V"].fill_null(0)

            elif "control/V/mA" in df_filtered.columns:
                callout_kind = "warn"
                callout = """
                            **Warning:** Missing current column `I/mA`. Using `control/V/mA` instead.
                          """

                df_filtered = df_filtered.with_columns(
                    pl.col("control/V/mA").alias("I/mA")
                )["time/s", "I/mA", "Ewe/V"]

            else:
                callout_kind = "danger"
                callout = """
                            **Error:** Missing current columns `I/mA` and control/V/mA. Please check your data file.
                          """
                df_filtered = None

        case _:
            callout = mo.md(
                """
                **Error**</br>
                Unknown experiment type selected. Please select a valid experiment type.
                """
            ).callout(kind="danger")
            df_filtered = None

    custom_callout(callout, callout_kind)
    return (df_filtered,)


@app.cell
def _(df, df_filtered, experiment_type, file_upload, mo, mpr, pl):
    match experiment_type:
        case "Impedance":
            # count points per decade in log10 space (not using min and max frequencies since )
            df_count = df_filtered.with_columns(
                pl.col("freq/Hz").log10().round(0).alias("freq/Hz")
            )
            df_count = df_count.filter(
                (pl.col("freq/Hz") > -2) & (pl.col("freq/Hz") < 5)
            )
            points_per_decade = df_count["freq/Hz"].unique_counts().mean()

            # output for user
            step2_info = f"""
                            ### **Step 2** – Inspect impedance data

                            **Experiment info**

                            - File name: `{file_upload[0].name}`
                            - Start date (yyyy-mm-dd): `{mpr.startdate.strftime("%Y-%m-%d")}`
                            - Start time (hh-mm-ss): `{mpr.timestamp.strftime("%H:%M:%S")}`
                            - End date (yyyy-mm-dd): `{mpr.enddate.strftime("%Y-%m-%d")}`
                            - Number of cycles: `{int(df["cycle number"].unique().len())}`
                            - Frequency range: `{round(df["freq/Hz"].max() / 1000):.0f}` kHz – `{int(df["freq/Hz"].min() * 1000)} mHz`
                            - Points per decade (log10 space): `{round(points_per_decade):.0f}`

                            **Dataframe info**

                            - Rows: `{df.height}`
                            - Columns: `{df.width}`
                            - Column names: `{", ".join(df.columns)}`

                            **Experimental data**

                            Please check the loaded and filtered data below. If everything looks good, click the "Copy to clipboard" button in the table below to copy the data and paste it into the data entry template.

                            {{dataframe}}
                        """

        case "Polarisation":
            # output for user
            step2_info = f"""
                            ### **Step 2** – Inspect polarisation data

                            **Experiment info**

                            - File name: `{file_upload[0].name}`
                            - Start date (yyyy-mm-dd): `{mpr.startdate.strftime("%Y-%m-%d")}`
                            - Start time (hh-mm-ss): `{mpr.timestamp.strftime("%H:%M:%S")}`
                            - End date (yyyy-mm-dd): `{mpr.enddate.strftime("%Y-%m-%d")}`
                            - Number of pulses (incl. initial rest step): `{int(df["Ns"].unique().len() / 2 + 1):.0f}`

                            **Dataframe info**

                            - Rows: `{df.height}`
                            - Columns: `{df.width}`
                            - Column names: `{", ".join(df.columns)}`

                            **Experimental data**

                            Please check the loaded and filtered data below. If everything looks good, click the "Copy to clipboard" button in the table below to copy the data and paste it into the data entry template.

                            {{dataframe}}
                        """

        case "Charge-Discharge Cycling":
            # output for user
            step2_info = f"""
                            ### **Step 2** – Inspect charge-discharge cycline data

                            **Experiment info**

                            - File name: `{file_upload[0].name}`
                            - Start date (yyyy-mm-dd): `{mpr.startdate.strftime("%Y-%m-%d")}`
                            - Start time (hh-mm-ss): `{mpr.timestamp.strftime("%H:%M:%S")}`
                            - End date (yyyy-mm-dd): `{mpr.enddate.strftime("%Y-%m-%d")}`
                            - Number of cycles: `{(df["half cycle"].max() + 1) / 2:.0f}`
                            - Average capacity: `{df["dq/mA.h"].abs().cum_sum().max() / df["half cycle"].max():.2f} mA.h`

                            **Dataframe info**

                            - Rows: `{df.height}`
                            - Columns: `{df.width}`
                            - Column names: `{", ".join(df.columns)}`

                            **Experimental data**

                            Please check the loaded and filtered data below. If everything looks good, click the "Copy to clipboard" button in the table below to copy the data and paste it into the data entry template.

                            {{dataframe}}
                        """
        case _:
            step2_info = """
                            ### **Step 2** – Inspect data

                            **Error**

                            Unknown experiment type selected. Please select a valid experiment type.
                        """

    step2_form = (
        mo.md(step2_info)
        .batch(
            dataframe=mo.ui.table(
                data=df_filtered,
            ),
        )
        .form(
            submit_button_label="Confirm",
        )
    )

    step2_form
    return (step2_form,)


@app.cell
def _(custom_callout, df_filtered, mo, step2_form):
    mo.stop(
        step2_form.value is None,
        custom_callout(
            "Please inspect the data and select the desired decimal separator before copying.",
            kind="info",
        ),
    )

    # get dataframe as csv text with tab separator and no header, using the selected decimal separator
    text = df_filtered.write_csv(
        separator="\t", 
        include_header=False,
    )
    return (text,)


@app.cell
def _(json, mo, step2_form, text):
    mo.stop(
        step2_form.value is None,
        None,
    )

    # copy-to-clipboard button
    iframe = mo.iframe(
    f"""
    <!doctype html>
    <html>
      <body style="
          font-family: system-ui;
          margin: 0;
          padding: 20px 0px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
      ">
        <!-- Left side -->
        <div style="display:flex; align-items:center; gap:10px;">
          <label style="font-size:14px; display:flex; align-items:center; gap:8px;">
            Decimal separator:
            <select id="sep" style="
                padding: 8px 10px;
                background: #ffffff;
                border: 1px solid #a3a3a3;
                border-radius: 6px;
                font-size: 14px;
            ">
              <option value=".">.</option>
              <option value=",">,</option>
            </select>
          </label>
        </div>

        <!-- Right side -->
        <button id="copy" style="
            min-width: 170px;
            padding: 10px 15px;
            background: #F2F5F9;
            border: 1px solid #a3a3a3;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
        ">
          Copy to clipboard
        </button>

        <script>
          const originalText = {json.dumps(text)};

          function applyDecimalSeparator(s, sep) {{
            if (sep === ".") return s;
            return s.replace(/(\\d)\\.(\\d)/g, `$1${{sep}}$2`);
          }}

          const copyBtn = document.getElementById("copy");
          const sepSel  = document.getElementById("sep");

          copyBtn.addEventListener("click", async () => {{
            const sep = sepSel.value;
            const textToCopy = applyDecimalSeparator(originalText, sep);

            try {{
              await navigator.clipboard.writeText(textToCopy);

              copyBtn.style.background = "#eaffea";
              copyBtn.style.color = "#145a14";
              copyBtn.textContent = "✔︎ Copied!";

              await new Promise(r => setTimeout(r, 2000));

              copyBtn.style.background = "#F2F5F9";
              copyBtn.style.color = "#000000";
              copyBtn.textContent = "Copy to clipboard";
            }} catch (e) {{
              console.error(e);

              copyBtn.style.background = "#fff0f0";
              copyBtn.style.color = "#b00000";
              copyBtn.textContent = "✖ Failed!";

              await new Promise(r => setTimeout(r, 2000));

              copyBtn.style.background = "#F2F5F9";
              copyBtn.style.color = "#000000";
              copyBtn.textContent = "Copy to clipboard";
            }}
          }});
        </script>
      </body>
    </html>
    """,
    width="100%",
    height="86px",
    )

    # Step description
    body = mo.vstack([
        mo.md(f"""
        ### **Step 3** – Copy data to clipboard
        Please click the 'Copy to clipboard' button below to copy the data and paste it into your local copy of the data entry template. The decimal separator you selected in the previous step will be used in the copied data. If you encounter any issues with copying to clipboard (e.g., due to browser permissions), please use the download option below the table to download the data as a .csv file and then copy it from there.
        """),
        iframe
    ], gap=0)

    mo.Html(f"""
    <div style="
      border: 1px solid rgba(0,0,0,0.3);
      border-radius: 10px;
      padding: 24px;
      background: #fcfcfc;
      box-shadow: 4px 4px 4px rgba(0,0,0,0.08);
    ">
      {body}
    </div>
    """)
    return


if __name__ == "__main__":
    app.run()
