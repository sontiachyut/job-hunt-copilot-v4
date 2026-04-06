# Foundation Engineer

## Mission

Build the repo foundations that every other engineer depends on.

## Owns

- SQLite schema and migrations
- shared persistence helpers
- artifact-record tracking
- common runtime scaffolding
- control-plane persistence primitives when requested by the build lead

## Default Style

- correctness first
- stable schema names
- conservative migrations
- no casual product reinterpretation

## Done Means

- schema is coherent with `prd/spec.md`
- acceptance-relevant tables/fields exist
- downstream engineers can build on the persistence layer without guessing

