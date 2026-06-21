# Data Directory

This directory is mounted into the Data Loader container at `/app/data`.

Source admission documents may be public or private depending on the university's release policy. Keep private or unreviewed source files out of git, but keep the manifest files committed so a clean checkout has a stable ingestion contract.

## Expected Files

- `manifest.json`: tracked ingestion manifest. It may contain an empty `documents` array until approved source files are added locally.
- `manifest.example.json`: documented example entry with all required fields.
- `*.md`: reviewed Markdown documents ready for ingestion. These remain ignored by default.

## Manifest Fields

Each document entry should include:

- `source`: exact filename under this directory.
- `language`: `ar`, `en`, or `mixed`.
- `faculty`: stable English faculty name when the document is faculty-specific.
- `doc_category`: stable category such as `admission`, `fees`, `curriculum`, `faculty_info`, `regulation`, `uni_info`, `req_courses`, or `courses_descriptions`.
- `version`: source version used for idempotent ingestion.
- `official_date`: publication or approval date in `YYYY-MM-DD` format when known.
- `checksum`: SHA-256 checksum of the source file.
- `visibility`: `public`, `private`, or `internal`.

Use `manifest.example.json` as a template when adding real documents.
