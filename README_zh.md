# TRICYS Backend (后端服务)

> **用于管理和执行氚循环集成仿真 (TRICYS) 的高性能 RESTful API 服务**

TRICYS Backend 为任务调度、实时监控和高级数据检索提供了一套稳健的异步接口基础架构，作为连接 TRICYS 核心仿真引擎与前端可视化界面的桥梁。

## 核心特性

- **任务全生命周期管理**: 支持异步任务提交、基于 FIFO 队列的自动调度以及执行状态追踪。
- **实时可观测性**: 通过 WebSocket 提供实时的日志流推送和执行进度更新，实现前端动态展示。
- **高级数据服务**: 针对多 Job 扫参仿真，提供高性能的 HDF5 数据切片与查询接口。
- **健壮性与工程化**: 内置故障恢复机制、工作区自动清理策略以及结果归档管理。
- **规范化接口**: 提供完全符合规范的 RESTful 端点，确保与前端的无缝集成。

## 技术栈

- **框架**: [FastAPI](https://fastapi.tiangolo.com/) (异步、高性能)
- **数据库**: 使用 [SQLModel](https://sqlmodel.tiangolo.com/) (SQLite) 进行元数据持久化。
- **调度**: 采用内置的 `asyncio.Queue` 实现轻量级的高效任务编排。
- **核心**: 直接集成 `tricys` 命令行核心引擎。

## 安装指南

```bash
# 克隆仓库
git clone https://github.com/asipp-neutronics/tricys_backend.git

# 安装依赖
pip install -r requirements.txt
```

## 快速开始

1. **启动服务端**:
   ```bash
   python main.py
   # 或者使用 uvicorn 启动
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

2. **访问 API 文档**:
   在浏览器中访问 `http://localhost:8000/docs` 即可查看并测试交互式 Swagger UI。

3. **健康检查**:
   ```bash
   curl http://localhost:8000/api/v1/health
   ```

## 项目结构

- `api/`: API 路由定义与交互逻辑。
- `core/`: 全局配置与系统生命周期事件。
- `models/`: 数据库 Schema 与 Pydantic 数据校验模型。
- `services/`: 核心业务逻辑 (引擎管理、队列调度、文件管理、HDF5 读取)。
- `utils/`: 通用工具类 (WebSocket 连接管理器、逻辑统一日志记录器)。

## 许可证

本项目采用 [APACHE 2.0](LICENSE) 许可证。
