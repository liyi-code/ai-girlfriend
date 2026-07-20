@echo off
cd /d "%~dp0"

echo ============================================================
echo   小念 AI 女友 —— 启动器
echo   首次运行需联网（创建环境 + 安装依赖，约几分钟）
echo ============================================================
echo.

:: 0) 选一个可用的 Python（优先 python，回退到 py 启动器）
set "PY=python"
python -c "import sys; v=sys.version_info; sys.exit(0 if (3,10)<=v[:2]<=(3,14) else 1)" >nul 2>&1
if errorlevel 1 (
    set "PY=py -3.11"
)
echo 将使用 %PY% 创建/运行环境

:: 1) 没有虚拟环境就创建
if not exist "venv\Scripts\python.exe" (
    echo.
    echo 首次运行：正在创建虚拟环境 venv ...
    %PY% -m venv venv
    if errorlevel 1 (
        echo 创建 venv 失败：请先安装 Python 3.10~3.14（推荐 3.11），安装时勾选“Add python.exe to PATH”。
        echo 也可安装后重跑本脚本，本脚本会自动优先使用它来创建环境。
        pause
        exit /b 1
    )
)

:: 2) 安装/补齐依赖（已装的包会自动跳过，不会重复下载）
echo.
echo 正在检查并安装依赖（已满足的会显示 already satisfied，请稍候）...
venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>&1
venv\Scripts\python.exe -m pip install -r requirements.txt --exists-action i
if errorlevel 1 (
    echo [警告] 依赖安装失败（可能是没联网或网络慢）。请联网后重跑本脚本。
    pause
    exit /b 1
)

:: 3) 没有 .env 就从模板生成一份，并直接打开让用户输入
if not exist ".env" (
    if exist ".env.txt" (
        echo.
        echo 发现 .env.txt（Windows 记事本自动加了 .txt 后缀），正在重命名为 .env ...
        move /Y ".env.txt" ".env" >nul
    )
    if not exist ".env" (
        if exist ".env.example" (
            copy .env.example .env >nul
        ) else (
            echo 未找到 .env.example，请手动创建 .env 配置文件。
            pause
            exit /b 1
        )
    )
    echo.
    echo 已生成 .env，现在用记事本打开，请填写 OPENAI_API_KEY 后「保存」「关闭」，
    echo 然后回到本窗口按任意键继续（之后重跑本脚本将不再重复此步骤）。
    start /wait "" "%SystemRoot%\system32\notepad.exe" .env
    pause
    exit /b 0
)

:: 3.5) 语音输入（本地 ASR）模型：若已开启且模型缺失，自动从国内镜像拉取（断点续传）。
::      失败也不阻塞启动，只是离线语音输入暂不可用。
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

:: 4) 提醒填写对话密钥（未填也能启动，但无法聊天）
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
