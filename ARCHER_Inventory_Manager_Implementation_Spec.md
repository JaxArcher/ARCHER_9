# ARCHER Inventory Manager - Complete Implementation Specification

**Target**: Antigravity Development Team  
**Date**: March 5, 2026  
**Priority**: Medium-High - Solves real daily pain point  
**Complexity**: Medium (computer vision + database + tracking logic)

---

## EXECUTIVE SUMMARY

The Inventory Manager tracks all physical possessions, their locations, quantities, and states. It solves the daily frustration of "Where did I put my keys?" and "Do I have more coffee?" by maintaining a comprehensive, continuously-updated inventory of the user's belongings.

**Core Value Proposition**: Never lose track of your stuff again.

**Key Features**:
- Real-time location tracking ("Where's my wallet?" → "Dining table, 2:15 PM")
- Supply level monitoring (consumables running low)
- Purchase & warranty management
- Borrowed/lent item tracking
- Storage organization mapping
- Inventory analytics (value, duplicates, unused items)

---

## AGENT PROFILE

**Name**: Inventory Manager  
**Internal ID**: `inventory`  
**Personality**: Organized, detail-oriented, photographic memory for objects  
**Tone**: Helpful, precise, proactive

**Model**: `claude-sonnet-4-5-20250929`  
**Fallback**: `qwen3.5:9b` (local)

---

## ARCHITECTURE

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│              INVENTORY MANAGER ARCHITECTURE                  │
└─────────────────────────────────────────────────────────────┘

INPUT LAYER
┌─────────────────────────────────────────────────────────────┐
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Observer   │  │     Voice    │  │   Manual     │      │
│  │   Cameras    │  │    Commands  │  │    Input     │      │
│  │              │  │              │  │              │      │
│  │ • Passive    │  │ • "I just    │  │ • User adds  │      │
│  │   scanning   │  │   bought X"  │  │   items      │      │
│  │ • Object     │  │ • "Where's   │  │ • Barcode    │      │
│  │   detection  │  │   my..."     │  │   scan       │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                  │              │
│         └─────────────────┴──────────────────┘              │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
PROCESSING LAYER
┌─────────────────────────────────────────────────────────────┐
│  ┌────────────────────────────────────────────────┐         │
│  │          OBJECT DETECTION ENGINE               │         │
│  ├────────────────────────────────────────────────┤         │
│  │ • YOLOv8 object detection                      │         │
│  │ • Item classification (keys, wallet, phone)    │         │
│  │ • Location extraction (room, surface, region)  │         │
│  │ • Persistent ID assignment                     │         │
│  │ • Movement tracking                            │         │
│  └────────────────────────────────────────────────┘         │
│                                                              │
│  ┌────────────────────────────────────────────────┐         │
│  │         SUPPLY LEVEL MONITOR                   │         │
│  ├────────────────────────────────────────────────┤         │
│  │ • Consumable quantity estimation               │         │
│  │ • Usage rate calculation                       │         │
│  │ • Depletion prediction                         │         │
│  │ • Restock alerts                               │         │
│  └────────────────────────────────────────────────┘         │
│                                                              │
│  ┌────────────────────────────────────────────────┐         │
│  │        LOCATION TRACKING SYSTEM                │         │
│  ├────────────────────────────────────────────────┤         │
│  │ • Current location                             │         │
│  │ • Location history                             │         │
│  │ • Movement patterns                            │         │
│  │ • Last seen timestamp                          │         │
│  └────────────────────────────────────────────────┘         │
│                                                              │
│  ┌────────────────────────────────────────────────┐         │
│  │      PURCHASE & WARRANTY TRACKER               │         │
│  ├────────────────────────────────────────────────┤         │
│  │ • Purchase date & price                        │         │
│  │ • Warranty duration                            │         │
│  │ • Warranty expiration alerts                   │         │
│  │ • Receipt/document storage                     │         │
│  └────────────────────────────────────────────────┘         │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
STORAGE LAYER
┌─────────────────────────────────────────────────────────────┐
│  ┌────────────────────────────────────────────────┐         │
│  │              INVENTORY DATABASE                │         │
│  ├────────────────────────────────────────────────┤         │
│  │ SQLite Tables:                                 │         │
│  │ • items - Master item registry                 │         │
│  │ • item_locations - Location history            │         │
│  │ • consumables - Supplies & quantities          │         │
│  │ • purchases - Purchase records                 │         │
│  │ • warranties - Warranty information            │         │
│  │ • borrowed_lent - Item loans                   │         │
│  │ • storage_locations - Organization map         │         │
│  └────────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
                           ▼
