#!/bin/bash

# Product Catalog Monitor startup script

echo "=================================="
echo "  Product Catalog Monitor"
echo "=================================="
echo ""

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose 未安装，请先安装 Docker Compose"
    exit 1
fi

echo "✅ Docker 环境检查通过"
echo ""

# 停止已有容器
echo "🛑 停止已有容器..."
docker-compose down

# 启动服务
echo "🚀 启动服务..."
docker-compose up -d

# 等待服务就绪
echo ""
echo "⏳ 等待服务启动（约 30 秒）..."
sleep 10

echo "   [1/3] PostgreSQL 启动中..."
sleep 10

echo "   [2/3] Python API 启动中..."
sleep 5

echo "   [3/3] n8n 启动中..."
sleep 5

# 健康检查
echo ""
echo "🔍 健康检查..."

# 检查 PostgreSQL
if docker exec catalog_monitor_db pg_isready -U postgres &> /dev/null; then
    echo "   ✅ PostgreSQL: 运行正常"
else
    echo "   ❌ PostgreSQL: 启动失败"
fi

# 检查 Python API
if curl -s http://localhost:5000/health &> /dev/null; then
    echo "   ✅ Python API: 运行正常"
else
    echo "   ❌ Python API: 启动失败"
fi

# 检查 n8n
if curl -s http://localhost:5678 &> /dev/null; then
    echo "   ✅ n8n: 运行正常"
else
    echo "   ❌ n8n: 启动失败"
fi

# 显示访问信息
echo ""
echo "=================================="
echo "  🎉 服务启动完成！"
echo "=================================="
echo ""
echo "📊 访问地址："
echo "   • n8n 工作流:  http://localhost:5678"
echo "   • Python API:  http://localhost:5000"
echo "   • PostgreSQL:  localhost:5432"
echo ""
echo "🧪 测试命令："
echo "   curl http://localhost:5000/health"
echo "   curl -X POST http://localhost:5000/scrape -H 'Content-Type: application/json' -d '{\"mode\":\"full\",\"max_products\":10}'"
echo ""
echo "📝 查看日志："
echo "   docker-compose logs -f"
echo ""
echo "🛑 停止服务："
echo "   docker-compose down"
echo ""
echo "=================================="
