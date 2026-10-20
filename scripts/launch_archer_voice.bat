@echo off
:: ARCHER Voice Launcher Task Wrapper
:: Invoked by the ArcherLaunchOnVoice scheduled task.
:: Runs launch_check.py in Col's session.

title ARCHER Voice Launch Check

cd /d "%~dp0.."
"%~dp0..\.venv\Scripts\python.exe" "%~dp0launch_check.py" %*
