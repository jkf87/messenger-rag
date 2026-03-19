@echo off
chcp 65001 > nul
echo =============================================
echo  충북소통메신저 쪽지 전체 백업
echo  받은쪽지 + 보낸쪽지 전체 수집
echo =============================================
C:\Python314\python.exe -u "%~dp0backup_notes.py"
pause
