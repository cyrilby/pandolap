@echo off
call .venv\Scripts\activate

REM Install necessary tools and build package
py -m pip install --upgrade build
py -m build

REM Upload package to PyPI [WIP as of 26-08-2026: Disabled]
REM py -m pip install --upgrade twine
REM py -m twine upload pypi dist/*

call deactivate