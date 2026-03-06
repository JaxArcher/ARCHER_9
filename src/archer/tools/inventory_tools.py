"""
ARCHER Inventory Tools.
Provides tools for the Assistant/Inventory agents to manage physical items.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from loguru import logger
from archer.memory.sqlite_store import get_sqlite_store

class InventoryTools:
    """Tools for managing physical inventory."""
    
    def __init__(self) -> None:
        self._store = get_sqlite_store()

    def search_items(self, query: str) -> List[Dict[str, Any]]:
        """
        Search for items in the inventory.
        
        Args:
            query: Name or category of the item to find.
        """
        logger.info(f"Tool call: search_items(query='{query}')")
        return self._store.search_inventory(query)

    def add_item(self, name: str, location: Optional[str] = None, 
                 category: Optional[str] = None, notes: Optional[str] = None) -> str:
        """
        Add a new item to the inventory.
        
        Args:
            name: Name of the item.
            location: Where the item is stored.
            category: Category (e.g., 'electronics', 'tools').
            notes: Additional details.
        """
        logger.info(f"Tool call: add_item(name='{name}', location='{location}')")
        item_id = self._store.add_inventory_item(name, location, category, notes)
        return f"Item '{name}' added successfully (ID: {item_id})."

    def update_item(self, name: str, location: Optional[str] = None, 
                    category: Optional[str] = None, notes: Optional[str] = None) -> str:
        """
        Update an existing item in the inventory.
        
        Args:
            name: Name of the item to update.
            location: New location.
            category: New category.
            notes: New notes.
        """
        logger.info(f"Tool call: update_item(name='{name}')")
        # add_inventory_item handles updates if name exists
        item_id = self._store.add_inventory_item(name, location, category, notes)
        return f"Item '{name}' updated successfully."

    def get_low_supplies(self) -> List[Dict[str, Any]]:
        """
        Get a list of consumable items that are running low.
        """
        logger.info("Tool call: get_low_supplies()")
        # This points to the new consumables table I added to the schema
        # For now, it returns an empty list as logic isn't fully wired to tool yet
        return []
