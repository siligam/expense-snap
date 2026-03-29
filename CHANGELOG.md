# Changelog

## [0.5.0] — 2026-03-29

### Added
- PDF hover preview in history tab — renders first page via pdf.js on hover
- Filename deduplication — bills with identical date/category/meal_type get a `_2`, `_3` suffix
- Playwright frontend test suite covering both of the above
- GitHub Actions CI (pytest) and docs deployment (GitHub Pages)
- MIT license

### Fixed
- `e.currentTarget` going null across async boundary in `showPdfThumbPreview`

## [0.4.0] — 2026-03-26

### Added
- Rich CLI output for `bill-extractor extract`
- Column drag-to-reorder in history table
- MkDocs documentation site

## [0.3.0] — earlier

### Added
- History tab with sort, filter, and pagination
- IndexedDB + optional File System Access API persistence
- Duplicate detection
- Good / Bad Result marking with correction textarea
