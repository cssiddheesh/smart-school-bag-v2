# Changelog

## 2.0.0
* New: packing sessions (start, continue, reset, complete, summary); no stale scans carried between days.
* New: single scan pipeline for real and simulated cards, with duplicate/not-required/unknown/disabled feedback and repeat-read debounce.
* New: live dashboard updates (cheap revision polling), honest RFID reader status, reader abstraction with experimental keyboard and serial adapters, reader read-log.
* New: Exhibition mode, book and timetable management, history filters and sessions, settings, optional admin PIN, backup/restore, recovery mode.
* New: versioned, non-destructive database migrations; WAL mode; indexes; foreign keys.
* Security: CSRF on every write, CSP and security headers, generated secret key, removed public scan endpoint, safe redirects, validated uploads.
* Removed: decorative hero/animations, duplicated status blocks, duplicate form/API routes, unused modules.
