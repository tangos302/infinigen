"""Append `requested_assets.md` entries for missing factories.

Two storage modes share the same file format. The file lives in
`_artifacts/maquette/requested_assets.md` (project-level, not per-run).

  - `append`: add new requests, dedupe against existing entries
  - `read`:   parse current entries (used by the local-mode auto-fix
              flow to decide what to implement next)

Format (markdown table for human-readability + easy parsing):

```markdown
# Maquette · Requested Assets

| Factory | First seen | Last seen | Count | Spec |
|---|---|---|---|---|
| `LowPolyVehicleFactory` | 2026-04-28 | 2026-04-28 | 2 | war rig / battle vehicle |
```
"""

from __future__ import annotations

import re
from datetime import date
from dataclasses import dataclass, field
from pathlib import Path

from .factories_guide import FORK_ROOT


REQUESTED_ASSETS_PATH = (
    FORK_ROOT.parent / "requested_assets.md"
)


@dataclass
class RequestedAsset:
    factory: str
    first_seen: str
    last_seen: str
    count: int
    spec: str = ""


def _parse_request_line(s: str) -> tuple[str, str]:
    """Parse a `# REQUESTED_ASSET: <Name> — <spec>` line content.
    Returns (factory_name, spec_text). The line is the raw text
    AFTER the `REQUESTED_ASSET:` marker."""
    # Accept various dash chars between name and spec
    parts = re.split(r"\s*[—\-–]\s*", s, maxsplit=1)
    name = parts[0].strip().rstrip(":")
    spec = parts[1].strip() if len(parts) > 1 else ""
    # Some Claude outputs may include backticks
    name = name.strip("`")
    return name, spec


def _load_existing(path: Path) -> dict[str, RequestedAsset]:
    if not path.exists():
        return {}
    out: dict[str, RequestedAsset] = {}
    text = path.read_text()
    # Parse rows of the markdown table
    row_re = re.compile(
        r"^\|\s*`([^`]+)`\s*\|\s*([\d-]+)\s*\|\s*([\d-]+)\s*\|\s*(\d+)\s*\|\s*(.*?)\s*\|$",
        re.MULTILINE,
    )
    for m in row_re.finditer(text):
        out[m.group(1)] = RequestedAsset(
            factory=m.group(1),
            first_seen=m.group(2),
            last_seen=m.group(3),
            count=int(m.group(4)),
            spec=m.group(5),
        )
    return out


_TABLE_HEADER = "| Factory | First seen | Last seen | Count | Spec |"
_TABLE_DIVIDER = "|---|---|---|---|---|"
_DOC_HEADER = """\
# Maquette · Requested Assets

Tracker of factories the pipeline wished existed. Populated by
`infinigen.maquette.pipeline` runs that emitted
`# REQUESTED_ASSET: ...` markers in their build scripts.

In `--local` mode a second Claude pass implements these on the fly. In
`--remote` mode (default) the table just accumulates and a separate
batch run drains it.

"""


def _write(path: Path, entries: dict[str, RequestedAsset]) -> None:
    sorted_entries = sorted(entries.values(), key=lambda e: (-e.count, e.factory))
    rows = [_DOC_HEADER, _TABLE_HEADER, _TABLE_DIVIDER]
    for e in sorted_entries:
        rows.append(
            f"| `{e.factory}` | {e.first_seen} | {e.last_seen} | "
            f"{e.count} | {e.spec} |"
        )
    rows.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows))


def append(request_lines: list[str], *,
           path: Path = REQUESTED_ASSETS_PATH,
           today: str | None = None) -> dict[str, RequestedAsset]:
    """Add request_lines (each a `# REQUESTED_ASSET:`-stripped string)
    to the tracker. Existing entries get count incremented + last_seen
    updated. Returns the merged dict."""
    today = today or date.today().isoformat()
    entries = _load_existing(path)
    for line in request_lines:
        name, spec = _parse_request_line(line)
        if not name:
            continue
        if name in entries:
            entries[name].count += 1
            entries[name].last_seen = today
            if spec and not entries[name].spec:
                entries[name].spec = spec
        else:
            entries[name] = RequestedAsset(
                factory=name, first_seen=today, last_seen=today,
                count=1, spec=spec,
            )
    _write(path, entries)
    return entries


def read(path: Path = REQUESTED_ASSETS_PATH) -> dict[str, RequestedAsset]:
    return _load_existing(path)
