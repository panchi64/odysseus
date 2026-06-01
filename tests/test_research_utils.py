"""Tests for research_utils.py — thinking block stripping and quality filtering."""

from src.research_utils import strip_thinking, is_low_quality


class TestStripThinking:
    def test_removes_think_tags(self):
        text = "<think>some internal reasoning</think>Final answer."
        assert strip_thinking(text) == "Final answer."

    def test_removes_thinking_tags(self):
        text = "<thinking>some internal reasoning</thinking>Final answer."
        assert strip_thinking(text) == "Final answer."

    def test_removes_nested_tags(self):
        text = "<think>outer <think>inner</think> still outer</think>Result."
        result = strip_thinking(text)
        assert "<think>" not in result
        assert "Result." in result

    def test_handles_orphaned_opening_tag(self):
        text = "<think>unclosed reasoning block\nFinal answer."
        result = strip_thinking(text)
        assert "<think>" not in result

    def test_handles_orphaned_closing_tag(self):
        text = "Some text</think> and more."
        result = strip_thinking(text)
        assert "</think>" not in result
        assert "Some text" in result

    def test_empty_string(self):
        assert strip_thinking("") == ""

    def test_none_input(self):
        assert strip_thinking(None) is None

    def test_no_thinking_tags(self):
        text = "Just a normal response with no tags."
        assert strip_thinking(text) == text

    def test_preserves_content_after_thinking(self):
        text = "<think>planning step</think>\n\n# Report\n\nHere is the report."
        result = strip_thinking(text)
        assert "# Report" in result
        assert "Here is the report." in result

    def test_strips_qwen_thinking_process(self):
        text = "Thinking Process: Let me analyze this carefully.\n\n# Answer\n\nThe answer is 42."
        result = strip_thinking(text)
        assert "Thinking Process" not in result
        assert "The answer is 42." in result


class TestIsLowQuality:
    def test_empty_string(self):
        assert is_low_quality("") is True

    def test_none_input(self):
        assert is_low_quality(None) is True

    def test_normal_summary(self):
        assert is_low_quality("Python 3.12 introduces several new features.") is False

    def test_insufficient_marker(self):
        assert is_low_quality("The content is insufficient to answer.") is True

    def test_no_relevant_info(self):
        assert is_low_quality("No relevant information found in the source.") is True

    def test_boilerplate(self):
        assert is_low_quality("This page contains only boilerplate text.") is True

    def test_unable_to_extract(self):
        assert is_low_quality("Unable to extract meaningful data.") is True

    def test_case_insensitive(self):
        assert is_low_quality("UNABLE TO EXTRACT any data") is True

    def test_does_not_contain_relevant_marker(self):
        assert is_low_quality("This page does not contain relevant information.") is True

    def test_not_relevant_to_goal_marker(self):
        assert is_low_quality("The text is not relevant to the goal of the query.") is True

    # Regression: bare topic words ("cookie", "copyright", "footer") must NOT
    # trip the filter. They previously discarded legitimate findings whenever the
    # subject matter happened to mention them (e.g. cookie law, copyright reform).
    def test_cookie_topic_not_filtered(self):
        assert is_low_quality(
            "The EU cookie law requires consent banners for tracking cookies."
        ) is False

    def test_copyright_topic_not_filtered(self):
        assert is_low_quality(
            "The 2024 copyright reform extended protection terms to 70 years."
        ) is False

    def test_footer_topic_not_filtered(self):
        assert is_low_quality(
            "Site footer links improved navigation and reduced bounce rate."
        ) is False