OUTPUT LAYER
┌─────────────────────────────────────────────────────────────┐
│ • Voice/GUI responses to queries                            │
│ • Proactive alerts (low supplies, warranty expiring)        │
│ • Analytics & reports                                       │
│ • Shopping list generation                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## DATABASE SCHEMA

**File**: `src/archer/inventory/schema.sql`

```sql
-- Master item registry
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name TEXT NOT NULL,
    category TEXT,  -- 'electronics', 'clothing', 'tools', 'kitchen', etc.
    subcategory TEXT,
    brand TEXT,
    model TEXT,
    serial_number TEXT,
    barcode TEXT,
    estimated_value REAL,
    is_consumable BOOLEAN DEFAULT FALSE,
    persistent_object_id TEXT UNIQUE,  -- For visual tracking
    added_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME,
    current_location_id INTEGER,
    image_path TEXT,
    notes TEXT,
    FOREIGN KEY (current_location_id) REFERENCES storage_locations(id)
);

CREATE INDEX idx_items_name ON items(item_name);
CREATE INDEX idx_items_category ON items(category);
CREATE INDEX idx_items_object_id ON items(persistent_object_id);

-- Location tracking
CREATE TABLE IF NOT EXISTS item_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    location_id INTEGER NOT NULL,
    placed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    removed_at DATETIME,
    still_there BOOLEAN DEFAULT TRUE,
    confidence REAL,  -- Visual detection confidence
    FOREIGN KEY (item_id) REFERENCES items(id),
    FOREIGN KEY (location_id) REFERENCES storage_locations(id)
);

CREATE INDEX idx_locations_item ON item_locations(item_id);
CREATE INDEX idx_locations_current ON item_locations(still_there);

-- Storage location mapping
CREATE TABLE IF NOT EXISTS storage_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    location_name TEXT NOT NULL,
    room TEXT,
    furniture_type TEXT,  -- 'table', 'shelf', 'drawer', 'counter', etc.
    level INTEGER,  -- Shelf level, drawer number, etc.
    coordinates TEXT,  -- JSON: {x, y, z} or bounding box
    capacity TEXT,  -- Size/capacity description
    is_visible BOOLEAN DEFAULT TRUE,  -- Drawer=false, table=true
    parent_location_id INTEGER,  -- Nested locations (drawer in desk)
    FOREIGN KEY (parent_location_id) REFERENCES storage_locations(id)
);

CREATE INDEX idx_locations_room ON storage_locations(room);

-- Consumable supplies
CREATE TABLE IF NOT EXISTS consumables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    unit TEXT,  -- 'count', 'liters', 'kg', 'rolls', etc.
    current_quantity REAL,
    low_threshold REAL,  -- Alert when below this
    ideal_quantity REAL,  -- Target stock level
    usage_rate_per_day REAL,  -- Learned consumption rate
    estimated_days_remaining INTEGER,
    last_restocked DATETIME,
    last_quantity_update DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (item_id) REFERENCES items(id)
);

CREATE INDEX idx_consumables_item ON consumables(item_id);

-- Purchase records
CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    purchase_date DATE,
    purchase_price REAL,
    currency TEXT DEFAULT 'USD',
    vendor TEXT,
    receipt_path TEXT,
    payment_method TEXT,
    notes TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id)
);

CREATE INDEX idx_purchases_item ON purchases(item_id);
CREATE INDEX idx_purchases_date ON purchases(purchase_date);

-- Warranties
CREATE TABLE IF NOT EXISTS warranties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    warranty_duration_months INTEGER,
    warranty_start_date DATE,
    warranty_end_date DATE,
    warranty_type TEXT,  -- 'manufacturer', 'extended', 'store'
    warranty_document_path TEXT,
    coverage_details TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id)
);

CREATE INDEX idx_warranties_item ON warranties(item_id);
CREATE INDEX idx_warranties_expiration ON warranties(warranty_end_date);

-- Borrowed & Lent items
CREATE TABLE IF NOT EXISTS borrowed_lent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    person_name TEXT NOT NULL,
    transaction_type TEXT,  -- 'borrowed' or 'lent'
    transaction_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    expected_return_date DATETIME,
    actual_return_date DATETIME,
    returned BOOLEAN DEFAULT FALSE,
    notes TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id)
);

CREATE INDEX idx_borrowed_lent_item ON borrowed_lent(item_id);
CREATE INDEX idx_borrowed_lent_person ON borrowed_lent(person_name);
CREATE INDEX idx_borrowed_lent_unreturned ON borrowed_lent(returned);

-- Inventory analytics cache
CREATE TABLE IF NOT EXISTS inventory_analytics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name TEXT NOT NULL,
    metric_value TEXT,  -- JSON for complex values
    calculated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(metric_name)
);
```

