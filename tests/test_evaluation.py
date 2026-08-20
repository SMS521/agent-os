from agentos.evaluation import parse_verdict


def test_parses_verdict_heading_pass():
    assert parse_verdict("## Verdict\nPASS\n\n## Findings\n- none") is True


def test_parses_verdict_heading_fail():
    assert parse_verdict("## Verdict\nFAIL\n\nsomething is wrong") is False


def test_parses_bare_pass_line_fallback():
    assert parse_verdict("looks fine overall\nPASS\n") is True


def test_unparseable_output_is_a_fail_not_a_pass():
    assert parse_verdict("I think this is probably okay") is False


def test_empty_output_is_a_fail():
    assert parse_verdict(None) is False
    assert parse_verdict("") is False


def test_case_insensitive_verdict_heading():
    assert parse_verdict("## verdict\npass") is True
