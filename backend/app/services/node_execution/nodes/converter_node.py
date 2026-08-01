from __future__ import annotations

import csv
import io
import json

from app.services.node_execution.base import NodeExecutionContext

_DELIMITER_ESCAPES = {"\\t": "\t", "\\n": "\n", "\\r": "\r"}


def _resolve_delimiter(raw: object) -> str:
    """Resolve the configured delimiter, honoring escapes like ``\\t`` for tab."""
    text = str(raw) if raw not in (None, "") else ","
    text = _DELIMITER_ESCAPES.get(text, text)
    return text[:1] or ","


def _dedupe_headers(header: list[str]) -> list[str]:
    """Make duplicate header names unique (``a, a`` -> ``a, a_2``).

    A generated suffix is bumped until the candidate is free — not already used
    and not another original column name elsewhere in the header — so a real
    column such as ``a_2`` is never overwritten and no value is dropped.
    """
    originals = list(header)
    used: set[str] = set()
    result: list[str] = []
    for name in originals:
        candidate = name
        if candidate in used:
            index = 2
            candidate = f"{name}_{index}"
            while candidate in used or candidate in originals:
                index += 1
                candidate = f"{name}_{index}"
        used.add(candidate)
        result.append(candidate)
    return result


def _coerce_rows(value: object) -> list:
    """Normalize an arbitrary value into a list of rows for CSV building."""
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            value = json.loads(stripped)
        except (ValueError, TypeError):
            return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return list(value)
    return []


def _normalize_columns(columns_raw: object) -> list[str] | None:
    """Accept an explicit column order as a list or a comma-separated string."""
    if isinstance(columns_raw, str):
        columns = [c.strip() for c in columns_raw.split(",") if c.strip()]
        return columns or None
    if isinstance(columns_raw, list):
        columns = [str(c) for c in columns_raw]
        return columns or None
    return None


def _csv_to_json(text: object, delimiter: str, has_header: bool, trim_values: bool) -> list:
    """Parse CSV text into a list of row dicts (with header) or row lists."""
    if not isinstance(text, str):
        text = str(text)
    # Strip a leading UTF-8 BOM so Excel exports don't produce a "\ufeffname" key.
    text = text.lstrip("\ufeff")
    if text.strip() == "":
        return []
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if trim_values:
        rows = [[cell.strip() for cell in row] for row in rows]
    if not rows:
        return []
    if not has_header:
        return rows
    header = _dedupe_headers(rows[0])
    return [
        {header[i]: (row[i] if i < len(row) else "") for i in range(len(header))}
        for row in rows[1:]
    ]


def _json_to_csv(
    value: object, delimiter: str, include_header: bool, columns: list[str] | None
) -> str:
    """Build CSV text from a list of dicts (or lists), escaping per RFC 4180."""
    rows = _coerce_rows(value)
    buffer = io.StringIO()
    if rows and isinstance(rows[0], dict):
        if columns is not None:
            fieldnames = columns
        else:
            fieldnames = []
            for row in rows:
                if isinstance(row, dict):
                    for key in row:
                        if key not in fieldnames:
                            fieldnames.append(key)
        writer = csv.DictWriter(
            buffer,
            fieldnames=fieldnames,
            delimiter=delimiter,
            extrasaction="ignore",
            lineterminator="\n",
        )
        if include_header:
            writer.writeheader()
        for row in rows:
            source = row if isinstance(row, dict) else {}
            writer.writerow({name: source.get(name, "") for name in fieldnames})
    else:
        writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
        for row in rows:
            writer.writerow(row if isinstance(row, list) else [row])
    return buffer.getvalue().rstrip("\n")


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the converter node.

    A technology-neutral data converter. The first supported conversions are
    ``csvToJson`` (CSV text -> list of row objects) and ``jsonToCsv`` (a list of
    objects/rows -> CSV text). The ``conversion`` field leaves room for more
    formats later without changing the node's contract.
    """
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    conversion = node_data.get("conversion", "csvToJson")
    delimiter = _resolve_delimiter(node_data.get("delimiter"))
    source_template = node_data.get("source", "")

    if isinstance(source_template, str) and source_template.strip():
        source_value = self.resolve_expression(
            source_template.strip(), inputs, node_id, preserve_type=True
        )
    else:
        source_value = self._first_visible_input(inputs)

    if conversion == "jsonToCsv":
        include_header = node_data.get("includeHeader", True)
        columns = _normalize_columns(node_data.get("converterColumns"))
        result: object = _json_to_csv(source_value, delimiter, include_header, columns)
    else:
        has_header = node_data.get("hasHeader", True)
        trim_values = node_data.get("trimValues", True)
        result = _csv_to_json(source_value, delimiter, has_header, trim_values)

    return {"result": result, "conversion": conversion}
