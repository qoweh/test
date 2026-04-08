# QGIS Final Files

## Use These 2 Files

1. `uiwang_cctv_priority_weighted_inferred_30m.gpkg`
- Main final layer for CCTV priority analysis.
- Contains `grid_score` and `score_points` layers.

2. `uiwang_roads_traffic_inferred.geojson`
- Road context layer with inferred traffic matching fields.
- Useful for map overlay and QA checks.

## Quick Load Order in QGIS

1. Load `uiwang_cctv_priority_weighted_inferred_30m.gpkg` (`grid_score`).
2. Load `uiwang_roads_traffic_inferred.geojson`.
3. Style by `total_score_0_100` and optionally filter top ranks with `priority_rank <= 150`.

## Notes

- Other files in `plus/` and `second report/gpt/` are intermediate, reproducibility, or comparison artifacts.
- For practical map production, these two files are sufficient.

## CSV Exports (from inferred GPKG)

- `this_uiwang_grid_score_30m_equal_inferred.csv`
- `this_uiwang_grid_score_30m_weighted_inferred.csv`

These are extracted from each GPKG `grid_score` layer for spreadsheet/statistical use.
