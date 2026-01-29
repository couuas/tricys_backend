# Tricys Backend 需求分析 (Requirement Analysis)

## 1. 项目背景 (Background)
Tricys (TRitium Integrated CYcle Simulation) 是一个基于 Python 和 OpenModelica 的高性能氚循环仿真框架。目前，Tricys 主要以命令行接口 (CLI) 的形式提供服务，具备强大的参数扫描、联合仿真、敏感性分析及 HDF5 数据流处理能力。

为了提升用户体验，扩展应用场景（如 Web 端远程调用、或构建更现代化的 Electron/Tauri 桌面客户端），需要构建一个 **Backend Wrapper (后端中间层)**。该层将屏蔽底层 CLI/Python 调用的复杂性，向外暴露统一、标准化的 RESTful/WebSocket API。

## 2. 核心目标 (Core Objectives)
1.  **能力服务化**: 将 Tricys 现有的 `config.json` 驱动的仿真能力转化为 HTTP 服务。
2.  **前后端分离**: 解耦计算核心与用户界面，支持 Web、桌面等多端接入。
3.  **全功能覆盖**: 100% 覆盖现有 CLI 能力（Basic Simulation, Analysis, Enhanced Mode, HDF5 Visualize, Archive）。
4.  **实时交互**: 提供传统 CLI 难以具备的实时日志流监控、进度反馈和任务中断控制。

## 3. 面向用户 (Target Audience)
*   **Tricys UI 开发者**: 需要一个稳定、文档清晰的 API 来构建前端界面。
*   **科研人员**: 未来可能通过 Web 门户提交远程计算任务。
*   **系统集成商**: 将 Tricys 作为一个计算节点集成到更大的核聚变仿真网络中。

## 4. 功能性需求 (Functional Requirements)

### 4.1 仿真任务管理 (Simulation Management)
*   **FR-01 任务提交**: 接收标准 JSON 配置对象，校验后触发 `tricys` 仿真核心。
*   **FR-02 任务控制**: 支持查询任务状态（Queueing, Running, Completed, Failed）、支持在运行中强制终止任务。
*   **FR-03 模式支持**: 必须支持 `--enhanced` (编译一次运行多次) 和 `--turbo` 模式的 API 参数开关。

### 4.2 实时监控 (Real-time Monitoring)
*   **FR-04 日志流**: 提供 WebSocket 接口，实时推送底层 Python/OpenModelica 的 stdout/stderr 日志。
*   **FR-05 进度反馈**: 实时推送当前仿真进度（如：当前是第几个 Case，总共多少 Case）。

### 4.3 数据与结果 (Data & Results)
*   **FR-06 结果获取**: 任务完成后，提供 API 获取结果文件信息（路径、大小、类型）。
*   **FR-07 数据可视化服务**: 提供接口直接查询 HDF5 中的时序数据或统计指标（用于前端绘图），**支持按需切片读取 (Data Slicing)**，减少前端解析大文件的压力。
*   **FR-08 归档管理**: 暴露 `archive` 和 `unarchive` 功能，支持上传/下载归档包。

### 4.4 配置管理 (Configuration)
*   **FR-09 默认配置获取**: 获取当前版本的标准配置模板。
*   **FR-10 配置校验**: 在提交任务前对配置进行格式和逻辑校验（Pre-flight Validation）。

## 5. 非功能性需求 (Non-Functional Requirements)

### 5.1 并发与隔离 (Concurrency & Isolation)
*   **NFR-01 进程隔离**: 后端 API 服务不能因仿真任务崩溃而崩溃。仿真必须在独立的子进程或 Worker 中运行。
*   **NFR-02 任务排队**: 考虑到单机 OpenModelica 资源的限制，需实现简单的 FIFO 任务队列，避免过多重任务同时压垮 CPU。
*   **NFR-03 进程持久化 (Persistence)**: 后端重启后，应能恢复或正确接管正在运行的仿真进程（或妥善终止孤儿进程），避免状态不一致。

### 5.2 性能与资源 (Performance & Resource)
*   **NFR-04 低延迟响应**: API 接口响应时间应 < 100ms（不包含长耗时的计算本身）。
*   **NFR-05 大文件传输**: 优化大文件（HDF5, ZIP）的上传下载性能，支持断点续传或流式传输（可选）。
*   **NFR-06 资源生命周期**: 实现自动清理策略，定期清理旧任务的临时文件，防止磁盘占满。

### 5.3 兼容性 (Compatibility)
*   **NFR-05 跨平台**: 必须在 Windows（当前主开发环境）上稳定运行，兼容 Linux/Docker 部署。
*   **NFR-06 无侵入**: 尽量不修改 `tricys` 现有的 `simulation/` 核心代码，而是通过 Wrapper 方式调用。

## 6. 风险评估 (Risk Assessment)
*   **风险 1**: Windows 下 OpenModelica 进程管理复杂，强制杀死进程可能导致 `.lock` 文件残留或 OMC 服务挂死。
*   **对策**: 实现健壮的 `cleanup` 机制，在启动前和结束后清理环境。
*   **风险 2**: 实时日志量过大导致 WebSocket 阻塞。
*   **对策**: 实现日志采样或缓冲机制。
*   **风险 3**: 多用户并发写文件冲突。
*   **对策**: 为每个任务分配唯一的 UUID Workspace，严格隔离文件系统读写。

## 7. 结论
构建 Backend Wrapper 是 Tricys 现代化的必经之路。核心难点在于对底层长运行进程的稳健控制和实时状态反馈。建议采用 **FastAPI + 异步任务队列** 的架构模式进行实现。
