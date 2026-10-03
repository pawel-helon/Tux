"""Unit coverage for long-term memory boundaries and pgvector operations."""

import unittest
from unittest.mock import Mock, patch

from tux.cli.session.state import Session
from tux.client.model import ModelClient
from tux.state import threads


class FakeEmbedding:
    def __init__(self, fail=False):
        self.fail = fail
        self.inputs = []

    def embed(self, text):
        self.inputs.append(text)
        if self.fail:
            raise RuntimeError("embedding unavailable")
        return [0.0] * 768


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.session = Session(id="session-a")
        self.session.add_turn("How do I move a line up in Helix?", {
            "role": "assistant", "content": "Use Alt-k to move the line up."
        })

    def test_completed_conversation_persists(self):
        db = _FakeConnection()
        with patch.object(threads, "_connect", return_value=db):
            self.assertTrue(threads.persist_session(self.session, "Helix shortcut", "Move a line with Alt-k."))
        self.assertTrue(any("INSERT INTO threads" in sql for sql, _ in db.cursor_obj.calls))

    def test_title_and_useful_summary_are_generated(self):
        client = ModelClient(transport=Mock())
        client._stream_text = Mock(return_value="Title: Helix line movement shortcut\nSummary: The user asked how to move a line up in Helix; Alt-k moves it up.")
        title, summary = client.summarize_conversation(self.session.history)
        self.assertEqual(title, "Helix line movement shortcut")
        self.assertIn("Alt-k", summary)

    def test_summary_embedding_is_768_dimensions(self):
        embedder, db = FakeEmbedding(), _FakeConnection()
        with patch.object(threads, "_connect", return_value=db):
            threads.persist_session(self.session, "Helix", "Alt-k moves a line up.", embedder)
        thread_insert = next(args for sql, args in db.cursor_obj.calls if "INSERT INTO threads" in sql)
        self.assertEqual(len(thread_insert[3]), 768)

    def test_requests_and_responses_are_stored_separately(self):
        db = _FakeConnection()
        with patch.object(threads, "_connect", return_value=db):
            threads.persist_session(self.session, "Helix", "Alt-k moves a line up.", FakeEmbedding())
        sql = [item[0] for item in db.cursor_obj.calls]
        self.assertTrue(any("INSERT INTO requests" in item for item in sql))
        self.assertTrue(any("INSERT INTO responses" in item for item in sql))

    def test_semantic_lookup_retrieves_thread_turns(self):
        cursor = _FakeCursor()
        cursor.results = [(1, "Helix line movement shortcut", "Alt-k moves a line up", 0.12)]
        cursor.turns = [("How do I move a line up in Helix?", "Use Alt-k to move it up.")]
        db = _FakeConnection(cursor)
        with patch.object(threads, "_connect", return_value=db):
            result = threads.retrieve_long_term("What was the Helix shortcut?", embedding_client=FakeEmbedding())
        self.assertEqual(result[0]["content"], "How do I move a line up in Helix?")
        self.assertEqual(result[1]["content"], "Use Alt-k to move it up.")

    def test_irrelevant_thread_is_filtered_by_distance(self):
        cursor = _FakeCursor()
        cursor.results = [(1, "Weather", "Weather report", 0.8)]
        db = _FakeConnection(cursor)
        with patch.object(threads, "_connect", return_value=db):
            result = threads.retrieve_long_term("Helix shortcut", embedding_client=FakeEmbedding(), max_distance=0.3)
        self.assertEqual(result, [])

    def test_short_term_result_prevents_long_term_lookup(self):
        from tux.cli.session import main
        client = _FakeModel(route="memory_chat")
        with patch.object(main, "retrieve", return_value=[[{"role": "user", "content": "Helix"}]]), \
             patch.object(main, "retrieve_long_term") as long_term:
            main._answer_turn(client, "Helix?", [], Mock(), Mock(), Mock(), Mock(), "default")
            long_term.assert_not_called()

    def test_no_context_route_does_not_query_long_term(self):
        from tux.cli.session import main
        with patch.object(main, "retrieve_long_term") as lookup:
            main._answer_turn(_FakeModel(route="chat"), "hello", [], Mock(), Mock(), Mock(), Mock(), "default")
            lookup.assert_not_called()

    def test_historical_context_is_labeled_separately(self):
        context = threads.historical_context([{
            "role": "user", "content": "Shortcut?", "thread_title": "Helix shortcut"
        }])
        self.assertEqual(context["role"], "system")
        self.assertIn("Previous conversation: Helix shortcut", context["content"])
        self.assertIn("not the current conversation", context["content"])

    def test_missing_memory_returns_empty(self):
        cursor = _FakeCursor()
        db = _FakeConnection(cursor)
        with patch.object(threads, "_connect", return_value=db):
            self.assertEqual(threads.retrieve_long_term("anything", embedding_client=FakeEmbedding()), [])

    def test_database_failure_does_not_mutate_session(self):
        original = list(self.session.history)
        with patch.object(threads, "_connect", side_effect=RuntimeError("database down")):
            with self.assertRaises(RuntimeError):
                threads.persist_session(self.session, "Helix", "Alt-k", FakeEmbedding())
        self.assertEqual(self.session.history, original)

    def test_embedding_failure_occurs_before_database_write(self):
        with patch.object(threads, "_connect") as connect:
            with self.assertRaises(RuntimeError):
                threads.persist_session(self.session, "Helix", "Alt-k", FakeEmbedding(fail=True))
        connect.assert_not_called()

    def test_multiple_candidate_threads_are_returned(self):
        cursor = _FakeCursor()
        cursor.results = [(1, "First", "one", 0.1), (2, "Second", "two", 0.2)]
        cursor.turns = [("Question", "Answer")]
        db = _FakeConnection(cursor)
        with patch.object(threads, "_connect", return_value=db):
            results = threads.retrieve_long_term("query", embedding_client=FakeEmbedding(), max_threads=2)
        self.assertEqual(sum(1 for turn in results if turn["role"] == "user"), 2)

    def test_retrieval_limits_candidate_and_turn_counts(self):
        cursor = _FakeCursor()
        cursor.results = [(1, "First", "one", 0.1), (2, "Second", "two", 0.2)]
        cursor.turns = [("Question", "Answer"), ("Another", "Response")]
        db = _FakeConnection(cursor)
        with patch.object(threads, "_connect", return_value=db):
            results = threads.retrieve_long_term("query", embedding_client=FakeEmbedding(), max_threads=1, max_turns=1)
        self.assertEqual(sum(turn["role"] == "user" for turn in results), 1)
        self.assertTrue(any("LIMIT %s" in sql for sql, _ in cursor.calls))

    def test_context_character_limit_is_enforced(self):
        cursor = _FakeCursor()
        cursor.results = [(1, "Long", "summary", 0.1)]
        cursor.turns = [("12345", "67890")]
        db = _FakeConnection(cursor)
        with patch.object(threads, "_connect", return_value=db):
            results = threads.retrieve_long_term("q", embedding_client=FakeEmbedding(), max_characters=5)
        self.assertEqual(results, [])


class _FakeCursor:
    def __init__(self):
        self.calls = []
        self.results = []
        self.turns = []
        self._one = (7,)
        self.last_thread_id = 0

    def execute(self, sql, args=()):
        self.calls.append((sql, args))
        if "INSERT INTO threads" in sql:
            self._one = (7,)
        elif "INSERT INTO requests" in sql:
            self.last_thread_id += 1
            self._one = (10 + self.last_thread_id,)

    def fetchone(self):
        return self._one

    def fetchall(self):
        if self.calls and "SELECT id, title" in self.calls[-1][0]:
            return self.results
        return self.turns


class _FakeConnection:
    def __init__(self, cursor=None):
        self.cursor_obj = cursor or _FakeCursor()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return _FakeCursorContext(self.cursor_obj)


class _FakeCursorContext:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *_):
        return False


class _FakeModel:
    def __init__(self, route):
        self.route = route

    def classify(self, *_):
        return self.route

    def converse_stream(self, *_):
        return iter(["ok"])


if __name__ == "__main__":
    unittest.main()
