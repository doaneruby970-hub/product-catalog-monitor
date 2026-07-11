@echo off
REM Product Catalog Monitor startup script (Windows)

echo ==================================
echo   Product Catalog Monitor
echo ==================================
echo.

REM 检查 Docker
docker --version >nul 2>&1
if errorlevel 1 (
    echo X Docker 未安装，请先安装 Docker Desktop
    pause
    exit /b 1
)

docker-compose --version >nul 2>&1
if errorlevel 1 (
    echo X Docker Compose 未安装，请先安装 Docker Compose
    pause
    exit /b 1
)

echo V Docker 环境检查通过
echo.

REM 启动项目自有的持久化可视 Chrome
call "%~dp0start-browser.bat"
if errorlevel 1 (
    echo X 项目 Chrome 启动失败
    pause
    exit /b 1
)

REM 停止已有容器
echo [正在停止已有容器...]
docker compose down

REM 启动服务
echo [正在启动服务...]
docker compose up -d

REM 等待服务就绪
echo.
echo [等待服务启动 约 30 秒...]
timeout /t 10 /nobreak >nul
echo    [1/3] PostgreSQL 启动中...
timeout /t 10 /nobreak >nul
echo    [2/3] Python API 启动中...
timeout /t 5 /nobreak >nul
echo    [3/3] n8n 启动中...
timeout /t 5 /nobreak >nul

REM 健康检查
echo.
echo [健康检查...]

docker exec catalog_monitor_db pg_isready -U postgres >nul 2>&1
if errorlevel 1 (
    echo    X PostgreSQL: 启动失败
) else (
    echo    V PostgreSQL: 运行正常
)

curl -s http://localhost:5000/health >nul 2>&1
if errorlevel 1 (
    echo    X Python API: 启动失败
) else (
    echo    V Python API: 运行正常
)

curl -s http://localhost:5678 >nul 2>&1
if errorlevel 1 (
    echo    X n8n: 启动失败
) else (
    echo    V n8n: 运行正常
)

REM 显示访问信息
echo.
echo ==================================
echo   服务启动完成！
echo ==================================
echo.
echo 访问地址：
echo    n8n 工作流:  http://localhost:5678
echo    Python API:  http://localhost:5000
echo    PostgreSQL:  localhost:5432
echo.
echo 测试命令：
echo    curl http://localhost:5000/health
echo.
echo 浏览器：
echo    项目自有 Chrome 使用 browser-profile 持久化目录和 9223 CDP 端口
echo.
echo 查看日志：
echo    docker compose logs -f
echo.
echo 停止服务：
echo    docker compose down
echo.
echo ==================================
pause
