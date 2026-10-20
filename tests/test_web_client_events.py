"""
The browser page's scripts register handlers with ArcherClient.on(name),
which throws for any name missing from app.js's `listeners` list. One
missing name (artifactPush) stopped ui.js part-way through on every page
load, so the toolbar buttons, the text box and the Room Listening panel
never worked (Claude, 2026-10-20). Every name used must be in the list.
"""

import re
from pathlib import Path

WEB_JS = Path(__file__).resolve().parents[1] / "web" / "js"


def _listener_names() -> set[str]:
    src = (WEB_JS / "app.js").read_text(encoding="utf-8")
    block = re.search(r"const listeners = \{(.*?)\n\s*\};", src, re.S)
    assert block, "app.js no longer has a `const listeners = { ... };` list"
    return set(re.findall(r"^\s*(\w+)\s*:\s*\[\]", block.group(1), re.M))


def test_every_handler_name_is_in_the_listener_list():
    names = _listener_names()
    missing = {}
    for js in sorted(WEB_JS.glob("*.js")):
        for name in re.findall(r"ArcherClient\.on\(\s*[\"'](\w+)[\"']", js.read_text(encoding="utf-8")):
            if name not in names:
                missing.setdefault(name, []).append(js.name)
    assert not missing, f"ArcherClient.on() names missing from app.js listeners: {missing}"


def test_every_emitted_name_is_in_the_listener_list():
    names = _listener_names()
    src = (WEB_JS / "app.js").read_text(encoding="utf-8")
    emitted = set(re.findall(r"emit\(\s*[\"'](\w+)[\"']", src))
    assert emitted <= names, f"emitted but not listed: {sorted(emitted - names)}"
