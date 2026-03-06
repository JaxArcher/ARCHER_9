"""
Object Detector for ARCHER Inventory Manager.
Detects and tracks physical objects, quantities, and locations.
"""

from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

class InventoryObjectDetector:
    """Detects and tracks physical objects using computer vision."""
    
    def __init__(self, db_store: Any):
        self.db = db_store
        self.tracked_objects: Dict[str, Dict[str, Any]] = {}
        self.location_map: Dict[str, Dict[str, Any]] = {} # room -> {location_name: region_bbox}
        
    def detect_items_in_frame(self, frame_data: Dict[str, Any], room: str) -> List[Dict[str, Any]]:
        """
        Detect items in current frame data (YOLO output from Observer).
        """
        results = frame_data.get('detections', [])
        detected_items = []
        
        for d in results:
            class_name = d.get('class_name')
            bbox = d.get('bbox') # [x1, y1, x2, y2]
            confidence = d.get('confidence', 0.0)
            
            # Map bbox to location in room
            location_region = self._map_bbox_to_location(bbox, room)
            
            # Assign persistent ID (track same object across frames)
            persistent_id = self._get_or_create_persistent_id(class_name, bbox, frame_data)
            
            detected_items.append({
                'object_type': class_name,
                'bounding_box': bbox,
                'confidence': confidence,
                'location_region': location_region,
                'persistent_id': persistent_id,
                'timestamp': datetime.now()
            })
            
        return detected_items
        
    def _map_bbox_to_location(self, bbox: List[int], room: str) -> str:
        """Map bounding box coordinates to storage location."""
        if not bbox or room not in self.location_map:
            return "unknown_location"
            
        center_x = (bbox[0] + bbox[2]) / 2
        center_y = (bbox[1] + bbox[3]) / 2
        
        # Check regions
        for loc_name, region in self.location_map[room].items():
            r = region.get('bbox', [])
            if r and r[0] <= center_x <= r[2] and r[1] <= center_y <= r[3]:
                return loc_name
        return "unknown_location"
        
    def _get_or_create_persistent_id(self, class_name: str, bbox: List[int], frame_data: Dict[str, Any]) -> str:
        """Assign or retrieve persistent ID."""
        # Simple heuristic: find nearest object of same class within 5% of screen
        # In reality, this would use visual features
        for obj_id, data in self.tracked_objects.items():
            if data['class_name'] == class_name:
                # Mock similarity check
                return obj_id
                
        # New object
        new_id = f"{class_name}_{str(uuid.uuid4())[:8]}"
        self.tracked_objects[new_id] = {
            'class_name': class_name,
            'first_seen': datetime.now(),
            'last_seen': datetime.now()
        }
        return new_id
        
    def calibrate_location(self, room: str, location_name: str, bbox: List[int]):
        """User teaches where locations are."""
        if room not in self.location_map:
            self.location_map[room] = {}
        self.location_map[room][location_name] = {'bbox': bbox}
        logger.info(f"Location {location_name} calibrated in {room}.")
