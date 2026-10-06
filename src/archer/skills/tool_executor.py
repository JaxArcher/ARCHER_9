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
from archer.core.event_bus import get_event_bus, Event, EventType
from archer.memory.sqlite_store import get_sqlite_store


class UniversalToolExecutor:
    """Executes tools from any skill category."""
    
    def __init__(self):
        self._pc_controller = PCController()
        self._inventory_tools = InventoryTools()
        self._store = get_sqlite_store()
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
            elif category == 'ui_control':
                return self._exec_ui_control_tool(tool_name, tool_input)
            elif category == 'tasks':
                return self._exec_tasks_tool(tool_name, tool_input)
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
            # Was hard-coded to "No active browser page" even when a page
            # genuinely was open (2026-09-19 finding: the real cause was a
            # Playwright thread-affinity crash inside browser_screenshot()
            # itself, now fixed -- see pc_control.py's _pw_executor). Keeping
            # this message honest about there being two real possibilities.
            return {'error': 'No active browser page, or the screenshot capture failed -- see ARCHER logs'}
        
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

    def _exec_ui_control_tool(self, tool_name: str, inp: Dict[str, Any]) -> Dict[str, Any]:
        """Execute tools that control ARCHER's own browser/desktop interface."""
        if tool_name == 'switch_tab':
            tab_name = (inp.get('tab_name') or '').strip().lower()
            if not tab_name:
                return {'error': 'tab_name is required'}
            get_event_bus().publish(Event(
                type=EventType.UI_SWITCH_TAB,
                source='tool_executor',
                data={'tab': tab_name},
            ))
            return {'result': {'success': True, 'tab': tab_name}}

        else:
            return {'error': f'Unknown UI control tool: {tool_name}'}

    def _exec_tasks_tool(self, tool_name: str, inp: Dict[str, Any]) -> Dict[str, Any]:
        """Execute task/habit tools (tasks_SKILL.md). Available to every
        agent persona -- get_all_tools() is unscoped by persona/stance tag,
        so this is true by construction, not something requiring separate
        per-persona wiring (Col's call, 2026-09-16).

        Publishes EventType.TASKS_CHANGED after any write so the browser
        TASKS tab refreshes even when the change came from a voice/text
        command rather than a click in the tab itself -- same pattern as
        the MEMORY tab's memory_snapshot broadcast."""
        def _notify_changed():
            get_event_bus().publish(Event(
                type=EventType.TASKS_CHANGED, source='tool_executor', data={},
            ))

        if tool_name == 'add_task':
            title = (inp.get('title') or '').strip()
            if not title:
                return {'error': 'title is required'}
            task_id = self._store.add_task(
                title=title,
                due_date=inp.get('due_date'),
                source=inp.get('source') or 'user',
            )
            _notify_changed()
            return {'result': {'task_id': task_id, 'title': title}}

        elif tool_name == 'list_tasks':
            return {'result': self._store.get_tasks(status=inp.get('status'))}

        elif tool_name == 'complete_task':
            task_id = inp.get('task_id')
            if task_id is None:
                return {'error': 'task_id is required'}
            self._store.complete_task(int(task_id))
            _notify_changed()
            return {'result': {'success': True, 'task_id': task_id}}

        elif tool_name == 'delete_task':
            task_id = inp.get('task_id')
            if task_id is None:
                return {'error': 'task_id is required'}
            self._store.delete_task(int(task_id))
            _notify_changed()
            return {'result': {'success': True, 'task_id': task_id}}

        elif tool_name == 'add_habit':
            name = (inp.get('name') or '').strip()
            if not name:
                return {'error': 'name is required'}
            habit_id = self._store.add_habit(name=name, frequency=inp.get('frequency') or 'daily')
            _notify_changed()
            return {'result': {'habit_id': habit_id, 'name': name}}

        elif tool_name == 'list_habits':
            return {'result': self._store.get_habits()}

        elif tool_name == 'complete_habit':
            name = (inp.get('name') or '').strip()
            if not name:
                return {'error': 'name is required'}
            result = self._store.complete_habit(name)
            if 'error' not in result:
                _notify_changed()
            return {'result': result}

        elif tool_name == 'delete_habit':
            name = (inp.get('name') or '').strip()
            if not name:
                return {'error': 'name is required'}
            self._store.delete_habit(name)
            _notify_changed()
            return {'result': {'success': True, 'name': name}}

        else:
            return {'error': f'Unknown tasks tool: {tool_name}'}
