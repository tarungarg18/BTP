# envv4 status

The QC GeoTIFF writer now uses the Assam Albers CRS and metric pixel size.

`qc_report.json` and `date_flexibility.md` in this folder were produced before that change. They are not validation of the current envv4 grid. A fresh Earth Engine audit was not run for this commit, so those older numbers must not be presented as the current result.

Regenerate with:

```bash
python scripts/run_qc_audit.py
```
