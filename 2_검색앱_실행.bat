@echo off
chcp 65001 > nul

:: Claude API 키 설정 (의미론적 검색 활성화)
:: set ANTHROPIC_API_KEY=sk-ant-여기에키입력

C:\Python314\python.exe "%~dp0search_app_win.py"
