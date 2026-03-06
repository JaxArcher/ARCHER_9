---
name: Inventory Management
description: Tracking and managing physical objects, supplies, and locations.
category: inventory
---

### search_inventory
Search for items in the user's physical inventory. Returns location, category, and notes.
**Parameters:**
- query: The name or category of the item to search for.

### add_inventory_item
Add a new item to the permanent inventory or update an existing one.
**Parameters:**
- name: The name of the item.
- location: (optional) Where the item is stored.
- category: (optional) The category of the item (e.g., electronics, tools, kitchen).
- notes: (optional) Any additional details about the item.

### get_low_supplies
Get a list of consumable supplies that are running low and need restocking.
**Parameters:**
- category: (optional) Filter by category (e.g., 'groceries', 'office').

### log_purchase
Record a new purchase for an item, including price and date.
**Parameters:**
- name: The name of the item purchased.
- price: (optional) The price paid (number).
- vendor: (optional) Where it was bought.
- date: (optional) The date of purchase (YYYY-MM-DD).

### track_loan
Record that an item has been lent to or borrowed from someone.
**Parameters:**
- name: The name of the item.
- person: The name of the person involved.
- type: The transaction type: 'borrowed' or 'lent'.
- due_date: (optional) When it's expected back (YYYY-MM-DD).