---

## CORE FEATURES

### 1. Object Detection & Tracking

**File**: `src/archer/inventory/object_detector.py`

```python
class InventoryObjectDetector:
    """Detects and tracks physical objects using computer vision."""
    
    def __init__(self):
        self.yolo_model = YOLO('yolov8n.pt')  # Nano model for speed
        self.tracked_objects = {}  # persistent_id -> object data
        self.location_map = {}  # Maps screen regions to storage locations
        
    def detect_items_in_frame(self, frame: np.ndarray, room: str) -> List[Dict]:
        """
        Detect items in current frame.
        
        Returns list of detected items with:
        - object_type: str
        - bounding_box: (x1, y1, x2, y2)
        - confidence: float
        - location_region: str
        - persistent_id: str (for tracking same object over time)
        """
        results = self.yolo_model(frame)
        
        detected_items = []
        for detection in results[0].boxes:
            # Extract detection info
            bbox = detection.xyxy[0].cpu().numpy()
            confidence = float(detection.conf[0])
            class_id = int(detection.cls[0])
            class_name = results[0].names[class_id]
            
            # Map bbox to location in room
            location_region = self._map_bbox_to_location(bbox, room)
            
            # Assign persistent ID (track same object across frames)
            persistent_id = self._get_or_create_persistent_id(
                class_name, bbox, frame
            )
            
            detected_items.append({
                'object_type': class_name,
                'bounding_box': bbox.tolist(),
                'confidence': confidence,
                'location_region': location_region,
                'persistent_id': persistent_id,
                'timestamp': datetime.now()
            })
            
        return detected_items
        
    def _map_bbox_to_location(self, bbox: np.ndarray, room: str) -> str:
        """
        Map bounding box coordinates to storage location.
        
        Example:
        - bbox in upper-left = "kitchen counter"
        - bbox near floor = "floor"
        - bbox on desk = "desk surface"
        
        This requires calibration/learning phase where user labels regions.
        """
        # Calculate bbox center
        center_x = (bbox[0] + bbox[2]) / 2
        center_y = (bbox[1] + bbox[3]) / 2
        
        # Check which location region contains this point
        for location_name, region in self.location_map.get(room, {}).items():
            if self._point_in_region(center_x, center_y, region):
                return location_name
                
        return "unknown_location"
        
    def _get_or_create_persistent_id(self, class_name: str, bbox: np.ndarray, 
                                     frame: np.ndarray) -> str:
        """
        Track same object across frames using visual features.
        
        Approach:
        - Extract visual features (color histogram, HOG, etc.)
        - Compare to known objects of same class
        - If match found, return existing ID
        - If new object, create new ID
        """
        # Extract features from bbox region
        x1, y1, x2, y2 = bbox.astype(int)
        object_region = frame[y1:y2, x1:x2]
        features = self._extract_visual_features(object_region)
        
        # Find matching object
        for obj_id, obj_data in self.tracked_objects.items():
            if obj_data['class_name'] != class_name:
                continue
                
            # Compare features
            similarity = self._compare_features(features, obj_data['features'])
            if similarity > 0.85:  # High confidence match
                # Update last seen
                obj_data['last_seen'] = datetime.now()
                obj_data['last_bbox'] = bbox
                return obj_id
                
        # New object - create ID
        new_id = f"{class_name}_{uuid.uuid4().hex[:8]}"
        self.tracked_objects[new_id] = {
            'class_name': class_name,
            'features': features,
            'first_seen': datetime.now(),
            'last_seen': datetime.now(),
            'last_bbox': bbox
        }
        
        return new_id
        
    def _extract_visual_features(self, image: np.ndarray) -> np.ndarray:
        """Extract visual features for object matching."""
        # Color histogram
        hist = cv2.calcHist([image], [0, 1, 2], None, [8, 8, 8], 
                           [0, 256, 0, 256, 0, 256])
        hist = cv2.normalize(hist, hist).flatten()
        
        return hist
        
    def calibrate_location_regions(self, room: str, location_name: str, 
                                   bbox: Tuple[int, int, int, int]):
        """
        User teaches system where locations are.
        
        Example:
        User says "This is the kitchen counter" while pointing camera at it.
        System saves the region.
        """
        if room not in self.location_map:
            self.location_map[room] = {}
            
        self.location_map[room][location_name] = {
            'bbox': bbox,
            'calibrated_at': datetime.now()
        }
```

