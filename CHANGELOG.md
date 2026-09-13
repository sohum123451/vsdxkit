# Changelog

This changelog covers `vsdxkit`. The project it descends from, and whose
history precedes 0.6.3 here, remains available at
<https://github.com/dave-howard/vsdx>.

From 0.7.1 onward this file is maintained by release-please, which writes a
section per release from the conventional-commit subjects on `main`. Edit the
release pull request rather than this file directly.

## [0.8.0](https://github.com/firmfooting/vsdxkit/compare/v0.7.1...v0.8.0) (2026-09-13)


### ⚠ BREAKING CHANGES

* allocate shape ids through one path that owns set_max_ids ([#270](https://github.com/firmfooting/vsdxkit/issues/270))

### Bug Fixes

* allocate shape ids through one path that owns set_max_ids ([#270](https://github.com/firmfooting/vsdxkit/issues/270)) ([615212f](https://github.com/firmfooting/vsdxkit/commit/615212f2f9d1a112d0838158d0a4f58cc6341eae))
* copy an inherited row onto the instance before writing to it ([#272](https://github.com/firmfooting/vsdxkit/issues/272)) ([2f582a4](https://github.com/firmfooting/vsdxkit/commit/2f582a46bc4957ac14731e71da1e57bff33cd513))

## [0.7.1](https://github.com/firmfooting/vsdxkit/compare/v0.7.0...v0.7.1) (2026-09-13)

**This release fixes a critical security defect. 0.7.0 was withdrawn from PyPI
because of it and cannot be reinstalled; upgrade to 0.7.1.**

### Security

* Jinja templates are rendered in a sandboxed environment
  ([#259](https://github.com/firmfooting/vsdxkit/pull/259))
  ([d5b735c](https://github.com/firmfooting/vsdxkit/commit/d5b735c95385032f72129e057a34484dab321d71)).

  `jinja_render_vsdx()` compiled text taken from the document being rendered —
  shape text, shape names, cell formulas — on Jinja's default environment, where
  that text is executable. A crafted `.vsdx` could reach the `os` module through
  a builtin's `__globals__` and run shell commands in the calling process, so
  rendering a document from an untrusted source was equivalent to running it.
  The context dictionary was readable by the document as well, exposing anything
  passed alongside it.

  All three compile sites now use `jinja2.sandbox.SandboxedEnvironment`. Ordinary
  templating is unchanged — loops, conditionals, filters and arithmetic behave
  exactly as before — while reaching through attributes raises
  `jinja2.exceptions.SecurityError`.

  The same defect exists in `vsdx`, the project this one descends from, in every
  released version up to and including 0.6.1. It has been reported privately to
  its maintainer as GHSA-2gwv-3c82-73r5. If you use that package, watch for its
  fix.

### Documentation

* correct attribution and release-day drift ([#265](https://github.com/firmfooting/vsdxkit/issues/265)) ([659b47b](https://github.com/firmfooting/vsdxkit/commit/659b47b5059cc186674c2d244e4e7e75f5b46035))

## 0.7.0 - 2026-09-13

**Withdrawn.** 0.7.0 was published and removed from PyPI the same day, over the
security defect fixed in 0.7.1. Everything below shipped in 0.7.1 instead. PyPI
does not permit a version number to be reused, so 0.7.0 will not return.

### Added

- The documentation is published to GitHub Pages at
  <https://firmfooting.github.io/vsdxkit/>, rebuilt on every push to `main` that
  touches the docs or the package. Sphinx autodoc reads the source, so the site
  would go stale the moment the API changed if publishing were manual. The build
  uses the same `-W --keep-going` gate as CI, so a warning cannot reach the
  published site by another route. The unused Read the Docs configuration is
  removed.
- A 0.x API notice at the top of the README and the documentation landing page:
  0.7 is the last release of the inherited API, and 1.0 renames `VisioFile` and
  `Container`, splits `Connect`, and removes the context manager.
- `tests/fixtures/com_reference/README.md` documents the COM reference corpus:
  what each scenario captured from Visio 16.0 and why, including the two
  scenarios whose COM calls failed, the `manifest.json` schema, and how to
  regenerate with `tools/com_reference.ps1`. CONTRIBUTING gains a "When a change
  needs Visio" section covering the `needs-visio` label and
  `tools/visio_check.ps1`.
- `docs/maintainers/upstream-sync.md` records how and when to check
  `dave-howard/vsdx` for fixes worth adopting, and the sync point last checked.
- CI runs the test suite on macOS as well as Linux and Windows, on the oldest
  and newest supported interpreters, which catches path-separator and
  case-sensitivity regressions before a release does.
- CI measures coverage on one matrix cell, publishes the per-file report to the
  job summary, uploads `coverage.xml` as an artifact, and fails the run below
  the `fail_under` threshold in `pyproject.toml`. The threshold starts at the
  suite's measured 90% and only ever rises.
- `Geometry`, `GeometryRow` and `GeometryCell` have direct tests, covering every
  line of `vsdx/geometry.py`: the master-geometry merge, `start_pos()`,
  `move()`, the `set_move_to()`/`set_line_to()` no-ops, and `RelMoveTo`
  handling. The tests characterise the code as it stands, faults included, and
  the docstrings now say what those faults are. `start_pos()` answers in
  shape-local coordinates for a `MoveTo` row but returns the shape's pin for a
  `RelMoveTo` one; `move()` and the coordinate setters write through an
  inherited row into the master, moving every other shape drawn from it; and a
  row added to a section is placed among the section's cells, ordered by index
  as text. Issues #239, #240 and #241 track the fixes.
- Package expansion limits: `VisioFile` inspects archive metadata before reading
  members and enforces caps on member count, per-member and total uncompressed
  size and compression ratio, and rejects duplicate and path-unsafe member names,
  raising `vsdx.PackageLimitError` with a stable `reason`. Defaults suit
  untrusted documents; trusted callers relax them via `limits=` or `limits_path=`.
- Renovate keeps the digest-pinned GitHub Actions and Python dependencies
  current, with grouped weekly update PRs and a uv lock maintenance pass.
- `VisioFileNotOpen` is now a genuine `Exception` subclass and is exported from
  the package root, so save-after-close is caught by normal `except Exception`
  handling and can be caught specifically.
- The CI build job now smoke-tests the built wheel in a clean virtual
  environment from outside the checkout: wheel contents are inspected for
  `py.typed` and both bundled media documents, and the installed distribution
  is exercised through `Media()`, `create_shape()`, connector creation, save
  and reopen before the artifact is uploaded.
- The `Connect` constructor validates its inputs and always produces a complete
  instance: the page and XML element are required, the element must be a
  namespaced `Connect` tag, and the schema-required `FromSheet`/`ToSheet`
  attributes must be present. `FromCell`/`ToCell` remain optional per the
  `Connect_Type` schema and read as `None` when absent. Invalid input raises
  `ValueError` instead of yielding an object that fails later on missing
  attributes.
- CI cancels superseded runs on the same ref via a concurrency group.
- Page `width`/`height` setters reject `None`, non-numeric and non-finite values
  and non-positive dimensions instead of silently writing `0.0`; the cell is
  left untouched on failure.
- Pyrefly runs at the `strict` preset with zero diagnostics at warning severity
  and no in-source type suppression comments.
- Every public definition (258 across the package) now carries an explicit
  return annotation, so Mypy consumers get real types instead of `Any`. A
  completeness gate (`tools/check_public_annotations.py`) and a Mypy consumer
  fixture (`tests/type_fixture.py`, run with `--disallow-untyped-calls`) keep
  the advertised typed contract checker-independent.
- Review-fix pass on merged PRs: the default `PackageLimits` are lowered to
  512 members, 64 MiB per member, 256 MiB total uncompressed and a 100:1
  ratio, so even at the caps loading materialises at most 256 MiB; the
  archive's declared entry count is checked against `max_members` before
  `ZipFile` parses the central directory; `Shape.connects`' `Connect`
  annotation is runtime-resolvable for `typing.get_type_hints` consumers; and
  `VisioFileDiff` streams members through a capped incremental decoder and
  hash instead of inflating each member wholesale. The action-pin drift
  checker is wired into CI.
- Page removal now deletes the page's relationship from `pages.xml.rels`, its
  `[Content_Types].xml` override and its page-rels part alongside the page part,
  so the OPC graph stays consistent. New pages allocate part names and
  relationship IDs from unused values instead of page count (removing a page
  then adding one no longer targets a colliding `pageN.xml`), and the returned
  `Page` carries its real page ID and relationship ID immediately.
- Typed contracts for shapes, pages, connectors, geometry, containers,
  templating, media and XML/package persistence.
- Shared required-XML helpers that report the missing package part rather than
  failing later on a `None` value.
- Regression coverage for in-place and named save destinations.
- `PagePosition.BEFORE` and `PagePosition.AFTER` now require a reference page:
  `add_page_at()` rejects them with `ValueError` instead of silently appending,
  and the resolver no longer falls back to `LAST` for invalid combinations.
  Integer, `FIRST` and `LAST` placements are asserted by index in tests.
- Current README and Sphinx guides for shape creation, connectors,
  re-anchoring, swimlanes, search and Jinja templates.
- Sphinx warning-as-error validation and a dedicated zizmor GitHub Actions audit
  in the CI gates.
- Malformed numeric ShapeSheet values raise `ValueError` naming the cell and raw
  value instead of silently reading as `0.0`; absent cells still read as `None`,
  keeping absent, malformed and genuine zero distinct.
- Package-wide import coverage now runs as a normal test across the supported
  Python and operating-system matrix.
- Test-suite strengthening: previously output-only tests now assert against
  independent expectations and reopen persisted files; a conditional-assert
  precedence bug in the end-arrow tests, an always-true assertion and an
  ignored expectations parameter are fixed; the two skipped diff tests are
  replaced with deterministic equivalents; and a four-mutant kill run
  documents that the new tests fail when the behaviour they name is broken.

### Fixed

- Every XML part is serialised with the namespace prefixes Visio itself writes.
  `ET.register_namespace` evicts any previous holder of a prefix, so registering
  four namespaces as the default left only the last one holding it and every
  Visio element serialised under a generated `ns0:` prefix. libvisio, which
  backs LibreOffice Draw's import filter, and draw.io's importer are stricter
  about prefixes than Visio is and reject such a package. Prefixes are now
  applied per part, so each part carries its own root vocabulary as the default.
  A CI job converts library output through LibreOffice Draw to keep it that way.
  Shape text no longer depends on the prefix either: the `cp`/`pp` formatting
  runs that bracket it are located by walking the `Text` element's children
  rather than by matching `ns0:` in serialised text.
- Copying a shape remaps every `Sheet.N!` and `SheetN!` reference in a formula,
  not only those a formula begins with. The connector engine writes
  `_XFTRIGGER(Sheet5!EventXFMod)` and `PAR(PNT(Sheet5!Connections.X1,...))` —
  no dot, and nested inside a function call — so a copied connector kept
  pointing at the source shapes and Visio dropped the glue. The walk also
  reaches the copied shape's own cells and cells nested inside `Section`s,
  which a copied group previously lost.
- Archive preflight derives the central directory's start from the end-of-
  central-directory record and detects ZIP64 by its locator, rather than
  trusting the declared values. A falsified declared count no longer stops the
  directory scan early, and a directory declaring zero entries is still scanned.
- `Page.delete_shape()` identifies the shape by element rather than by ID.
  Visio shape IDs are page-scoped and collide, so handing a page a shape
  belonging to a different page satisfied the guard and then deleted whichever
  shape on *this* page happened to share the number. It now raises `ValueError`,
  and says so when an ID collision is what made the call look plausible.
- `Shape.remove()` is deprecated and now delegates to `Page.delete_shape()`, the
  single deletion path. It previously detached the element and nothing else,
  leaving orphan connectors and dangling `Connect` records that Visio repairs on
  open, and it raised `ValueError` outright for a shape inside a group, whose
  XML is held by the group's `Shapes` container rather than by the group element.
  Deleting a shape through either API now also removes `Connect` records that
  name it as the target, not only those leading from it, and deleting a group
  removes the records naming its children — they disappear with the group, so a
  record pointing at one dangled. Deleting a shape that is not on the page now
  raises `ValueError` instead of silently doing nothing, and a connector that
  inherits `BeginX` from its master is recognised as a connector rather than
  surviving as a detached line. `Page.remove_connect_records()` takes a
  `match="from" | "either"` argument for those two cases.
- Reading Shape Data no longer changes the document. `DataProperty.value`'s
  getter used to clear a `No Formula` formula and stamp a `STR` unit while
  reading, so merely inspecting a shape's properties altered the bytes the
  package saved. The tidy-up now happens on write, where it belongs, and the
  setter creates the `Value` cell when the row has none instead of silently
  doing nothing (upstream dave-howard/vsdx#79).
- `Shape.data_properties` no longer serves a stale cache after a `Property` row
  is added, removed or replaced; the cache is keyed on the rows themselves. It
  also copies the master's dictionary rather than merging into it in place.
  Inherited properties are still resolved once per shape, so a change made to a
  master *after* an instance's properties have been read is not picked up until
  that instance's own rows change.
- Connector record removal normalises integer IDs before matching XML attributes,
  preserving the existing public-call behaviour.
- Shape and connector coordinate setters reject `None` instead of writing
  invalid `V="None"` ShapeSheet values.
- `save_vsdx()` now writes through a same-directory temporary archive and
  atomically replaces the target; failed in-place writes retain the original.
- Repeated in-place or named saves preserve untouched ZIP members and keep
  archive member paths relative.
- Combined routes such as `point|curved` retain connection-point glue while
  applying the requested line style.
- `apply_text_context()` again coerces non-string values before replacement.
- The legacy debug-handler bridge imports and runs on Python 3.10.
- `Shape.copy()` retains a valid Page or Shape parent rather than assigning an
  internal shape list as the parent.
- XML master-part types now match the package representation used at runtime.
- Missing `IX` values and list/dictionary confusion in geometry handling no
  longer flow into unguarded operations.
- Page-template matching handles absent names and non-matching Jinja markers.
- Connector re-anchoring handles missing endpoint IDs explicitly and avoids
  parameter shadowing.
- Media documents can be closed and opened again through one lazy access path.
- Page relationship parts use OPC separators on every operating system and are
  copied into the in-memory package when a page is copied.
- Bundled media paths no longer depend on the process working directory.
- Closing an in-memory document no longer deletes an unrelated same-stem
  directory beside the source file.
- Saving rejects an empty package instead of writing a corrupt archive and
  recognises an uppercase `.VSDX` suffix without appending another extension.

### Changed

- Tests write their output to pytest's `tmp_path` instead of `tests/out`, so a
  run no longer leaves 120 files in the checkout. `/tests/out/` is gone from
  `.gitignore`; delete any `tests/out` an earlier run left behind. A
  session-scoped fixture snapshots `git status --porcelain --untracked-files=all`
  at session start and fails the run if new entries appear afterwards, naming
  them. Diffing against the snapshot rather than demanding a clean tree keeps
  the check usable in a checkout that already has unrelated edits. Paths git
  ignores stay invisible to it, and it is skipped where git cannot report.
- The bundled media and palette documents are now parsed once per `VisioFile`
  rather than once per `create_shape` and `connect_shapes` call. A loop building
  N shapes and N connectors re-opened and re-parsed `media.vsdx` and
  `palette_extended.vsdx` 2N times; it now opens each at most once. The shared
  `Media` is owned by the document and released by `close_vsdx()`, which stays
  safe to call more than once, and a create or connect call after a close builds
  a fresh one instead of reusing a closed instance. `Media` remains public and
  independently constructible.
- `save_vsdx` now keeps the saved extension in step with the package kind. The
  kind comes from the content type of `visio/document.xml`, not the filename, so
  saving a macro-enabled package to a `.vsdx` destination — or a plain drawing to
  a `.vsdm` one — raises `ValueError` instead of writing a package whose
  extension and `[Content_Types].xml` disagree, which Visio reports as corrupt.
  The same check applies to an in-place `save_vsdx()` on a file that was renamed
  outside the library; it refuses rather than renaming the caller's path. A
  destination carrying neither Visio extension still gets the matching one
  appended, which for a macro-enabled package is now `.vsdm` rather than `.vsdx`.
  Callers relying on the old silent `.vsdx` suffix for `.vsdm` documents will see
  the new exception. The new `VisioFile.is_macro_enabled` property exposes the
  same determination.
- The documentation toolchain moved from the published `docs` extra to a PEP 735
  `docs` dependency group carrying its own `requires-python` floor, so Sphinx can
  track releases that need a newer interpreter than `vsdxkit` itself. Sphinx is
  now pinned to 9.1.0 and the docs build runs on Python 3.12. Anyone installing
  `vsdxkit[docs]` should install the `docs` group instead.
- The lint job checks and formats the whole `tests` tree rather than two
  selected test modules; the remaining test files have been brought into
  compliance (semantic fixes: `raise AssertionError` instead of `assert
  False`, `zip(..., strict=True)`, `enumerate()` accumulation, exception
  chaining).
- zizmor is pinned to the committed uv lock (`uv run zizmor`) instead of
  resolving ad hoc via `uvx` at run time.
- Package keywords no longer carry inherited upstream terms.
- CONTRIBUTING.md and SECURITY.md now describe this fork (uv workflow,
  gate list, private vulnerability reporting on this repository) rather than
  inheriting the upstream project's text.
- CI now uses a committed uv lock for normal test, lint and build jobs. The
  minimum-dependency job regenerates that lock with
  `--resolution lowest-direct` and runs the full test suite on the oldest and
  newest supported Python versions.
- Test and development tooling now use uv dependency groups instead of a
  published `dev` extra.
- The pyrefly preset is now `strict` rather than `basic`.
- Runtime dependency floors now match the supported API and security baseline:
  `Jinja2>=3.1.6`, `deprecation>=2.1.0`, and `typing-extensions>=4.4.0` on
  Python 3.10–3.11. Python 3.12 and later use `typing.override` directly.
- `insert_shape()` now validates that `page_path` identifies the supplied
  `Page` instead of silently allocating IDs against whichever page was visited
  last.
- GitHub's default branch is now `main`; CI and documentation references follow
  the renamed branch.
- `VisioFileDiff` reads archive members in-memory: it no longer extracts
  beside the source files (which could delete a user's same-stem directory)
  and undecodable members compare by SHA-256 digest, so two different binary
  members are reported as changed instead of collapsing into one placeholder.
- Documentation now names the distribution `vsdxkit`, retains `import vsdx`,
  and requires Python 3.10 or later.

## 0.6.3

- Renamed the distribution to `vsdxkit` while preserving the `vsdx` import.
- Replaced legacy packaging with `pyproject.toml`.
- Added ruff, pyrefly and a Python 3.10–3.14 Linux/Windows CI matrix.
- Added connector creation, master import, connector re-anchoring, shape
  creation from the bundled palette and CFF swimlane operations.
- Split master import, templating and XML persistence out of `vsdxfile.py`.
- Replaced package `print()` diagnostics with standard-library logging.
