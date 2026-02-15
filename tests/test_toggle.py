"""
Tests for the ARCHER Toggle Service.
"""

import os
import tempfile
import pytest

from archer.config import get_config


class TestToggleService:
    """Tests for the cloud/local toggle service."""

    def setup_method(self):
        """Create a fresh toggle service with a temp DB for each test."""
        # Use a temp file for the test DB
        self._temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._temp_db.close()

        # Patch the config to use the temp DB
        config = get_config()
        self._original_db_path = config.sqlite_db_path
        config.sqlite_db_path = self._temp_db.name

        # Reset singleton
        import archer.core.toggle as toggle_module
        toggle_module._toggle_service = None

    def teardown_method(self):
        """Clean up temp DB."""
        config = get_config()
        config.sqlite_db_path = self._original_db_path

        try:
            os.unlink(self._temp_db.name)
        except Exception:
            pass

        import archer.core.toggle as toggle_module
        toggle_module._toggle_service = None

    def test_default_mode(self):
        """Test that the default mode is cloud."""
        from archer.core.toggle import ToggleService
        toggle = ToggleService()
        assert toggle.mode == "cloud"

    def test_set_mode(self):
        """Test setting the mode."""
        from archer.core.toggle import ToggleService
        toggle = ToggleService()
        toggle.mode = "local"
        assert toggle.mode == "local"
        assert toggle.is_local is True
        assert toggle.is_cloud is False

    def test_toggle(self):
        """Test toggling between modes."""
        from archer.core.toggle import ToggleService
        toggle = ToggleService()
        assert toggle.mode == "cloud"

        new_mode = toggle.toggle()
        assert new_mode == "local"
        assert toggle.mode == "local"

        new_mode = toggle.toggle()
        assert new_mode == "cloud"
        assert toggle.mode == "cloud"

    def test_mode_persists(self):
        """Test that mode persists in SQLite across instances."""
        from archer.core.toggle import ToggleService
        toggle1 = ToggleService()
        toggle1.mode = "local"

        # Create a new instance — should read from DB
        toggle2 = ToggleService()
        assert toggle2.mode == "local"

    def test_invalid_mode_raises(self):
        """Test that invalid mode raises ValueError."""
        from archer.core.toggle import ToggleService
        toggle = ToggleService()
        with pytest.raises(ValueError):
            toggle.mode = "invalid"