### 2. Item Registry & Query System

**File**: `src/archer/inventory/item_registry.py`

```python
class ItemRegistry:
    """Manages the master inventory database."""
    
    def __init__(self, db_path: str = "data/archer.db"):
        self.db = sqlite3.connect(db_path)
        self._create_tables()
        
    def add_item(self, item_name: str, category: str, metadata: Dict = None) -> int:
        """
        Add new item to inventory.
        
        Args:
            item_name: Human-readable name
            category: Item category
            metadata: Optional additional data (brand, model, etc.)
            
        Returns:
            item_id
        """
        cursor = self.db.cursor()
        
        cursor.execute("""
            INSERT INTO items (item_name, category, brand, model, serial_number, 
                              barcode, estimated_value, is_consumable, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item_name,
            category,
            metadata.get('brand'),
            metadata.get('model'),
            metadata.get('serial_number'),
            metadata.get('barcode'),
            metadata.get('estimated_value'),
            metadata.get('is_consumable', False),
            metadata.get('notes')
        ))
        
        self.db.commit()
        return cursor.lastrowid
        
    def update_item_location(self, item_id: int, location_id: int, confidence: float = 1.0):
        """
        Update where item was last seen.
        
        Creates location history entry and updates current location.
        """
        cursor = self.db.cursor()
        
        # Close previous location record
        cursor.execute("""
            UPDATE item_locations 
            SET still_there = FALSE, removed_at = CURRENT_TIMESTAMP
            WHERE item_id = ? AND still_there = TRUE
        """, (item_id,))
        
        # Add new location record
        cursor.execute("""
            INSERT INTO item_locations (item_id, location_id, confidence)
            VALUES (?, ?, ?)
        """, (item_id, location_id, confidence))
        
        # Update item's current location
        cursor.execute("""
            UPDATE items 
            SET current_location_id = ?, last_seen = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (location_id, item_id))
        
        self.db.commit()
        
    def find_item(self, item_name: str) -> Dict[str, Any]:
        """
        Locate an item by name.
        
        Returns:
            {
                'item_id': int,
                'item_name': str,
                'current_location': str,
                'last_seen': datetime,
                'location_history': List[Dict]
            }
        """
        cursor = self.db.cursor()
        
        cursor.execute("""
            SELECT i.id, i.item_name, sl.location_name, sl.room, i.last_seen
            FROM items i
            LEFT JOIN storage_locations sl ON i.current_location_id = sl.id
            WHERE i.item_name LIKE ?
            ORDER BY i.last_seen DESC
            LIMIT 1
        """, (f"%{item_name}%",))
        
        row = cursor.fetchone()
        if not row:
            return None
            
        item_id, name, location, room, last_seen = row
        
        # Get location history
        cursor.execute("""
            SELECT sl.location_name, sl.room, il.placed_at, il.removed_at
            FROM item_locations il
            JOIN storage_locations sl ON il.location_id = sl.id
            WHERE il.item_id = ?
            ORDER BY il.placed_at DESC
            LIMIT 5
        """, (item_id,))
        
        history = [
            {
                'location': loc,
                'room': rm,
                'placed_at': placed,
                'removed_at': removed
            }
            for loc, rm, placed, removed in cursor.fetchall()
        ]
        
        return {
            'item_id': item_id,
            'item_name': name,
            'current_location': f"{location} in {room}" if location else "Unknown",
            'last_seen': last_seen,
            'location_history': history
        }
        
    def get_items_in_location(self, location_id: int) -> List[Dict]:
        """Get all items currently in a specific location."""
        cursor = self.db.cursor()
        
        cursor.execute("""
            SELECT i.id, i.item_name, i.category, il.placed_at
            FROM items i
            JOIN item_locations il ON i.id = il.item_id
            WHERE il.location_id = ? AND il.still_there = TRUE
            ORDER BY il.placed_at DESC
        """, (location_id,))
        
        return [
            {
                'item_id': id,
                'name': name,
                'category': category,
                'placed_at': placed
            }
            for id, name, category, placed in cursor.fetchall()
        ]
```

