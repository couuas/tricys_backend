# Tricys Backend 实施阶段规划 (Implementation Stages)

为了稳健地构建 Tricys Backend，我们将开发过程划分为三个阶段。每个阶段都有明确的目标、交付物和验收测试标准。

## 阶段 1: 核心最小可行性产品 (Stage 1: Core Execution MVP)
**目标**: 建立基础架构，实现通过 API 提交配置并运行仿真，支持基本的轮询查状态。重点解决子进程管理和基本的并发队列。

### 1.1 开发任务
*   [x] **脚手架**: 初始化 FastAPI 项目结构，配置 Poetry/Pip 依赖。
*   [x] **数据库**: 集成 SQLite + SQLModel，设计 `Task` 表。
*   [x] **引擎核心**: 实现 `Service/Engine`，封装 `subprocess.Popen` 调用 Tricys CLI。
*   [x] **API**: 实现 `POST /tasks` (提交) 和 `GET /tasks/{id}` (查询)。
*   [x] **任务队列**: 实现基于 `asyncio.Queue` 的内存级 FIFO 调度器。

### 1.2 测试策略 (Testing)
*   **单元测试 (Unit)**: 测试 Config Pydantic Model 的校验逻辑。
*   **集成测试 (Integration)**:
    *   **Case 1.1**: 提交一个标准的 `simulation` 任务，断言返回 PENDING 状态。
    *   **Case 1.2**: 轮询查询状态，断言状态流转：PENDING -> RUNNING -> COMPLETED。
    *   **Case 1.3**: 验证 `workspaces` 目录下是否生成了结果文件。

---

## 阶段 2: 实时可观测性 (Stage 2: Real-time Observability)
**目标**: 如果第一阶段是"黑盒"，本阶段就是"让它透明"。实现 WebSocket 实时日志流和进度条，以及任务终止功能。解决长连接和日志管道的性能问题。

### 2.1 开发任务
*   [x] **WebSocket**: 实现 `ConnectionManager`，支持多客户端订阅同一 Task。
*   [x] **日志管道**: 改造引擎核心，使用独立线程读取 subprocess 的 stdout/stderr，并写入 `asyncio.Queue` 进行广播。
*   [x] **进度解析**: 编写正则表达式解析器，从日志流中提取进度信息（如 `Job 5/100`）。
*   [x] **控制接口**: 实现 `POST /tasks/{id}/stop`，包含 `terminate()` 和 `kill()` 兜底逻辑。
*   [x] **持久化**: 增加 PID 记录和进程恢复/清理逻辑。

### 2.2 测试策略 (Testing)
*   **单元测试 (Unit)**: 测试日志解析正则对各种边界情况的匹配能力。
*   **端到端测试 (E2E)**:
    *   **Case 2.1**: 使用 Python `websockets` 库模拟客户端，断言能收到连续的 Log Frame。
    *   **Case 2.2**: 提交长任务（如 sleep 10s），在第 2s 发送 Stop 请求，断言状态变为 STOPPED 且进程确实消失。
    *   **Case 2.3**: 模拟 Backend 崩溃重启，验证"僵尸任务"是否被标记为 FAILED。

---

## 阶段 3: 高级数据服务与加固 (Stage 3: Data Services & Robustness)
**目标**: 提升后端作为"服务"的价值，提供 HDF5 数据切片能力，减少前端负担；完善工程化细节（清理、归档）。

### 3.1 开发任务
*   [x] **HDF5 切片**: 实现 `HDF5ReaderService` 服务，利用 `pandas.read_hdf` 的 `where` 子句或切片功能读取局部数据。
*   [x] **数据 API**: 实现 `POST /tasks/{id}/results/query`。
*   [x] **预检机制**: 引入 Config JSON Schema 校验。
*   [x] **生命周期**: 实现 `CleanupService` 后台任务，通过 `APScheduler` 或简单的定时循环清理旧文件。
*   [x] **归档**: 实现 Zip 打包下载接口。

### 3.2 测试策略 (Testing)
*   **性能测试 (Performance)**:
    *   **Case 3.1**: 对 1GB 大小的 HDF5 文件进行切片查询，断言 API 响应时间 < 200ms。
