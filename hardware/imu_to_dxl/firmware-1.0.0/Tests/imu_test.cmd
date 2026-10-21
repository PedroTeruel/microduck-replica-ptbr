@echo off
setlocal
cd /d "%~dp0.."
if not exist Build\Tests\imu mkdir Build\Tests\imu
gcc -std=c11 -Wall -Wextra -Werror -O0 -g -D_CRT_SECURE_NO_WARNINGS -D__weak= -I Tests\imu_board -I Core\Inc -I Drivers\LSM6DSV16X Tests\imu_test.c Core\Src\imu.c Drivers\LSM6DSV16X\lsm6dsv16x_reg.c -o Build\Tests\imu\imu_test.exe
if errorlevel 1 exit /b 1
Build\Tests\imu\imu_test.exe
exit /b %errorlevel%
