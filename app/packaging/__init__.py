"""Per-job artifact packaging.

Each module here produces a file (or a data structure) that ends up inside
`outputs/<date>/job_<id>/`:

- `cover_letter` -> `cover_letter.docx`
- `screening`    -> `screening.json`

The resume itself is produced by the existing `app.services.resume_docx`.
"""
