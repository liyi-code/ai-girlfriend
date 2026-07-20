@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   小念 AI 女友 —— 启动器
echo   首次运行需联网（创建环境 + 安装依赖，约几分钟）
echo ============================================================
echo.

:::: 0) 前置检查：本机必须已安装 Python 3.10~3.13 并加入 PATH
where python >nul 2>&1
if errorlevel 1 (
    echo [错误] 没找到 python。请先到 https://www.python.org 下载安装 Python 3.11，
    echo        安装时务必勾选 “Add python.exe to PATH”，装完重新运行本脚本。
    pause
    exit /b 1
)
python -c "import sys; v=sys.version_info; sys.exit(0 if (3,10)<=v[:2]<=(3,13) else 1)" 2>nul
if errorlevel 1 (
    echo [错误] 检测到 Python 版本不在 3.10~3.13 区间（太新或太旧）。
    echo        请安装 Python 3.11（推荐）：https://www.python.org/downloads/release/python-3119/
    echo        安装时勾选 “Add python.exe to PATH”。
    pause
    exit /b 1
)
python -c "import sys; print('检测到 Python', sys.version.split()[0], '（符合要求）')"

:::: 1) 没有虚拟环境就创建（用本机 Python 3.11 建一个干净 venv）
if not exist "venv\Scripts\python.exe" (
    echo.
    echo 首次运行：正在创建虚拟环境 venv ...
    python -m venv venv
    if errorlevel 1 (
        echo 创建 venv 失败：请确认 Python 3.11 已正确安装并加入 PATH。
        pause
        exit /b 1
    )
)

:::: 2) 安装/补齐依赖（已装的包会自动跳过，不会重复下载）
echo.
echo 正在检查并安装依赖（已满足的会显示 already satisfied，请稍候）...
venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>&1
venv\Scripts\python.exe -m pip install -r requirements.txt --exists-action i
if errorlevel 1 (
    echo [警告] 依赖安装失败（可能是没联网或网络慢）。请联网后重跑本脚本。
    pause
    exit /b 1
)

:::: 3) 没有 .env 就从模板生成一份，提醒用户填写
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

:::: 3.5) 语音输入（本地 ASR）模型：若已开启且模型缺失，自动从国内镜像拉取（断点续传）。
::::        失败也不阻塞启动，只是离线语音输入暂不可用。
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

:::: 4) 提醒填写对话密钥（未填也能启动，但无法聊天）
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