### 3. Consumable Supply Monitor

**File**: `src/archer/inventory/supply_monitor.py`

```python
class SupplyMonitor:
    """Monitors consumable supplies and predicts depletion."""
    
    def __init__(self, db_path: str = "data/archer.db"):
        self.db = sqlite3.connect(db_path)
        
    def track_consumable(self, item_id: int, unit: str, current_quantity: float,
                        low_threshold: float, ideal_quantity: float):
        """
        Register a consumable item for monitoring.
        
        Args:
            item_id: Item ID from items table
            unit: 'count', 'liters', 'kg', 'rolls', etc.
            current_quantity: Current amount
            low_threshold: Alert when below this
            ideal_quantity: Target stock level
        """
        cursor = self.db.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO consumables 
            (item_id, unit, current_quantity, low_threshold, ideal_quantity)
            VALUES (?, ?, ?, ?, ?)
        """, (item_id, unit, current_quantity, low_threshold, ideal_quantity))
        
        self.db.commit()
        
    def update_quantity(self, item_id: int, new_quantity: float, 
                       consumed: bool = False):
        """
        Update quantity and calculate usage rate.
        
        Args:
            item_id: Item ID
            new_quantity: New quantity level
            consumed: True if this is consumption, False if restocking
        """
        cursor = self.db.cursor()
        
        # Get current data
        cursor.execute("""
            SELECT current_quantity, usage_rate_per_day, last_quantity_update
            FROM consumables
            WHERE item_id = ?
        """, (item_id,))
        
        row = cursor.fetchone()
        if not row:
            return
            
        old_quantity, old_usage_rate, last_update = row
        
        # Calculate usage rate if this is consumption
        if consumed and last_update:
            days_since_update = (datetime.now() - 
                               datetime.fromisoformat(last_update)).days
            if days_since_update > 0:
                consumed_amount = old_quantity - new_quantity
                usage_rate = consumed_amount / days_since_update
                
                # Smooth with existing rate (exponential moving average)
                if old_usage_rate:
                    usage_rate = 0.7 * old_usage_rate + 0.3 * usage_rate
        else:
            usage_rate = old_usage_rate
            
        # Estimate days remaining
        if usage_rate and usage_rate > 0:
            days_remaining = int(new_quantity / usage_rate)
        else:
            days_remaining = None
            
        # Update database
        cursor.execute("""
            UPDATE consumables
            SET current_quantity = ?,
                usage_rate_per_day = ?,
                estimated_days_remaining = ?,
                last_quantity_update = CURRENT_TIMESTAMP,
                last_restocked = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE last_restocked END
            WHERE item_id = ?
        """, (new_quantity, usage_rate, days_remaining, not consumed, item_id))
        
        self.db.commit()
        
    def get_low_supplies(self) -> List[Dict]:
        """
        Get consumables running low.
        
        Returns items below threshold or predicted to run out soon.
        """
        cursor = self.db.cursor()
        
        cursor.execute("""
            SELECT i.item_name, c.current_quantity, c.unit, c.low_threshold,
                   c.estimated_days_remaining, c.usage_rate_per_day
            FROM consumables c
            JOIN items i ON c.item_id = i.id
            WHERE c.current_quantity <= c.low_threshold 
               OR c.estimated_days_remaining <= 7
            ORDER BY c.estimated_days_remaining ASC NULLS LAST
        """)
        
        return [
            {
                'item': name,
                'current': qty,
                'unit': unit,
                'threshold': threshold,
                'days_remaining': days,
                'daily_usage': usage
            }
            for name, qty, unit, threshold, days, usage in cursor.fetchall()
        ]
        
    def predict_next_restock_date(self, item_id: int) -> datetime:
        """
        Predict when item will need restocking.
        
        Based on usage rate and current quantity.
        """
        cursor = self.db.cursor()
        
        cursor.execute("""
            SELECT current_quantity, usage_rate_per_day, low_threshold
            FROM consumables
            WHERE item_id = ?
        """, (item_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
            
        qty, usage_rate, threshold = row
        
        if not usage_rate or usage_rate <= 0:
            return None
            
        # Calculate days until threshold
        days_until_low = (qty - threshold) / usage_rate
        
        if days_until_low <= 0:
            return datetime.now()  # Already low
            
        return datetime.now() + timedelta(days=days_until_low)
```

