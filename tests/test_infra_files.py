import json

from ialauncher.infra.files import compact_json, tail


def test_compact_json_round_trips_and_keeps_lines_short():
    data = {"engine": {"label": "x", "command": [f"--arg-{i}" for i in range(40)],
                       "params": {"ctx": {"label": "Context", "default": "0"}}}}
    text = compact_json(data)
    assert json.loads(text) == data
    assert max(len(line) for line in text.splitlines()) <= 110
    assert '"ctx": {"label": "Context", "default": "0"}' in text  # small objects stay on one line


def test_tail_strips_terminal_codes(tmp_path):
    log = tmp_path / "x.log"
    log.write_text("one\n\x1b[32mtwo\x1b[0m\r\nthree\n")
    assert tail(log, 2) == "two\nthree"
    assert tail(tmp_path / "missing.log") == ""
