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


def _exported_methods() -> set[str]:
    src = (WEB_JS / "app.js").read_text(encoding="utf-8")
    block = re.search(r"return\s*\{([\s\S]*?)\n\s*\};\s*\}\)\(\);", src)
    assert block, "Could not find return object of ArcherClient IIFE in app.js"
    return set(re.findall(r"^\s*(?:get\s+)?(\w+)\s*[:\(,]", block.group(1), re.M))


def test_archer_client_exposes_public_send():
    """
    Claude 2026-10-21 15:30: android.js and other modules call window.ArcherClient.send(msg).
    ArcherClient must expose a generic `send` method so client messages reach the server.
    """
    exported = _exported_methods()
    assert "send" in exported, "ArcherClient does not expose a public send(obj) method"


def test_every_method_called_on_archer_client_is_exported():
    """
    Verify that any method invoked on ArcherClient or window.ArcherClient in web/js/*.js
    actually exists in ArcherClient's exported return object.
    """
    exported = _exported_methods()
    missing = {}
    for js in sorted(WEB_JS.glob("*.js")):
        content = js.read_text(encoding="utf-8")
        for method in re.findall(r"(?:window\.)?ArcherClient\.(\w+)\s*\(", content):
            if method not in exported:
                missing.setdefault(method, []).append(js.name)
    assert not missing, f"Methods called on ArcherClient but not exported in app.js: {missing}"

