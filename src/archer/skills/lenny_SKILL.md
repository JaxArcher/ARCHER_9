---
name: lenny
description: Dedicated Windows workstation (ARCHER's own PC) for running applications, creating Office documents, and web browsing undisturbed.
category: lenny
---

### lenny_status
Check the current connection status, active task, and state of LENNY (ARCHER's dedicated PC).

### lenny_open_app
Launch an application or program on LENNY (e.g. 'notepad', 'word', 'excel', 'chrome', or any installed Windows application).
**Parameters:**
- name: The application name or executable to launch (e.g. 'notepad', 'winword', 'excel', 'chrome').

### lenny_word_document
Create a Word document (.docx) using native Microsoft Office on LENNY, format headings and paragraphs, and save it to artifacts.
**Parameters:**
- title: The title/heading of the Word document.
- content: The content, paragraphs, or bullet points to write in the document.
- filename: (optional) The target filename (e.g. 'shopping_list.docx').

### lenny_excel_sheet
Create an Excel spreadsheet (.xlsx) using native Microsoft Office on LENNY with structured rows and columns.
**Parameters:**
- sheet_name: The name of the worksheet tab.
- rows: The data rows as a table or list of rows to write into the spreadsheet.
- filename: (optional) The target filename (e.g. 'budget.xlsx').

### lenny_list_controls
Inspect and list visible UI Automation controls (buttons, inputs, menus) in the active or specified window on LENNY.
**Parameters:**
- window_title: (optional) The partial title of the window to inspect. Omit to inspect the currently active window.

### lenny_invoke_control
Click, invoke, or activate a UI element on LENNY by its name, label, or automation ID using UI Automation.
**Parameters:**
- identifier: The name, text, or automation ID of the control to invoke.
- window_title: (optional) The partial title of the window containing the control.

### lenny_type_text
Type a sequence of text characters on LENNY at the current keyboard focus.
**Parameters:**
- text: The text string to type.

### lenny_press_keys
Press a keyboard shortcut, key combination, or special key on LENNY (e.g. 'enter', 'tab', 'backspace', 'ctrl+s', 'esc').
**Parameters:**
- keys: The key or key combination to press (e.g. 'enter', 'ctrl+s', 'tab').

### lenny_look_and_click
Use local vision (VLM) on Main PC to find a button, icon, or element visually on LENNY's screen and click or double-click it.
**Parameters:**
- description: Visual description of the target element to click (e.g. 'Save button', 'blue submit button', 'Notepad text area').
- action: (optional) Action to perform ('click' or 'doubleclick'). Defaults to 'click'.

### lenny_describe_screen
Capture a screenshot of LENNY's desktop and return a plain-language description of what is currently open and visible.
**Parameters:**
- focus_area: (optional) Specific application or area of the screen to focus the description on.
