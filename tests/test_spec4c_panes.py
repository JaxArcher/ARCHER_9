"""
Unit tests for Spec 4c: Resizable and Movable Panes (GridStack integration).
"""

from pathlib import Path
import pytest


def test_gridstack_vendor_files_exist():
    """Verify GridStack assets are present in web/vendor/gridstack/."""
    vendor_dir = Path("web/vendor/gridstack")
    assert (vendor_dir / "gridstack-all.js").exists(), "gridstack-all.js must exist"
    assert (vendor_dir / "gridstack.min.css").exists(), "gridstack.min.css must exist"
    assert (vendor_dir / "gridstack-all.js").stat().st_size > 50000
    assert (vendor_dir / "gridstack.min.css").stat().st_size > 1000


def test_panes_js_logic_and_persistence():
    """Verify web/js/panes.js has layout persistence, defaults, and event handlers."""
    panes_js = Path("web/js/panes.js")
    assert panes_js.exists(), "web/js/panes.js must exist"
    content = panes_js.read_text(encoding="utf-8")

    assert "GridStack.init" in content
    assert "archer.layout.v1" in content
    assert "DEFAULT_LAYOUT" in content
    assert "pane-chat" in content
    assert "pane-orb" in content
    assert "pane-camera" in content
    assert "pane-listening" in content
    assert "pane-workspace" in content
    assert "resetLayout" in content
    assert "archer-reset-layout-btn" in content
    assert "grid-stack-dragging" in content


def test_index_html_pane_structure():
    """Verify web/index.html defines all 5 GridStack panes and script/style links."""
    index_html = Path("web/index.html").read_text(encoding="utf-8")

    # Vendor and script tags
    assert "/static/vendor/gridstack/gridstack.min.css" in index_html
    assert "/static/vendor/gridstack/gridstack-all.js" in index_html
    assert "/static/js/panes.js" in index_html

    # Toolbar button
    assert 'id="archer-reset-layout-btn"' in index_html

    # Container and 5 panes
    assert 'id="archer-main-layout" class="grid-stack"' in index_html
    assert 'id="pane-chat"' in index_html
    assert 'id="pane-orb"' in index_html
    assert 'id="pane-camera"' in index_html
    assert 'id="pane-listening"' in index_html
    assert 'id="pane-workspace"' in index_html

    # Critical child components preserved
    assert 'id="archer-system-camera-feed"' in index_html
    assert 'id="archer-transcript"' in index_html
    assert 'id="archer-tabs"' in index_html
    assert 'id="archer-tab-content"' in index_html


def test_ui_css_pane_and_drag_shielding():
    """Verify web/css/ui.css styles panes, drag handles, and shields iframes."""
    ui_css = Path("web/css/ui.css").read_text(encoding="utf-8")

    assert ".archer-pane" in ui_css
    assert ".archer-pane-header" in ui_css
    assert ".archer-pane-grip" in ui_css
    assert ".archer-pane-body" in ui_css
    assert "#archer-reset-layout-btn" in ui_css
    assert "body.grid-stack-dragging iframe" in ui_css


def test_spec_section_12_records_gridstack():
    """Verify Section 12 of redesign spec documents GridStack 14.0.0."""
    spec_md = Path("ARCHER_Workspace_Redesign_Spec_06OCT2026.md").read_text(encoding="utf-8")
    assert "gridstack" in spec_md
    assert "14.0.0" in spec_md
    assert "web/vendor/gridstack/" in spec_md
