@echo off
chcp 65001 > nul
echo =============================================
echo  충북소통메신저 백업 도구
echo  채팅창을 열면 자동으로 백업됩니다
echo  종료: Ctrl+C
echo =============================================
C:\Python314\python.exe "%~dp0backup.py"
pause