### 4. Purchase & Warranty Tracker

**File**: `src/archer/inventory/purchase_tracker.py`

```python
class PurchaseTracker:
    """Tracks purchases and warranties."""
    
    def __init__(self, db_path: str = "data/archer.db"):
        self.db = sqlite3.connect(db_path)
        
    def log_purchase(self, item_id: int, purchase_date: datetime.date,
                    price: float, vendor: str = None, receipt_path: str = None):
        """Record a purchase."""
        cursor = self.db.cursor()
        
        cursor.execute("""
            INSERT INTO purchases (item_id, purchase_date, purchase_price, 
                                  vendor, receipt_path)
            VALUES (?, ?, ?, ?, ?)
        """, (item_id, purchase_date, price, vendor, receipt_path))
        
        self.db.commit()
        
    def add_warranty(self, item_id: int, duration_months: int, 
                    start_date: datetime.date, warranty_type: str = "manufacturer"):
        """Add warranty information for an item."""
        cursor = self.db.cursor()
        
        end_date = start_date + timedelta(days=duration_months * 30)
        
        cursor.execute("""
            INSERT INTO warranties (item_id, warranty_duration_months, 
                                   warranty_start_date, warranty_end_date, 
                                   warranty_type)
            VALUES (?, ?, ?, ?, ?)
        """, (item_id, duration_months, start_date, end_date, warranty_type))
        
        self.db.commit()
        
    def check_warranty_status(self, item_id: int) -> Dict[str, Any]:
        """Check if item is under warranty."""
        cursor = self.db.cursor()
        
        cursor.execute("""
            SELECT warranty_end_date, warranty_type, coverage_details,
                   warranty_document_path
            FROM warranties
            WHERE item_id = ?
            ORDER BY warranty_end_date DESC
            LIMIT 1
        """, (item_id,))
        
        row = cursor.fetchone()
        if not row:
            return {'under_warranty': False}
            
        end_date, warranty_type, coverage, doc_path = row
        end_date = datetime.fromisoformat(end_date).date()
        
        under_warranty = end_date >= datetime.now().date()
        days_remaining = (end_date - datetime.now().date()).days
        
        return {
            'under_warranty': under_warranty,
            'warranty_type': warranty_type,
            'expiration_date': end_date,
            'days_remaining': days_remaining,
            'coverage': coverage,
            'document_path': doc_path
        }
        
    def get_expiring_warranties(self, days_ahead: int = 30) -> List[Dict]:
        """Get warranties expiring soon."""
        cursor = self.db.cursor()
        
        cutoff_date = datetime.now().date() + timedelta(days=days_ahead)
        
        cursor.execute("""
            SELECT i.item_name, w.warranty_end_date, w.warranty_type,
                   p.purchase_price
            FROM warranties w
            JOIN items i ON w.item_id = i.id
            LEFT JOIN purchases p ON w.item_id = p.item_id
            WHERE w.warranty_end_date <= ?
              AND w.warranty_end_date >= CURRENT_DATE
            ORDER BY w.warranty_end_date ASC
        """, (cutoff_date,))
        
        return [
            {
                'item': name,
                'expiration': exp,
                'type': wtype,
                'original_price': price,
                'days_remaining': (datetime.fromisoformat(exp).date() - 
                                 datetime.now().date()).days
            }
            for name, exp, wtype, price in cursor.fetchall()
        ]
```

### 5. Borrowed/Lent Tracker

**File**: `src/archer/inventory/loan_tracker.py`

