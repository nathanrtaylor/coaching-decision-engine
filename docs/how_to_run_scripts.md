

## python to run data extract process using yaml files under extraction

# 1. compile sql scripts (optional, useful if you want to validate sql)
python .\extraction\scripts\compile_sql.py --config .\extraction\configs\extract_run.yaml    

# 2. run extract (gets data from EDP and puts it in raw data files)
python .\extraction\scripts\run_extract.py --config .\extraction\configs\extract_run.yaml    

## python command to run the pipeline and turn raw data into signals
python -m cde.cli.run_pipeline --raw-dir data/raw/weekly/latest --out-dir outputs/runs/2026-03-03_TEST --configs-dir configs 

