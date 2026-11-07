# MODIS teaching presentation

`build_deck.mjs` reads the generated exact analysis summary and CSV tables from
`reports/modis_2024_2025`. It authors 16 slides with native editable tables and
charts through `@oai/artifact-tool`. Speaker notes contain source citations and
the explanations used in the companion notes document.

The runtime paths below refer to the bundled runtime supplied for this task.

```bash
RUNTIME_NODE_MODULES=/home/da-rog/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules \
DECK_FILENAME=MODIS_Terra_Aqua_2024_2025_Presentation_revision.pptx \
/home/da-rog/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
analysis/modis_2024_2025/presentation/build_deck.mjs
```

Keep `presentation/node_modules` linked to that runtime's `node/node_modules`.
The finalizer will refuse to overwrite an existing final presentation. Choose a
new filename for revisions. Native chart workbooks intentionally store a display
snapshot rounded to 12 significant digits for Excel compatibility. The source
analysis CSVs keep their exact computed values.

Use only the bundled LibreOffice to export a checked final deck to PDF:

```bash
/home/da-rog/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/soffice \
--headless --convert-to pdf --outdir reports/modis_2024_2025 \
reports/modis_2024_2025/MODIS_Terra_Aqua_2024_2025_Presentation_revision.pptx
```

Drafts and renders stay in `reports/modis_2024_2025/.build/presentation`.
The private validation receipt stays in `presentation/.validation`, outside the
delivery directory. Revisions require visual inspection of all slides after
finalization and PDF export. Do not claim native PowerPoint testing from a
render or a structural validation receipt.
