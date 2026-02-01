# Tricys Backend 架构设计 (Technical Design)

## 1. 系统架构 (Architecture)

采用典型的分层架构，基于 **FastAPI** 框架构建。

```mermaid
graph TD
    Client[Web / Desktop] -- HTTP/WS --> API[API Layer (FastAPI)]
    
    subgraph "Backend Service"
        API --> Manager[Task Manager Service]
        Manager --> Queue[Task Queue (InMemory / Redis)]
        Manager --> DB[(SQLite DB)]
        
        Manager --> DB[(SQLite DB)]
        
        Manager -- Spawn --> Worker[Subprocess Worker]
    end
    
    subgraph "Tricys Core (CLI)"
        Worker -- "tricys basic/analysis/parse" --> Core[Tricys CLI Entry]
        Core -- stdout/stderr --> LogPipe[Log Capture Pipe]
        Core -- write --> FS[File System (HDF5/Logs)]
    end
    
    LogPipe -- async read --> Manager
    Manager -- push --> API
```

## 2. 技术栈选型 (Tech Stack)

| 组件 | 选型 | 理由 |
| :--- | :--- | :--- |
| **Language** | Python 3.10+ | 与 Tricys 核心同源，易于集成 |
| **Web Framework** | **FastAPI** | 高性能异步，原生 OpenAPI 支持，WebSocket 支持友好 |
| **Database** | **SQLite** (v1.0) | 轻量级，无需额外部署 Server，适合单机应用 |
| **ORM** | **SQLModel** | 结合 Pydantic 和 SQLAlchemy，极大简化代码 |
| **Task Queue** | **asyncio.Queue** | v1.0 采用内存队列简化部署；v2.0 可迁移至 Celery+Redis |
| **Testing** | **Pytest** | 标准 Python 测试框架 |

## 3. 模块设计 (Module Design)

```text
tricys_backend/
├── main.py              # App 入口
├── api/
│   ├── v1/
│   │   ├── endpoints/
│   │   │   ├── simulation.py  # 仿真相关接口
│   │   │   ├── analysis.py    # 分析相关接口
│   │   │   └── archive.py     # 归档接口
├── core/
│   ├── config.py        # 后端配置 (端口, 存储路径等)
│   └── events.py        # 启动/关闭事件
├── models/              # 数据库模型 & Pydantic 模型
│   ├── task.py
│   └── response.py
├── services/
│   ├── engine.py        # 核心：子进程管理、日志捕获
│   ├── file_manager.py  # 文件读写、工作区管理
│   ├── file_browser.py  # 文件浏览与流式下载服务
│   ├── model_service.py # (New) 调用 `tricys parse` 解析模型
│   └── task_queue.py    # 简单的 FIFO 调度器
└── utils/
    ├── websocket.py     # 连接管理器
    └── logger.py
```

## 4. 数据库设计 (Database Schema)

### Table: `tasks`
用于持久化存储任务元数据。

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | TEXT (UUID) | 主键 |
| `name` | TEXT | 任务名称 (可选) |
| `type` | TEXT | `BASIC` 或 `ANALYSIS` |
| `status` | TEXT | `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `STOPPED` |
| `config_json` | TEXT | 完整的配置 JSON 字符串 |
| `workspace_path` | TEXT | 该任务的工作目录绝对路径 |
| `result_path` | TEXT | 结果文件路径 (如存在) |
| `pid` | INTEGER | 底层仿真进程的 OS PID (用于恢复/终止) |
| `created_at` | DATETIME | 创建时间 |
| `updated_at` | DATETIME | 最后更新时间 |
| `error_msg` | TEXT | 报错信息 (如有) |

## 5. 核心流程设计 (Core Process Design)

### 5.1 启动任务 (Start Simulation)
1.  **API**: 接收 Config，生成 `task_id`，存入 DB 状态 `PENDING`。
2.  **Queue**: 将 `task_id` 放入 `asyncio.Queue`。
3.  **Worker**:
    *   后台死循环监听 Queue。
    *   取出一个 `task_id`。
    *   更新 DB 状态 `RUNNING`，**记录 `pid`**。
    *   **日志持久化**: 使用 `tee` 模式，将 stdout 同时写入 `simulation.log` 和推送到 WebSocket。
    *   **关键**: 开启独立线程/协程实时读取 `process.stdout` 和 `process.stderr`。
    *   将读取到的日志行通过 `WebsocketManager` 广播给订阅了该 `task_id` 的客户端。
    *   等待进程结束。
    *   更新 DB 状态 `COMPLETED` / `FAILED`，清除 `pid`。

### 5.3 故障恢复 (Crash Recovery)
1.  **Server Startup**:
2.  **Scan**: 查询 DB 中所有状态为 `RUNNING` 的任务。
3.  **Check PID**: 检查对应 `pid` 进程是否存在。
    *   若不存在 -> 标记为 `FAILED` (异常退出)。
    *   若存在但非 Tricys 进程 -> 标记为 `FAILED` (PID 复用冲突)。
    *   若存在且为 Tricys 进程 -> 尝试 Re-attach 日志流 (如果支持) 或仅监控其退出状态。


### 5.2 终止任务 (Stop Simulation)
1.  **API**: 接收 Stop 请求。
2.  **Service**: 查找当前 `RUNNING` 的 Worker。
3.  **Action**: 调用 `process.terminate()`。若 5秒未退出，调用 `process.kill()`。
4.  **DB**: 更新状态为 `STOPPED`。

## 6. 接口设计原则
遵循 RESTful 规范，URL 风格如下：
*   `GET /api/v1/tasks` (List)
*   `POST /api/v1/tasks` (Create)
*   `GET /api/v1/tasks/{id}` (Detail)
*   `DELETE /api/v1/tasks/{id}` (Stop/Cancel)
*   `GET /api/v1/tasks/{id}/logs` (History Logs)
*   `WS /ws/tasks/{id}` (Realtime Logs)
*   `POST /api/v1/models/parse` (Model Parsing)

## 7. CLI 集成规范 (CLI Integration Rules)
遵循 **"Thin Backend, Thick CLI"** 原则：
1.  **仿真运行**: 通过 `subprocess.Popen(["tricys", "basic", "-c", ...])` 调用。
2.  **模型解析**: 通过 `subprocess.run(["tricys", "parse", ...])` 调用。
3.  **结果处理**: 优先使用 `tricys` 提供的子命令或标准库读取 HDF5，后端不包含复杂科学计算逻辑。
