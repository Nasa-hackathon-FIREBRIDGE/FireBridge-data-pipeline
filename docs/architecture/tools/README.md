# Rebuilding the design dictionary and checks

`schema.sql` is the column/key source of truth. `column_notes.json` supplies a plain-language meaning for every column. `publication_checks.md` lists cross-record/scientific rules that SQL alone cannot enforce. `endpoint_catalog.json` maps the API document to real tables.

Use an isolated Python environment with `pglast==8.7`, then run:

```bash
python docs/architecture/tools/build_dictionary.py
```

The script regenerates `DATABASE.md` and `validation.json`. It parses the PostgreSQL schema and query examples, verifies foreign-key tables/columns/types and unique targets, checks named index columns, requires an explanation for every column, and checks endpoint table references and local links.

It does not connect to PostgreSQL, install PostGIS, fetch provider data, execute scientific queries, start services or validate runtime query performance. Those are implementation acceptance checks. To change the schema, edit the SQL and matching column explanations together, then regenerate.