*   **集成测试 (Integration)**:
    *   **Case 3.2**: 提交包含无效字段的 Config，断言 API 返回 422 错误。
    *   **Case 3.3**: 手动修改文件时间模拟过期，触发清理任务，断言文件被删除但 DB 记录保留。

---

## 阶段 4: 其他 (Other: Spec Compliance & Ancillary Features)
**目标**: 补全规格说明书中定义的辅助功能，确保与 `interface.md` 的 100% 兼容性。

### 4.1 开发任务
*   [x] **删除 API**: 实现 `DELETE /tasks/{id}`，支持可选的 `cleanup_files=true` 参数以物理删除工作区。
*   [x] **健康检查**: 实现 `GET /health` 端点，返回系统状态和版本。
*   [x] **配置模板**: 实现 `GET /config/template`，返回标准配置 JSON 供前端初始化。
*   [x] **多 Job 查询**: 升级查询 API，支持 `job_ids` 列表参数（如 `[1, 5, 10]`），兼容旧版 `job_id`。
*   [x] **历史记录查询**: 升级 `GET /tasks` 端点，支持 `status` 过滤及 `limit` 和 `offset` 分页参数。

### 4.2 测试策略 (Testing)
*   **集成测试 (Integration)** - 详见 `tests/integration_test_other.py`:
    *   **Case 4.1**: `test_delete_task` - 验证 DB 删除逻辑，并测试 `cleanup_files` 对物理文件的影响。
    *   [x] **Case 4.2**: `test_health_and_template` - 验证辅助端点的可访问性和返回格式。
    *   [x] **Case 4.3**: `test_query_multijob_hdf5` - 创建包含多个 Job 的 HDF5/CSV，验证查询 API 能正确过滤出指定的 Job 集合。
    *   [x] **Case 4.4**: `test_task_list_filtering & test_task_list_pagination` - 验证任务列表的 `status` 过滤功能以及 `limit`/`offset` 分页逻辑。

---

## 阶段 5: Copilot Reviewer 稳定性与安全性加固 (Stage 5: Stability & Security Hardening)
**目标**: 基于现有功能进行稳健性增强，重点解决崩溃恢复、磁盘维护、输入安全校验以及测试体系的重构。提升后端作为生产级服务的可靠性。

### 5.1 开发任务
*   [x] **崩溃恢复 (Crash Recovery)**:
    *   在 `main.py` 的 lifespan 中实现 `recover_orphaned_tasks`。
    *   启动时扫描数据库中 `RUNNING` 的任务，若对应 PID 不存在或已被复用，强制标记为 `FAILED`，防止"僵尸任务"。
*   [x] **进度解析 (Log Parsing)**:
    *   增强 `LogReaderThread`，支持从标准输出中正则提取进度信息（支持 `Job X/Y`、`XX%`、`[XX%]` 格式）。
    *   在 WebSocket 消息中增加 `progress/total/percent` 字段。
*   [x] **智能清理 (Smart Cleanup)**:
    *   升级 `CleanupService`，仅清理不可变状态 (`COMPLETED`/`FAILED`/`STOPPED`) 的任务文件。
    *   实现空目录递归清理，并严格遵循 7 天保留策略。
*   [x] **统计监控 (Statistics)**:
    *   新增 `GET /tasks/stats/summary` 接口，提供总任务数、状态分布、今日完成数等监控指标。
*   [x] **安全加固 (Security)**:
    *   强化 `ConfigJsonSchema`，增加 `model_name` 的正则校验 (防止特殊字符)。
    *   增加 Path Traversal 防护，禁止文件路径包含 `..`。
*   [x] **测试重构 (Test Refactoring)**:
    *   重构 `test_stage1.py` 等集成测试，引入 `pytest-mock` 模拟 subprocess，消除对真实 CLI 的依赖，提高测试稳定性。

### 5.2 测试策略 (Testing)
*   **单元测试 (Unit)**:
    *   `TestProgressParsing`: 针对三种不同的日志格式编写正则匹配测试，确保 0-100% 提取准确。
    *   `TestConfigValidation`: 构造恶意 Payload（如路径遍历、超长参数列表），验证 Pydantic 校验器是否抛出异常。
