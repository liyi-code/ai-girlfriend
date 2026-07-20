@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   小念 AI 女友 —— 启动器
echo   首次运行需联网（创建环境 + 安装依赖，约几分钟）
echo ============================================================
echo.

::::: 0) 找一个可用的 Python 3.10~3.13（依赖 numpy/av/faster-whisper 在 3.14 上无预编译包，会卡编译）
:::::    优先用 Windows 的 py 启动器按版本挑选；即使系统默认是 3.14，也能自动用 3.11 建环境。
:::::    注意：py 启动器对“未安装的版本”会返回 exit 0 但 stdout 为空，故以“能打印出版本号”为准。
set "PYCMD="
where py >nul 2>&1
if %errorlevel%==0 (
    for %%V in (3.13 3.12 3.11 3.10) do (
        if not defined PYCMD (
            for /f "tokens=*" %%O in ('py -%%V -c "import sys; print('%%V')" 2^>nul') do (
                if "%%O"=="%%V" set "PYCMD=py -%%V"
            )
        )
    )
)
::::: 回退：若没有 py 启动器，但系统默认 python 正好在 3.10~3.13 也可用
if not defined PYCMD (
    python -c "import sys; v=sys.version_info; exit(0 if (3,10)<=v[:2]<=(3,13) else 1)" >nul 2>&1 && set "PYCMD=python"
)
if not defined PYCMD (
    echo [错误] 没找到可用的 Python 3.10~3.13。
    echo.
    echo   你当前装的 Python 3.14 太新：项目依赖（numpy / av / faster-whisper 等）
    echo   在 3.14 上没有官方预编译包，pip 会尝试本地源码编译而卡死或报错。
    echo.
    echo   解决办法：安装 Python 3.11（无需卸载 3.14，两者可共存）：
    echo     https://www.python.org/downloads/release/python-3119/
    echo   安装时勾选 “Add python.exe to PATH”，装完重新运行本脚本即可。
    echo   本脚本会自动优先使用 3.11 来创建环境。
    pause
    exit /b 1
)
echo 将使用 %PYCMD% 创建/运行环境

::::: 1) 没有虚拟环境就创建（用上面挑好的 %PYCMD% 建一个干净 venv）
if not exist "venv\Scripts\python.exe" (
    echo.
    echo 首次运行：正在用 %PYCMD% 创建虚拟环境 venv ...
    %PYCMD% -m venv venv
    if errorlevel 1 (
        echo 创建 venv 失败：请确认 Python 3.10~3.13 已正确安装。
        pause
        exit /b 1
    )
)

::::: 2) 安装/补齐依赖（已装的包会自动跳过，不会重复下载）
echo.
echo 正在检查并安装依赖（已满足的会显示 already satisfied，请稍候）...
venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>&1
venv\Scripts\python.exe -m pip install -r requirements.txt --exists-action i
if errorlevel 1 (
    echo [警告] 依赖安装失败（可能是没联网或网络慢）。请联网后重跑本脚本。
    pause
    exit /b 1
)

::::: 3) 没有 .env 就从模板生成一份，提醒用户填写
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo.
        echo 已根据 .env.example 生成 .env，请打开填写你的 OPENAI_API_KEY 等配置，然后重新运行本脚本。
    ) else (
        echo 未找到 .env 与 .env.example，请手动创建 .env 配置文件。
    )
    pause
    exit /b 0
)

::::: 3.5) 语音输入（本地 ASR）模型：若已开启且模型缺失，自动从国内镜像拉取（断点续传）。
:::::        失败也不阻塞启动，只是离线语音输入暂不可用。
if exist ".env" (
    findstr /i /c:"VOICE_INPUT_ENABLED=false" .env >nul
    if not errorlevel 1 goto :skip_asr
    if not exist "models\faster-whisper-small\model.bin" (
        echo.
        echo 正在自动下载语音识别模型（首次需联网，可断点续传，缺失不影响文字聊天）...
        venv\Scripts\python.exe download_model.py
    )
)
:skip_asr

::::: 4) 提醒填写对话密钥（未填也能启动，但无法聊天）
findstr /i /c:"OPENAI_API_KEY=" .env >nul
if not errorlevel 1 (
    findstr /r /c:"^OPENAI_API_KEY= *$" .env >nul
    if not errorlevel 1 (
        echo.
        echo [提示] 你的 .env 里 OPENAI_API_KEY 还是空的，小念启动后无法聊天。
        echo        请用记事本打开 .env，填好 OPENAI_API_KEY（DeepSeek / 任意兼容 OpenAI 的服务商均可），
        echo        然后重新运行本脚本即可。
        echo        （想先看看界面也可以直接回车继续，但对话会提示缺密钥）
        pause
    )
)

echo.
echo 正在启动小念（AI 女友）...
venv\Scripts\python.exe -m src.main
pause
