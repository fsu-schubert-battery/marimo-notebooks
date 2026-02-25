# International Flow Battery Reproducibility Study

## FSU Data Dashboard

This repository contains the data obtained by participants of the Friedrich Schiller University Jena from experiments performed during the international flow battery reproducibility study led by MIT and QUB. The data is evaluated with Python within an interactive Marimo notebook. 

## 🚀 Contributing data

Datasets can be contributed via Pull Request. The raw measurement files (BioLogic `*.mpr`) must follow a fixed directory layout so the automated precompute pipeline can process them.

### Directory structure

Place your data under `apps/public/data/` using the following hierarchy:

```
apps/public/data/
  {study_phase}/                 # e.g. phase_2a, phase_2b
    {participant}/               # your participant ID, e.g. P001
      {repetition}/              # measurement repetition: 1, 2, 3, …
        {flow_rate}/             # electrolyte flow rate in mL/min: 3.3, 8.3, 20.7, 25, …
          {technique}/           # see naming convention below
            *.mpr                # BioLogic raw data files
    Temperature/                 # (optional) temperature log per study phase
      DL-200T_temperature.csv    # CSV with columns: datetime, temperature_C
```

### Technique naming convention

Technique directories must use the following numbered prefixes so the precompute script can identify them:

| Directory name          | Description                  |
|-------------------------|------------------------------|
| `00 break-in`           | Break-in / conditioning      |
| `01 eis`                | Electrochemical impedance    |
| `02 polarisation`       | Polarisation curves          |
| `03 charge-discharge`   | Charge–discharge cycling     |
| `04 post-eis`           | Post-experiment EIS          |
| `05 post-polarisation`  | Post-experiment polarisation |

### Step-by-step

1. **Fork** this repository on GitHub.
2. Clone your fork and create a new branch:
   ```bash
   git checkout -b data/{your-name}
   ```
3. Add your `*.mpr` files into the correct directory structure under `apps/public/data/`.
4. Commit and push:
   ```bash
   git add apps/public/data/
   git commit -m "data: add {your-name} measurements for {phase}"
   git push origin data/{your-name}
   ```
5. Open a **Pull Request** against `main`.

Once the PR is merged, a GitHub Action will automatically:
1. Run the precompute script to extract the raw data into Parquet files.
2. Rebuild and deploy the interactive dashboard to GitHub Pages.

> **Note:** Directories containing `fail` in their name (e.g. `3-failed`) are automatically excluded from processing.

## 🧪 Local Development

### Prerequisites

- **Python ≥ 3.12**
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** – a fast Python package manager

### Setup

Clone the repository and navigate into it:

```bash
git clone https://github.com/fsu-schubert-battery/marimo-notebooks.git
cd marimo-notebooks
```

No manual virtual environment or `pip install` is required – `uv` resolves all dependencies automatically from the inline PEP 723 metadata in each notebook.

### Running the dashboard locally

```bash
uv run marimo run apps/ifbs_dashboard.py
```

This starts a local server (by default at `http://localhost:2718`) and opens the dashboard in your browser. The notebook's dependencies (`polars`, `scipy`, `altair`, etc.) are installed on the fly by `uv`.

To edit the notebook interactively instead:

```bash
uv run marimo edit apps/ifbs_dashboard.py
```

### Building the static site

To export all notebooks as a static HTML/WASM site (same as the GitHub Actions workflow):

```bash
uv run .github/scripts/build.py
```

This creates the `_site/` directory. Serve it locally with:

```bash
python -m http.server -d _site
```

Then open `http://localhost:8000`.