```python
class LoanTracker:
    """Tracks items borrowed from or lent to others."""
    
    def __init__(self, db_path: str = "data/archer.db"):
        self.db = sqlite3.connect(db_path)
        
    def lend_item(self, item_id: int, person: str, expected_return: datetime = None,
                 notes: str = None):
        """Record lending an item to someone."""
        cursor = self.db.cursor()
        
        cursor.execute("""
            INSERT INTO borrowed_lent (item_id, person_name, transaction_type,
                                      expected_return_date, notes)
            VALUES (?, ?, 'lent', ?, ?)
        """, (item_id, person, expected_return, notes))
        
        self.db.commit()
        
        return {
            'message': f"Recorded: Lent {self._get_item_name(item_id)} to {person}",
            'reminder': f"Expected back: {expected_return}" if expected_return else None
        }
        
    def borrow_item(self, item_name: str, person: str, expected_return: datetime = None):
        """Record borrowing an item from someone."""
        # Create item entry if doesn't exist
        item_id = self._get_or_create_item(item_name, category="borrowed")
        
        cursor = self.db.cursor()
        
        cursor.execute("""
            INSERT INTO borrowed_lent (item_id, person_name, transaction_type,
                                      expected_return_date)
            VALUES (?, ?, 'borrowed', ?)
        """, (item_id, person, expected_return))
        
        self.db.commit()
        
        return {
            'message': f"Recorded: Borrowed {item_name} from {person}",
            'reminder': f"Return by: {expected_return}" if expected_return else None
        }
        
    def return_item(self, item_id: int, person: str):
        """Mark item as returned."""
        cursor = self.db.cursor()
        
        cursor.execute("""
            UPDATE borrowed_lent
            SET returned = TRUE, actual_return_date = CURRENT_TIMESTAMP
            WHERE item_id = ? AND person_name = ? AND returned = FALSE
        """, (item_id, person))
        
        self.db.commit()
        
    def get_unreturned_items(self) -> Dict[str, List[Dict]]:
        """
        Get items not yet returned (both borrowed and lent).
        
        Returns:
            {
                'lent': [...],
                'borrowed': [...]
            }
        """
        cursor = self.db.cursor()
        
        # Get lent items
        cursor.execute("""
            SELECT i.item_name, bl.person_name, bl.transaction_date,
                   bl.expected_return_date
            FROM borrowed_lent bl
            JOIN items i ON bl.item_id = i.id
            WHERE bl.transaction_type = 'lent' AND bl.returned = FALSE
            ORDER BY bl.expected_return_date ASC NULLS LAST
        """)
        
        lent = [
            {
                'item': name,
                'person': person,
                'since': trans_date,
                'expected_return': exp_return,
                'overdue': (datetime.fromisoformat(exp_return) < datetime.now() 
                           if exp_return else False)
            }
            for name, person, trans_date, exp_return in cursor.fetchall()
        ]
        
        # Get borrowed items
        cursor.execute("""
            SELECT i.item_name, bl.person_name, bl.transaction_date,
                   bl.expected_return_date
            FROM borrowed_lent bl
            JOIN items i ON bl.item_id = i.id
            WHERE bl.transaction_type = 'borrowed' AND bl.returned = FALSE
            ORDER BY bl.expected_return_date ASC NULLS LAST
        """)
        
        borrowed = [
            {
                'item': name,
                'from_person': person,
                'since': trans_date,
                'expected_return': exp_return,
                'overdue': (datetime.fromisoformat(exp_return) < datetime.now() 
                           if exp_return else False)
            }
            for name, person, trans_date, exp_return in cursor.fetchall()
        ]
        
        return {
            'lent': lent,
            'borrowed': borrowed
        }
```

---

## VOICE COMMANDS

**File**: `src/archer/inventory/voice_commands.py`

```python
# Command patterns the Inventory Manager should recognize

COMMAND_PATTERNS = {
    'locate_item': [
        "where's my {item}",
        "where is my {item}",
        "where did I put my {item}",
        "find my {item}",
        "locate my {item}",
        "I can't find my {item}",
        "have you seen my {item}"
    ],
    
    'add_item': [
        "I just bought {item}",
        "I got a new {item}",
        "add {item} to inventory",
        "track my {item}",
        "I have a {item} now"
    ],
    
    'check_supplies': [
        "do I have {item}",
        "how much {item} do I have",
        "am I out of {item}",
        "check {item} supplies",
        "do I need to buy {item}"
    ],
    
    'lend_item': [
        "I'm lending {person} my {item}",
        "I lent my {item} to {person}",
        "{person} borrowed my {item}"
    ],
    
    'borrow_item': [
        "I borrowed {item} from {person}",
        "I'm borrowing {person}'s {item}",
        "{person} lent me their {item}"
    ],
    
    'warranty_check': [
        "is my {item} under warranty",
        "warranty status for {item}",
        "when does {item} warranty expire"
    ],
    
    'shopping_list': [
        "what do I need to buy",
        "generate shopping list",
        "what supplies are low",
        "what am I running out of"
    ]
}
```

