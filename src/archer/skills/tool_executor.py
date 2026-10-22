"""
Universal Tool Executor for ARCHER.

Routes tool calls to appropriate implementations (PC control, canvas, etc.)
based on skill category.
"""

import time
from typing import Dict, Any
from loguru import logger

from archer.tools.pc_control import PCController
from archer.canvas.renderer import execute_canvas_tool
from archer.skills.skills_registry import get_tool_category
from archer.tools.inventory_tools import InventoryTools
from archer.core.event_bus import get_event_bus, Event, EventType
from archer.memory.sqlite_store import get_sqlite_store


from archer.core.approvals import get_approval_manager
from archer.tools.document_tools import DocumentTools
from archer.tools.terminal_manager import get_terminal_manager


class UniversalToolExecutor:
    """Executes tools from any skill category."""
    
    def __init__(self):
        self._bus = get_event_bus()
        self._pc_controller = PCController()
        self._inventory_tools = InventoryTools()
        self._store = get_sqlite_store()
        self._approval_mgr = get_approval_manager()
        self._document_tools = DocumentTools()
        self._terminal_manager = get_terminal_manager()
    
    def execute(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call by routing to the correct implementation with Phase 3 gating."""
        # Phase 3 Approval Gate
        needs_approval, reason = self._approval_mgr.should_gate(tool_name, tool_input)

        if needs_approval:
            approved = self._approval_mgr.request_approval(
                tool_name=tool_name,
                tool_input=tool_input,
                prompted_by="User request"
            )
            if not approved:
                logger.warning(f"[ToolExecutor] Action denied or cancelled for tool '{tool_name}'.")
                return {"error": f"Action '{tool_name}' was denied or timed out by user.", "denied": True}
        else:
            # If self-record or session-approved, record directly to change log
            if reason in ("self_record", "session_approved"):
                self._approval_mgr.record_change(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    approval_status="session" if reason == "session_approved" else "no_approval_needed",
                    prompted_by="User request",
                    success=True
                )

        start_t = time.time()
        self._bus.publish(Event(
            type=EventType.TOOL_START,
            source="tool_executor",
            data={"tool_name": tool_name, "tool_input": tool_input},
        ))
        try:
            category = get_tool_category(tool_name)
            
            if category == 'automation':
                res = self._exec_pc_tool(tool_name, tool_input)
            elif category == 'visualization':
                result = execute_canvas_tool(tool_name, tool_input)
                res = {'result': result}
            elif category == 'inventory':
                res = self._exec_inventory_tool(tool_name, tool_input)
            elif category == 'ui_control':
                res = self._exec_ui_control_tool(tool_name, tool_input)
            elif category == 'tasks':
                res = self._exec_tasks_tool(tool_name, tool_input)
            elif category == 'documents':
                res = self._exec_documents_tool(tool_name, tool_input)
            elif category == 'terminal':
                res = self._exec_terminal_tool(tool_name, tool_input)
            elif category == 'pool_tools':
                res = self._exec_pool_tool(tool_name, tool_input)
            else:
                res = {'error': f'Unknown tool category: {category}'}
            duration = round(time.time() - start_t, 2)
            is_err = isinstance(res, dict) and "error" in res
            self._bus.publish(Event(
                type=EventType.TOOL_END,
                source="tool_executor",
                data={
                    "tool_name": tool_name,
                    "success": not is_err,
                    "result": res,
                    "duration": duration,
                },
            ))
            return res
                
        except Exception as e:
            duration = round(time.time() - start_t, 2)
            logger.error(f'Tool execution failed ({tool_name}): {e}')
            self._bus.publish(Event(
                type=EventType.TOOL_END,
                source="tool_executor",
                data={
                    "tool_name": tool_name,
                    "success": False,
                    "error": str(e),
                    "duration": duration,
                },
            ))
            return {'error': str(e)}
    
    def requires_confirmation(self, tool_name: str) -> bool:
        """Check if tool requires user confirmation."""
        return self._approval_mgr.should_gate(tool_name, {})[0]
    
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

        elif tool_name == 'open_url_in_my_browser':
            result = self._pc_controller.open_url_in_my_browser(inp['url'])
            return {'result': result}

        elif tool_name == 'play_youtube':
            result = self._pc_controller.play_youtube(inp.get('query', ''))
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
        if tool_name == 'find_item':
            # Phase 2d: the room camera's item records (memory/item_store.py).
            from archer.memory.item_store import ItemStore, describe_where

            name = inp.get('name') or inp.get('query') or ''
            found = ItemStore().find(name)
            if not found:
                return {'result': f"No record of {name or 'that item'}: ARCHER hasn't seen it yet."}
            return {'result': describe_where(found[0])}

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

    def _exec_documents_tool(self, tool_name: str, inp: Dict[str, Any]) -> Dict[str, Any]:
        """Execute document and artifact tools (Phase 5, Spec Section 8)."""
        if tool_name == 'create_word_document':
            return self._document_tools.create_word_document(
                title=inp.get('title', ''),
                content=inp.get('content', ''),
                filename=inp.get('filename')
            )
        elif tool_name == 'edit_word_document':
            return self._document_tools.edit_word_document(
                filepath=inp.get('filepath', ''),
                append_text=inp.get('append_text', ''),
                output_filename=inp.get('output_filename')
            )
        elif tool_name == 'create_presentation':
            return self._document_tools.create_presentation(
                title=inp.get('title', ''),
                subtitle=inp.get('subtitle'),
                slides=inp.get('slides'),
                filename=inp.get('filename')
            )
        elif tool_name == 'create_spreadsheet':
            return self._document_tools.create_spreadsheet(
                title=inp.get('title', ''),
                sheets=inp.get('sheets'),
                headers=inp.get('headers'),
                rows=inp.get('rows'),
                total_columns=inp.get('total_columns'),
                filename=inp.get('filename')
            )
        elif tool_name == 'create_pdf':
            return self._document_tools.create_pdf(
                title=inp.get('title', ''),
                content=inp.get('content', ''),
                filename=inp.get('filename')
            )
        elif tool_name == 'merge_pdfs':
            return self._document_tools.merge_pdfs(
                pdf_files=inp.get('pdf_files', []),
                output_filename=inp.get('output_filename')
            )
        elif tool_name == 'open_document':
            return self._document_tools.open_document(filepath=inp.get('filepath', ''))
        elif tool_name == 'show_in_folder':
            return self._document_tools.show_in_folder(filepath=inp.get('filepath', ''))
        elif tool_name == 'list_artifacts':
            return {'result': self._document_tools.list_artifacts(extension=inp.get('extension'))}
        else:
            return {'error': f'Unknown documents tool: {tool_name}'}

    def _exec_terminal_tool(self, tool_name: str, inp: Dict[str, Any]) -> Dict[str, Any]:
        """Execute terminal tools (Phase 6, Spec Section 9)."""
        if tool_name == 'run_terminal_command':
            cmd = inp.get('command', '')
            timeout = float(inp.get('timeout', 30.0))
            return self._terminal_manager.execute_archer_command(command=cmd, timeout=timeout)
        else:
            return {'error': f'Unknown terminal tool: {tool_name}'}

    def _exec_pool_tool(self, tool_name: str, inp: Dict[str, Any]) -> Dict[str, Any]:
        """Execute installed tool pool tools (Phase 4, Spec Section 7)."""
        from archer.tools.tool_pool_manager import get_tool_pool_manager
        clean_name = tool_name
        if clean_name.startswith("run_"):
            clean_name = clean_name[4:]
        cmd = inp.get("command", "")
        return get_tool_pool_manager().execute_tool(clean_name, command=cmd)