*   **集成测试 (Integration)** - 详见 `tests/test_stage5.py`:
    *   **Case 5.1**: `test_orphaned_task_recovery` - 手动插入无效 PID 的 RUNNING 记录，模拟服务重启，断言状态被修正为 FAILED。
    *   **Case 5.2**: `test_cleanup_only_terminal_states` - 创建 RUNNING 和 COMPLETED 两个过期任务，验证清理逻辑只删除了已完成的任务文件。
    *   **Case 5.3**: `test_statistics_summary` - 批量插入不同状态的任务，验证统计接口返回的计数是否准确。
*   **手动验证 (Manual)** - 使用 `tests/manual_test_stage5.html`:
    *   **Dashboard**: 打开 HTML，观察"系统统计"面板数据是否正常加载。
    *   **Progress UI**: 提交一个模拟输出进度的任务，观察进度条是否随 WebSocket 消息实时滚动。
    *   **Security Check**: 点击"路径遍历攻击"按钮，确认后端返回 422 错误而非 500 崩溃。

## 阶段 6: 结果管理与流式传输 (Stage 6: Result Management & Enhanced Features)
**目标**: 提供便捷的结果获取渠道，支持 HDF5 文件浏览、下载及摘要查询，并通过流式传输优化大文件处理体验。

### 6.1 开发任务
*   [x] **结果摘要**: 实现 `GET /tasks/{id}/result_summary`，返回 HDF5 关键元数据（如 Metrics Table）。
*   [x] **文件浏览**: 实现 `GET /tasks/{id}/files`，递归列出工作区文件结构。
*   [x] **文件下载**: 升级文件下载接口，支持 `Range` 请求头，实现断点续传和大文件流式传输。
*   [x] **手动测试页面**: 更新 `manual_test_stage6.html`，集成结果浏览和下载功能。

### 6.2 测试策略
*   **集成测试 (Integration)** - 详见 `tests/test_stage6.py`:
    *   **Case 6.1**: `test_list_result_files` - 验证文件列表的递归结构和元数据（大小、修改时间）。
    *   **Case 6.2**: `test_download_file_stream` - 通过 `StreamingResponse` 下载大文件，验证内存占用可控。
    *   **Case 6.3**: `test_get_result_summary` - 验证能正确从 HDF5 `/summary` 表中读取指标数据。


---

## 阶段 7: 架构升级与生态集成 (Stage 7: Architecture Refinement & Ecosystem Integration)
**目标**: 实施 "Thin Backend" 架构重构，通过 CLI 子命令解耦模型解析逻辑，并提供标准 BI 数据源接口以支持高级可视化。

### 7.1 开发任务
*   [x] **CLI 扩展**: 实现 `tricys parse` 子命令，支持导出 Modelica 模型参数 Schema。
*   [x] **模型服务**: 在 Backend 实现 `ModelService`，通过 `subprocess` 调用 `tricys parse` 并缓存结果。
*   [x] **API 升级**: 实现 `POST /models/parse` 接口。
*   [x] **BI 集成**: 实现 `POST /tasks/{id}/results/query_bi`，支持 Grafana JSON Datasource 协议。
*   [x] **架构加固**: 移除 Backend 中直接引用 `tricys.core` 的代码，确保全链路通过 CLI 交互。

### 7.2 测试策略
*   **集成测试 (Integration)** - 新增 `tests/test_stage7.py`:
    *   [x] **Case 7.1**: `test_model_parsing` - 上传示例 `.mo` 文件，断言返回的 JSON Schema 字段完整性。
    *   [x] **Case 7.2**: `test_bi_query` - 模拟 Grafana 查询请求，断言返回的时序数据格式符合预期。
*   **手动验证 (Manual)**:
    *   **Grafana**: 搭建本地 Grafana，配置 JSON Datasource 指向 Backend，验证能否画出折线图。(说明：此部分功能已实现，但集成验证推迟到后续阶段)
