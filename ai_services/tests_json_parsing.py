"""Tests for the JSON-list parsing used by keywords and tags.

Model output is not trusted to be well-formed JSON: free-tier models fence
it, emit a bare array, or get cut off by the token limit. These tests pin the
recovery behaviour, and in particular that a malformed document yields
nothing rather than fragments.
"""

from django.test import SimpleTestCase

from ai_services.services.voice_text import (
    _clean_term,
    _looks_like_term,
    _parse_string_list,
    _repair_truncated_json,
)


class TestCleanTerm(SimpleTestCase):
    def test_strips_quotes_and_json_punctuation(self):
        self.assertEqual(_clean_term('  "handwoven",  '), 'handwoven')

    def test_strips_a_json_key_prefix(self):
        self.assertEqual(_clean_term('"cotton":'), 'cotton')

    def test_lowercases(self):
        self.assertEqual(_clean_term('COTTON Runner'), 'cotton runner')

    def test_handles_none(self):
        self.assertEqual(_clean_term(None), '')

    def test_numbers_become_strings(self):
        self.assertEqual(_clean_term(42), '42')


class TestLooksLikeTerm(SimpleTestCase):
    def test_rejects_punctuation_only(self):
        self.assertFalse(_looks_like_term('":'))
        self.assertFalse(_looks_like_term(''))

    def test_rejects_overlong_fragments(self):
        self.assertFalse(_looks_like_term('x' * 80))

    def test_accepts_a_real_phrase(self):
        self.assertTrue(_looks_like_term('cotton table runner'))


class TestRepairTruncatedJson(SimpleTestCase):
    def test_closes_an_open_string_and_array(self):
        self.assertEqual(
            _repair_truncated_json('{"keywords": ["a", "b'),
            '{"keywords": ["a", "b"]}')

    def test_closes_an_open_object(self):
        self.assertEqual(_repair_truncated_json('{"keywords": ['),
                         '{"keywords": []}')

    def test_drops_a_dangling_comma(self):
        self.assertEqual(_repair_truncated_json('{"keywords": ["a",'),
                         '{"keywords": ["a"]}')

    def test_complete_json_is_left_alone(self):
        self.assertEqual(_repair_truncated_json('{"a": 1}'), '')

    def test_unbalanced_closer_is_rejected(self):
        """Repairing past a mismatch would invent content."""
        self.assertEqual(_repair_truncated_json('{"a": [1, 2}'), '')

    def test_braces_inside_strings_are_ignored(self):
        self.assertEqual(
            _repair_truncated_json('{"keywords": ["a{b", "c'),
            '{"keywords": ["a{b", "c"]}')

    def test_escaped_quote_does_not_end_the_string(self):
        self.assertEqual(
            _repair_truncated_json('{"keywords": ["say \\"hi', ),
            '{"keywords": ["say \\"hi"]}')

    def test_non_json_is_not_repaired(self):
        self.assertEqual(_repair_truncated_json('just prose'), '')


class TestParseStringList(SimpleTestCase):
    def test_well_formed_object(self):
        self.assertEqual(
            _parse_string_list('{"keywords": ["a", "b"]}', 'keywords'),
            ['a', 'b'])

    def test_fenced_json(self):
        self.assertEqual(
            _parse_string_list('```json\n{"keywords": ["a", "b"]}\n```', 'keywords'),
            ['a', 'b'])

    def test_bare_array(self):
        self.assertEqual(_parse_string_list('["a", "b"]', 'keywords'),
                         ['a', 'b'])

    def test_reads_the_named_key(self):
        self.assertEqual(_parse_string_list('{"tags": ["x"]}', 'tags'), ['x'])

    def test_recovers_a_truncated_document(self):
        self.assertEqual(
            _parse_string_list(
                '{"keywords": ["cotton runner", "table runner", "handmade run',
                'keywords'),
            ['cotton runner', 'table runner', 'handmade run'])

    def test_never_returns_json_fragments(self):
        """A half-written document must not leak 'a":[1' style junk."""
        self.assertEqual(_parse_string_list('{"a": [1, 2}', 'keywords'), [])

    def test_prose_fallback(self):
        self.assertEqual(
            _parse_string_list('cotton runner, table runner', 'keywords'),
            ['cotton runner', 'table runner'])

    def test_empty_input(self):
        self.assertEqual(_parse_string_list('', 'keywords'), [])
        self.assertEqual(_parse_string_list(None, 'keywords'), [])

    def test_respects_the_limit(self):
        raw = '{"keywords": [' + ','.join('"k%d"' % i for i in range(30)) + ']}'
        self.assertEqual(len(_parse_string_list(raw, 'keywords', limit=12)), 12)

    def test_drops_empty_entries(self):
        self.assertEqual(
            _parse_string_list('{"keywords": ["a", "", "  ", "b"]}', 'keywords'),
            ['a', 'b'])

    def test_ignores_a_wrongly_named_key(self):
        """A dict without the expected key is not silently mislabelled."""
        self.assertEqual(_parse_string_list('{"other": ["a"]}', 'keywords'), [])
