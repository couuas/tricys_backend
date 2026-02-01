# TRICYS_BACKEND 架构规则与约束

本文档定义了 **TRICYS_BACKEND** 项目的架构原则和开发约束，重点关注 **后端服务 (`tricys_backend`)** 与 **核心 CLI (`tricys`)** 之间的关系。

> [!NOTE]
> **Tricys CLI (`tricys`)** 是一个独立的开源项目，并不包含在 `tricys_backend` 代码库中。后端仅通过系统命令调用它。

## 1. 核心架构原则：“瘦后端，厚 CLI” (Thin Backend, Thick CLI)

*   **仅作为服务封装层**: `tricys_backend` 必须完全作为 **Restful/WebSocket 服务层** 运行。它应只负责处理 HTTP 请求、进程管理、数据库持久化和客户端通信。
*   **后端不含仿真逻辑**: 后端 **绝不能** 包含任何核心仿真逻辑、Modelica 解析逻辑或科学计算代码。
*   **子进程是唯一接口**: 所有与核心业务逻辑（运行仿真、分析结果、解析模型）的交互，**必须** 通过 `subprocess` 调用 `tricys` CLI 来完成。
    *   *允许*: `subprocess.run(["tricys", "parse", ...])`
    *   *禁止*: `from tricys.core.modelica import get_all_parameters` (在后端代码中)

## 2. 新功能开发流程

当出现新需求时（例如，“我需要获取模型参数”或“我需要查询特定的 HDF5 数据”）：

1.  **检查 `tricys` CLI**: `tricys` CLI 是否已经通过子命令支持此功能？
2.  **优先扩展 CLI**: 如果不支持，请先在 `tricys/main.py` 中将其作为新的 **Subcommand (子命令)** 实现。
    *   确保它将结构化数据（最好是 JSON）输出到 `stdout`，以便机器解析。
    *   确保 Debug/Info 日志输出到 `stderr`，避免污染 JSON 输出。
3.  **在后端集成**: CLI 命令就绪后，再在 `tricys_backend` 中实现 Wrapper 来调用此命令并服务化结果。

## 3. Tricys CLI 现状总结 (截至 Stage 6)

`tricys` CLI (`tricys/main.py`) 是所有核心能力的统一入口点。

### 支持的命令

| 子命令 | 描述 | 后端设计用途 |
| :--- | :--- | :--- |
| `basic` | 运行标准参数仿真。 | 被 Task Worker 用于执行 Basic 任务。 |
| `analysis` | 运行敏感性分析或优化。 | 被 Task Worker 用于执行 Analysis 任务。 |
| `parse` | **(New)** 解析 Modelica 包以提取参数。 | 被后端用于动态生成配置 Schema。 |
| `archive` |/`unarchive` | 压缩/解压任务工作区。 | 用于导入/导出功能。 |
| `hdf5` | 启动通用 HDF5 可视化工具 (纯 GUI)。 | *后端不直接使用。* |
| `gui` | 启动传统的 Tkinter/PySide GUI。 | *后端不直接使用。* |

### 关键 Flags

*   `--config (-c)`: JSON 配置文件路径 (标准输入)。
*   `--enhanced`: 启用 "编译一次，运行多次" 优化。
*   `--turbo`: 禁用显式 CPU/内存限制以获得最高性能。

## 4. 文档与维护

*   **保持 `rules.md` 更新**: 每当做出新的架构决策或添加新的主要子系统时，必须更新此文件。
*   **后端设计同步**: `tricys_backend/.agent/backend_design/` 文档应严格遵循这些约束。

---
**Agent 总结**:
在后端编写 Python 逻辑之前，**始终** 寻找使用 `tricys <command>` 的方法。如果命令不存在，**创建它** 是你的首要任务。