---

## PROACTIVE ALERTS

**File**: `src/archer/inventory/alert_system.py`

```python
class InventoryAlertSystem:
    """Generates proactive alerts for inventory issues."""
    
    def __init__(self, supply_monitor: SupplyMonitor, purchase_tracker: PurchaseTracker,
                 loan_tracker: LoanTracker):
        self.supply_monitor = supply_monitor
        self.purchase_tracker = purchase_tracker
        self.loan_tracker = loan_tracker
        
    def check_and_generate_alerts(self) -> List[Dict]:
        """
        Check all alert conditions and generate appropriate alerts.
        
        Run this periodically (daily or on-demand).
        """
        alerts = []
        
        # Low supplies
        low_supplies = self.supply_monitor.get_low_supplies()
        for supply in low_supplies:
            if supply['days_remaining'] and supply['days_remaining'] <= 3:
                severity = 'urgent'
            elif supply['days_remaining'] and supply['days_remaining'] <= 7:
                severity = 'moderate'
            else:
                severity = 'low'
                
            alerts.append({
                'type': 'low_supply',
                'severity': severity,
                'message': f"{supply['item']} is running low - {supply['days_remaining']} days left",
                'action': f"Add to shopping list?",
                'data': supply
            })
            
        # Expiring warranties
        expiring = self.purchase_tracker.get_expiring_warranties(days_ahead=30)
        for warranty in expiring:
            if warranty['days_remaining'] <= 7:
                severity = 'high'
            else:
                severity = 'moderate'
                
            alerts.append({
                'type': 'warranty_expiring',
                'severity': severity,
                'message': f"{warranty['item']} warranty expires in {warranty['days_remaining']} days",
                'action': "Want warranty info?",
                'data': warranty
            })
            
        # Unreturned items
        unreturned = self.loan_tracker.get_unreturned_items()
        
        # Lent items
        for item in unreturned['lent']:
            if item['overdue']:
                alerts.append({
                    'type': 'lent_item_overdue',
                    'severity': 'moderate',
                    'message': f"{item['person']} hasn't returned your {item['item']} yet",
                    'action': f"Remind them?",
                    'data': item
                })
                
        # Borrowed items
        for item in unreturned['borrowed']:
            if item['overdue']:
                alerts.append({
                    'type': 'borrowed_item_overdue',
                    'severity': 'high',
                    'message': f"You need to return {item['item']} to {item['from_person']}",
                    'action': "Set reminder?",
                    'data': item
                })
                
        return alerts
```

---

## IMPLEMENTATION PHASES

### Phase 1: Basic Inventory (Week 1-2)
- Database schema
- Manual item entry (voice/GUI)
- Item registry & query system
- Basic location tracking (manual)
- "Where's my X?" queries

### Phase 2: Computer Vision Integration (Week 3-4)
- Object detection with YOLO
- Persistent object tracking
- Location region calibration
- Passive inventory scanning
- Automatic item discovery

### Phase 3: Consumables & Supplies (Week 5)
- Supply level monitoring
- Usage rate calculation
- Depletion prediction
- Low supply alerts
- Shopping list generation

### Phase 4: Purchases & Warranties (Week 6)
- Purchase logging
- Warranty tracking
- Expiration alerts
- Receipt storage

### Phase 5: Loans & Advanced Features (Week 7)
- Borrowed/lent tracking
- Inventory analytics
- Duplicate detection
- Value tracking

---

## SUCCESS CRITERIA

**Phase 1**:
- [ ] User can add items manually
- [ ] User can query "Where's my wallet?" and get answer
- [ ] Location history tracked

**Phase 2**:
- [ ] System detects common items (keys, phone, wallet)
- [ ] Tracks item movement across rooms
- [ ] Updates location automatically

**Phase 3**:
- [ ] Alerts when coffee running low
- [ ] Predicts depletion date
- [ ] Generates shopping list

**Phase 4**:
- [ ] Logs purchases with price
- [ ] Tracks warranty status
- [ ] Alerts before warranty expires

**Phase 5**:
- [ ] Tracks lent items
- [ ] Reminds to get items back
- [ ] Shows inventory value

---

**END OF SPECIFICATION**

Estimated implementation time: 7 weeks  
Complexity: Medium  
Value: High - solves daily frustration
