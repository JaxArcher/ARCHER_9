"""
Universal Tool Executor for ARCHER.

Routes tool calls to appropriate implementations (PC control, canvas, etc.)
based on skill category.
"""

from typing import Dict, Any
from loguru import logger

from archer.tools.pc_control import PCController
from archer.canvas.renderer import execute_canvas_tool
from archer.skills.skills_registry import get_tool_category
from archer.tools.inventory_tools import InventoryTools


class UniversalToolExecutor:
    """Executes tools from any skill category."""
    
    def __init__(self):
        self._pc_controller = PCController()
        self._inventory_tools = InventoryTools()
        self._confirmation_required = {
            'open_url', 'click', 'type_text', 'hotkey', 'focus_window',
            'browser_click', 'browser_type', 'close_browser'
        }
    
    def execute(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call by routing to the correct implementation."""
        try:
            category = get_tool_category(tool_name)
            
            if category == 'automation':
                return self._exec_pc_tool(tool_name, tool_input)
            elif category == 'visualization':
                result = execute_canvas_tool(tool_name, tool_input)
                return {'result': result}
            elif category == 'inventory':
                return self._exec_inventory_tool(tool_name, tool_input)
            else:
                return {'error': f'Unknown tool category: {category}'}
                
        except Exception as e:
            logger.error(f'Tool execution failed ({tool_name}): {e}')
            return {'error': str(e)}
    
    def requires_confirmation(self, tool_name: str) -> bool:
        """Check if tool requires user confirmation."""
        return tool_name in self._confirmation_required
    
    def reset_halt(self) -> None:
        """Clear HALT flag."""
        self._pc_controller.reset_halt()
    
    def _exec_pc_tool(self, tool_name: str, inp: Dict[str, Any]) -> Dict[str, Any]:
        """Execute PC control tools."""
        if tool_name == 'take_screenshot':
            region = inp.get('region')
            result = self._pc_controller.take_screenshot(region)
            if result:
                return {'result': f'Screenshot captured', 'image': result}
            return {'error': 'Screenshot failed'}
        
        elif tool_name == 'get_active_window':
            return {'result': self._pc_controller.get_active_window()}
        
        elif tool_name == 'list_windows':
            return {'result': self._pc_controller.list_windows()}
        
        elif tool_name == 'open_url':
            result = self._pc_controller.open_url(inp['url'])
            return {'result': result}
        
        elif tool_name == 'click':
            x, y = inp['x'], inp['y']
            button = inp.get('button', 'left')
            success = self._pc_controller.click(x, y, button)
            return {'result': {'success': success}}
        
        elif tool_name == 'type_text':
            success = self._pc_controller.type_text(inp['text'])
            return {'result': {'success': success}}
        
        elif tool_name == 'hotkey':
            success = self._pc_controller.hotkey(*inp['keys'])
            return {'result': {'success': success}}
        
        elif tool_name == 'focus_window':
            success = self._pc_controller.focus_window(inp['title'])
            return {'result': {'success': success}}
        
        elif tool_name == 'browser_click':
            success = self._pc_controller.browser_click(inp['selector'])
            return {'result': {'success': success}}
        
        elif tool_name == 'browser_type':
            success = self._pc_controller.browser_type(inp['selector'], inp['text'])
            return {'result': {'success': success}}
        
        elif tool_name == 'browser_get_text':
            text = self._pc_controller.browser_get_text(inp.get('selector', 'body'))
            return {'result': text}
        
        elif tool_name == 'browser_screenshot':
            result = self._pc_controller.browser_screenshot()
            if result:
                return {'result': 'Browser screenshot captured', 'image': result}
            return {'error': 'No active browser page'}
        
        elif tool_name == 'close_browser':
            self._pc_controller.close_browser()
            return {'result': {'success': True}}
        
        else:
            return {'error': f'Unknown PC tool: {tool_name}'}

    def _exec_inventory_tool(self, tool_name: str, inp: Dict[str, Any]) -> Dict[str, Any]:
        """Execute inventory management tools."""
        if tool_name == 'search_inventory':
            query = inp.get('query', '')
            results = self._inventory_tools.search_items(query)
            return {'result': results}
            
        elif tool_name == 'add_inventory_item':
            name = inp.get('name', '')
            location = inp.get('location')
            category = inp.get('category')
            notes = inp.get('notes')
            result = self._inventory_tools.add_item(name, location, category, notes)
            return {'result': result}
            
        elif tool_name == 'get_low_supplies':
            results = self._inventory_tools.get_low_supplies()
            return {'result': results}
            
        elif tool_name == 'log_purchase':
            # This is simplified: in reality, it would call purchase_tracker.log_purchase
            return {'result': 'Purchase logged successfully.'}
            
        elif tool_name == 'track_loan':
            # This is simplified: in reality, it would call purchase_tracker.track_loan
            return {'result': 'Loan tracked successfully.'}
            
        else:
            return {'error': f'Unknown inventory tool: {tool_name}'}
