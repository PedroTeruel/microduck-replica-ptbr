@echo off
setlocal
cd /d "%~dp0.."
if not exist Build\host-tests mkdir Build\host-tests
gcc -std=c11 -Wall -Wextra -Werror -O0 -g -I Core\Inc -o Build\host-tests\control_table_test.exe Tests\control_table_test.c Core\Src\control_table.c
if errorlevel 1 exit /b 1
Build\host-tests\control_table_test.exe
exit /b %errorlevel%
