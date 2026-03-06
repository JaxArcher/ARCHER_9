"""
ARCHER Inventory Manager Agent implementation.
Focuses on physical asset tracking, supplies, and locations.
"""

from __future__ import annotations
import json
import enum
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from loguru import logger

from archer.config import get_config
from archer.core.event_bus import Event, EventType, get_event_bus
from archer.memory.sqlite_store import get_sqlite_store


# Import core inventory components
from archer.inventory.object_detector import InventoryObjectDetector
from archer.inventory.item_registry import ItemRegistry
from archer.inventory.supply_monitor import SupplyMonitor
from archer.inventory.purchase_tracker import PurchaseTracker

class InventoryAgent:
    """
    The Inventory Manager tracks all physical belongings.
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._bus = get_event_bus()
        self._store = get_sqlite_store()
        
        # Initialize components
        self.detector = InventoryObjectDetector(self._store)
        self.registry = ItemRegistry(self._store)
        self.supply_monitor = SupplyMonitor(self._store)
        self.purchase_tracker = PurchaseTracker(self._store)
        
        self._subscribe_events()
        logger.info("Inventory Manager Agent initialized.")

    def _subscribe_events(self) -> None:
        """Subscribe to relevant event bus channels."""
        self._bus.subscribe(EventType.OBSERVATION_EVENT, self._on_observation)
        self._bus.subscribe(EventType.STT_FINAL, self._on_utterance)

    def _on_observation(self, event: Event) -> None:
        """Handle vision detections for object tracking."""
        payload = event.data.get("payload", {})
        source = event.data.get("source", "unknown")
        
        if source == "webcam":
            # 1. Update object locations
            room = payload.get("room", "unknown")
            detections = self.detector.detect_items_in_frame(payload, room)
            
            for d in detections:
                # Find matching item in registry or create entry
                item = self.registry.find_item(d['object_type'])
                if item:
                    # Map room and region to a storage_location_id
                    # This is simplified: in reality, logic would map region -> location_id
                    self.registry.update_item_location(item['item_id'], 1, d['confidence'])
                
            # 2. Check for low supplies (proactive)
            low_supplies = self.supply_monitor.get_low_supplies()
            if low_supplies:
                self._dispatch_supply_alert(low_supplies)
                
            # 3. Check for expiring warranties
            expiring = self.purchase_tracker.get_expiring_warranties(days_ahead=30)
            if expiring:
                self._dispatch_warranty_alert(expiring)

    def _on_utterance(self, event: Event) -> None:
        """Handle user speech for inventory queries and updates."""
        text = event.data.get("text", "").lower()
        
        # Simple query detection
        if "where is" in text or "where's my" in text:
            # Extract item name and call registry.find_item
            pass
            
        if "how much" in text and ("left" in text or "have" in text):
            # Check supply_monitor
            pass
            
        if "i just bought" in text:
            # Call purchase_tracker.log_purchase
            pass
            
        if "lent" in text and "to" in text:
            # Call purchase_tracker.track_loan
            pass

    def _dispatch_supply_alert(self, low_supplies: List[Dict[str, Any]]) -> None:
        """Send an alert to the orchestrator regarding low supplies."""
        summary = ", ".join([s['item'] for s in low_supplies])
        logger.info(f"Inventory supply alert: {summary}")
        # In actual implementation: self._bus.publish(...)

    def _dispatch_warranty_alert(self, expiring: List[Dict[str, Any]]) -> None:
        """Send an alert to the orchestrator regarding expiring warranties."""
        summary = ", ".join([w['item'] for w in expiring])
        logger.info(f"Inventory warranty alert: {summary}")
