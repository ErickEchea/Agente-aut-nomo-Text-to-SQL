# data/sqlite

SQLite files placed here can be registered as data sources under **Connections → Add connection**. The
backend mounts this directory read-only at `/data/sqlite` (`NEXUS_CONNECTIONS__SQLITE_DIR`). It only opens
files inside the directory, with `mode=ro` and `PRAGMA query_only` (ADR-0013).

```bash
make sqlite-demo   # exports the retail demo (scale 0.1) as retail_mini.sqlite
```

`retail_mini.sqlite` has the same tables, comments (as trailing `--` comments in the DDL), keys and
indexes as the PostgreSQL demo. As in the PostgreSQL demo, `detalle_ventas(producto_id)` deliberately
has no index, so the optimizer has a full scan to report.

Generated files are git-ignored. Only this README and `.gitkeep` are tracked.
