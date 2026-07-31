from __future__ import annotations

import csv
import io
import json

from app.services.node_execution.base import NodeExecutionContext


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


def _csv_to_json(text: object, delimiter: str, has_header: bool) -> list:
    """Parse CSV text into a list of row dicts (with header) or row lists."""
    if not isinstance(text, str):
        text = str(text)
    if text.strip() == "":
        return []
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return []
    if not has_header:
        return rows
    header = rows[0]
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
    delimiter = str(node_data.get("delimiter") or ",")[:1] or ","
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
        result = _csv_to_json(source_value, delimiter, has_header)

    return {"result": result, "conversion": conversion}
