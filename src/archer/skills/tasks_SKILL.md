---
name: Tasks & Habits
description: Managing to-do items and daily/weekly habit streaks, available to every agent persona (not just the core Assistant).
category: tasks
---

### add_task
Add a new task/to-do item. Use this when the user asks to be reminded of
something, add something to their list, or track something they need to
do — for example "remind me to call the bank tomorrow" or "add pick up
dry cleaning to my list".
**Parameters:**
- title: The task description.
- due_date: (optional) When it's due, as an ISO date or datetime (e.g. '2026-09-18').
- source: (optional) Which agent/persona is adding this (e.g. 'assistant', 'therapist', 'trainer'). Defaults to 'user' if not specified.

### list_tasks
List current tasks, optionally filtered by status. Use this when the user
asks what's on their list, what they need to do, or what's still pending.
**Parameters:**
- status: (optional) Filter by 'pending' or 'completed'. Omit to get all tasks.

### complete_task
Mark a task as completed. Use this when the user says they finished or
did something that was tracked as a task.
**Parameters:**
- task_id: The numeric id of the task to complete (integer).

### delete_task
Permanently remove a task (not the same as completing it — use this only
when the user wants it gone entirely, e.g. it's no longer relevant).
**Parameters:**
- task_id: The numeric id of the task to delete (integer).

### add_habit
Start tracking a new habit/streak. Use this when the user wants to build
or track a recurring habit — for example "help me track drinking water
every day" or "I want to track a weekly habit of calling my mom".
**Parameters:**
- name: The habit's name (e.g. "drink water", "call mom").
- frequency: (optional) 'daily' or 'weekly'. Defaults to 'daily'.

### list_habits
List all tracked habits and their current streaks. Use this when the user
asks about their habits, streaks, or how they're doing on something
they're tracking.

### complete_habit
Mark a habit as done for today (or this week, for weekly habits). Use
this when the user says they did a tracked habit — e.g. "I drank my
water" or "logged my workout". If it was already marked done for the
current period, say so rather than claiming the streak went up again.
**Parameters:**
- name: The habit's name, matching what it was created with.

### delete_habit
Stop tracking a habit entirely (removes its streak history). Use this
only when the user explicitly wants to stop tracking something.
**Parameters:**
- name: The habit's name to remove.
