# Converter

The **Converter** node converts data between formats without writing code. It is technology-neutral so more formats can be added over time; the first supported conversions are CSV text and JSON rows in both directions.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.result` (parsed rows for `csvToJson`, CSV text for `jsonToCsv`) |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `conversion` | string | `csvToJson` (CSV text → array of row objects) or `jsonToCsv` (array of objects/rows → CSV text) |
| `source` | expression | The data to convert. Leave empty to use the node's first input |
| `delimiter` | string | Single-character field separator (default `,`) |
| `hasHeader` | boolean | `csvToJson` only — treat the first row as the header (default `true`) |
| `trimValues` | boolean | `csvToJson` only — strip whitespace around header names and cell values (default `true`) |
| `includeHeader` | boolean | `jsonToCsv` only — write a header row (default `true`) |
| `converterColumns` | string | `jsonToCsv` only — optional comma-separated column order |

## Behavior

- **`csvToJson`** parses the source CSV text. With `hasHeader: true` each row becomes an object keyed by the header values; with `hasHeader: false` each row becomes an array of cell values. Quoted fields, embedded delimiters, and embedded newlines are handled per RFC 4180. A leading UTF-8 BOM (common in Excel exports) is stripped, and duplicate header names are made unique (`a, a` → `a`, `a_2`). Set `delimiter` to `\t` to parse tab-separated values.
- **`jsonToCsv`** builds CSV text from an array of objects (or arrays). Column order is taken from `converterColumns` when provided, otherwise inferred from the first object's keys. Values containing the delimiter, quotes, or newlines are quoted automatically.

## Example

```json
{
  "type": "converter",
  "data": {
    "label": "toRows",
    "conversion": "csvToJson",
    "source": "$userInput.body.text",
    "delimiter": ",",
    "hasHeader": true
  }
}
```

For input `name,age\nAda,36`, downstream nodes access the parsed rows via `$toRows.result` (`[{ "name": "Ada", "age": "36" }]`).

## Related

- [Set](./set-node.md) – Transform and map individual fields
- [JSON output mapper](./json-output-mapper-node.md) – Build a JSON response object
- [Node Types](../reference/node-types.md) – Overview of all node types
- [Expression DSL](../reference/expression-dsl.md) – Functions and syntax
