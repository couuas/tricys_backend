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

基于用户体验流程，功能需求分为三个核心阶段：

### 4.1 仿真前：配置与提交 (Pre-simulation Configuration)
*   **FR-01 动态模型解析**: 
    *   后端提供 API 调用 `tricys parse` 子命令，动态解析 Modelica 模型 (`.mo`)。
    *   返回包含参数名、类型、默认值、单位、注释的 JSON Schema，供前端自动生成配置表单。
*   **FR-02 标准化配置提交**: 
    *   接收前端生成的标准 `config.json` 对象。
    *   后端仅做基本的格式校验，核心业务校验下沉至 CLI。
*   **FR-03 模式选择**: 支持在提交时选择 `Basic` / `Analysis` 模式，并开关 `--enhanced` / `--turbo` 选项。

### 4.2 仿真中：实时监控 (In-simulation Monitoring)
*   **FR-04 进程托管与日志管道**: 
    *   后端通过 `subprocess` 启动仿真，并利用 Pipe 实时捕获 stdout/stderr。
    *   **无需** 复杂的日志文件轮询，直接转发流式输出。
*   **FR-05 实时状态推送**: 
    *   通过 WebSocket (`/ws/tasks/{id}`) 实时广播日志行 (Log Frames)。
    *   **进度解析**: 后端根据日志中的特定模式（如 `Job X/Y`）解析进度，并推送结构化进度事件 (Progress Events)。
*   **FR-06 任务控制**: 
    *   支持随时向子进程发送 `SIGTERM`/`SIGKILL` 以终止仿真。

### 4.3 仿真后：结果展示与 BI 集成 (Post-simulation Visualization)
*   **FR-07 HDF5 数据服务**: 
    *   提供 API (`/results/query`) 支持对 HDF5 结果文件进行切片查询 (Slicing)，按需读取特定变量或时间段的数据。
*   **FR-08 BI 工具集成接口**: 
    *   (New) 提供适配 **Grafana JSON Datasource** 或通用 BI 工具的 API 接口。
    *   允许外部 BI 工具直接连接 Backend 作为数据源，进行自定义图表展示。
*   **FR-09 文件管理与归档**: 
    *   支持递归浏览工作区文件结构。
    *   支持大文件 (HDF5) 的流式下载 (Range Request) 和归档打包下载 (`tricys archive` wrapper)。

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
*   **NFR-06 架构约束 (Architectural Constraints)**: 
    *   遵循 **"Thin Backend, Thick CLI"** 原则。
    *   禁止在 Backend 代码中 import 核心仿真包，必须通过 `tricys` CLI 子命令调用。

## 6. 风险评估 (Risk Assessment)
*   **风险 1**: Windows 下 OpenModelica 进程管理复杂，强制杀死进程可能导致 `.lock` 文件残留或 OMC 服务挂死。
*   **对策**: 实现健壮的 `cleanup` 机制，在启动前和结束后清理环境。
*   **风险 2**: 实时日志量过大导致 WebSocket 阻塞。
*   **对策**: 实现日志采样或缓冲机制。
*   **风险 3**: 多用户并发写文件冲突。
*   **对策**: 为每个任务分配唯一的 UUID Workspace，严格隔离文件系统读写。

## 7. 结论
构建 Backend Wrapper 是 Tricys 现代化的必经之路。核心难点在于对底层长运行进程的稳健控制和实时状态反馈。建议采用 **FastAPI + 异步任务队列** 的架构模式进行实现。
