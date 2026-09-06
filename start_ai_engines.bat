@echo off
echo Starting Akira Engine (Llama.cpp Multi-LoRA Single Server)
echo ===================================================

cd /d "%~dp0"

REM 1. Locate llama-server.exe in PATH, llama_cpp\, or Akira\
set "LLAMA_BIN="
where llama-server.exe >nul 2>nul
if %errorlevel% equ 0 set "LLAMA_BIN=llama-server.exe"
if not defined LLAMA_BIN if exist "llama_cpp\llama-server.exe" set "LLAMA_BIN=llama_cpp\llama-server.exe"
if not defined LLAMA_BIN if exist "Akira\llama-server.exe" set "LLAMA_BIN=Akira\llama-server.exe"

if not defined LLAMA_BIN goto :err_no_binary

REM 2. Locate model directory (Akira\ folder or current directory)
set "MODEL_DIR="
if exist "Akira\Llama-3-8B-Instruct.Q4_K_M.gguf" set "MODEL_DIR=Akira\"
if not defined MODEL_DIR if exist "Llama-3-8B-Instruct.Q4_K_M.gguf" set "MODEL_DIR="
if not defined MODEL_DIR goto :err_no_model

echo Launching Akira Unified Engine (Port 8081) with Guard + API + Mech LoRAs...
echo Binary: %LLAMA_BIN%
echo Model directory: %MODEL_DIR%
echo.

start "Akira Unified Engine" cmd /k "%LLAMA_BIN% --model %MODEL_DIR%Llama-3-8B-Instruct.Q4_K_M.gguf --lora %MODEL_DIR%akira_guard.gguf --lora %MODEL_DIR%akira_api.gguf --lora %MODEL_DIR%akira_mech.gguf --lora-init-without-apply --no-repack -c 2048 -np 1 --port 8081"

echo Engine is booting! Keep the window open while Akira is running.
echo.
echo Once you see "model loaded" / "listening on http://127.0.0.1:8081"
echo run:  python verify_servant_tier.py
exit /b 0

:err_no_binary
echo.
echo [ERROR] 'llama-server.exe' was not found on your system!
echo.
echo How to install llama-server:
echo   Option 1 - Install with winget (run in terminal):
echo       winget install ggml.llamacpp
echo.
echo   Option 2 - Download Windows binary zip from:
echo       https://github.com/ggerganov/llama.cpp/releases
echo       and place 'llama-server.exe' into this project folder.
echo.
echo NOTE: You do NOT need llama-server to run Akira!
echo Akira works with Cloud AI providers (Groq, Gemini, Claude).
echo You can run Akira immediately in text mode:
echo       python text_mode.py
echo.
exit /b 1

:err_no_model
echo.
echo [ERROR] Base model Llama-3-8B-Instruct.Q4_K_M.gguf not found in Akira\ or current folder!
echo.
exit /b 1
