@echo off
call .venv\Scripts\activate
pip install -e .[dev]
call deactivate