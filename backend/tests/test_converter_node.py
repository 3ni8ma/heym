import unittest
from types import SimpleNamespace

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import converter_node


def _ctx(node_data: dict, source_value: object) -> NodeExecutionContext:
    # The handler resolves `source` via the executor; the stub returns the
    # provided value regardless of the template, and also serves as the
    # first-visible-input fallback when `source` is empty.
    executor = SimpleNamespace(
        resolve_expression=lambda _expr, *_a, **_k: source_value,
        _first_visible_input=lambda _inputs: source_value,
    )
    return NodeExecutionContext(
        executor=executor,
        node_id="conv_1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node={"id": "conv_1"},
        node_type="converter",
        node_data=node_data,
        node_label="conv1",
    )


class CsvToJsonTests(unittest.TestCase):
    def test_header_rows_become_dicts(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "csvToJson", "source": "$in"}, "name,age\nAda,36\nGrace,45")
        )

        self.assertEqual(output["conversion"], "csvToJson")
        self.assertEqual(
            output["result"],
            [{"name": "Ada", "age": "36"}, {"name": "Grace", "age": "45"}],
        )

    def test_without_header_returns_lists(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "csvToJson", "hasHeader": False}, "Ada,36\nGrace,45")
        )

        self.assertEqual(output["result"], [["Ada", "36"], ["Grace", "45"]])

    def test_quoted_field_with_delimiter(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "csvToJson"}, 'name,note\n"Smith, Jr.",hi')
        )

        self.assertEqual(output["result"], [{"name": "Smith, Jr.", "note": "hi"}])

    def test_quoted_field_with_embedded_newline(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "csvToJson"}, 'name,note\nAda,"line1\nline2"')
        )

        self.assertEqual(output["result"], [{"name": "Ada", "note": "line1\nline2"}])

    def test_custom_delimiter(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "csvToJson", "delimiter": ";"}, "name;age\nAda;36")
        )

        self.assertEqual(output["result"], [{"name": "Ada", "age": "36"}])

    def test_ragged_row_fills_missing_with_empty_string(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "csvToJson"}, "name,age\nAda"))

        self.assertEqual(output["result"], [{"name": "Ada", "age": ""}])

    def test_empty_input_returns_empty_list(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "csvToJson"}, ""))

        self.assertEqual(output["result"], [])

    def test_csv_to_json_is_the_default_conversion(self) -> None:
        output = converter_node.execute(_ctx({}, "name\nAda"))

        self.assertEqual(output["conversion"], "csvToJson")
        self.assertEqual(output["result"], [{"name": "Ada"}])

    def test_leading_utf8_bom_is_stripped(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "csvToJson"}, "\ufeffname,age\nAda,36"))

        # The first key is "name", not the BOM-prefixed variant.
        self.assertEqual(output["result"], [{"name": "Ada", "age": "36"}])

    def test_duplicate_headers_are_made_unique(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "csvToJson"}, "a,a\n1,2"))

        self.assertEqual(output["result"], [{"a": "1", "a_2": "2"}])

    def test_dedupe_does_not_collide_with_existing_column(self) -> None:
        # The generated suffix must skip a real "a_2" column so no value is lost.
        output = converter_node.execute(_ctx({"conversion": "csvToJson"}, "a,a,a_2\n1,2,3"))

        self.assertEqual(output["result"], [{"a": "1", "a_3": "2", "a_2": "3"}])

    def test_tab_delimiter_via_escape(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "csvToJson", "delimiter": "\\t"}, "name\tage\nAda\t36")
        )

        self.assertEqual(output["result"], [{"name": "Ada", "age": "36"}])

    def test_trim_values_default_strips_whitespace(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "csvToJson"}, "name, age\nAda , 36"))

        # Header keys and cell values are trimmed by default.
        self.assertEqual(output["result"], [{"name": "Ada", "age": "36"}])

    def test_trim_values_false_keeps_whitespace(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "csvToJson", "trimValues": False}, "name, age\nAda , 36")
        )

        self.assertEqual(output["result"], [{"name": "Ada ", " age": " 36"}])


class JsonToCsvTests(unittest.TestCase):
    def test_dicts_become_csv_with_header(self) -> None:
        output = converter_node.execute(
            _ctx(
                {"conversion": "jsonToCsv"},
                [{"name": "Ada", "age": 36}, {"name": "Grace", "age": 45}],
            )
        )

        self.assertEqual(output["result"], "name,age\nAda,36\nGrace,45")

    def test_include_header_false_omits_header(self) -> None:
        output = converter_node.execute(
            _ctx(
                {"conversion": "jsonToCsv", "includeHeader": False},
                [{"name": "Ada", "age": 36}],
            )
        )

        self.assertEqual(output["result"], "Ada,36")

    def test_explicit_column_order(self) -> None:
        output = converter_node.execute(
            _ctx(
                {"conversion": "jsonToCsv", "converterColumns": "age, name"},
                [{"name": "Ada", "age": 36}],
            )
        )

        self.assertEqual(output["result"], "age,name\n36,Ada")

    def test_values_needing_quotes_are_escaped(self) -> None:
        output = converter_node.execute(
            _ctx(
                {"conversion": "jsonToCsv"},
                [{"note": 'He said "hi", loudly'}],
            )
        )

        self.assertEqual(output["result"], 'note\n"He said ""hi"", loudly"')

    def test_list_of_lists(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "jsonToCsv"}, [["a", "b"], ["c", "d"]]))

        self.assertEqual(output["result"], "a,b\nc,d")

    def test_json_string_input_is_parsed(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "jsonToCsv"}, '[{"name": "Ada"}]'))

        self.assertEqual(output["result"], "name\nAda")

    def test_single_dict_becomes_one_row(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "jsonToCsv"}, {"name": "Ada", "age": 36})
        )

        self.assertEqual(output["result"], "name,age\nAda,36")

    def test_empty_list_returns_empty_string(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "jsonToCsv"}, []))

        self.assertEqual(output["result"], "")


class ConverterRoundTripTests(unittest.TestCase):
    def test_build_then_parse_round_trip(self) -> None:
        rows = [{"name": "Ada", "age": "36"}, {"name": "Grace", "age": "45"}]

        csv_out = converter_node.execute(_ctx({"conversion": "jsonToCsv"}, rows))
        parsed = converter_node.execute(_ctx({"conversion": "csvToJson"}, csv_out["result"]))

        self.assertEqual(parsed["result"], rows)


if __name__ == "__main__":
    unittest.main()
