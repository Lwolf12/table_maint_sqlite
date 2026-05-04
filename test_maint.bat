@echo off
setlocal
cd /d "%~dp0"

REM Omit -d/-t so the last database path and table name are restored from
REM %%APPDATA%%\table_maint\db_history.json (after a successful table load).
REM Pass a record id as the first argument to open the list scrolled to that row.

if "%~1"=="" (
    python -m table_maint
) else (
    python -m table_maint -r "%~1"
)

endlocal
exit /b %ERRORLEVEL%
