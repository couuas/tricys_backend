# Tricys Backend 接口规范 (Interface Specification)

## 1. 概述 (Overview)
*   **Base URL**: `/api/v1`
*   **Content-Type**: `application/json`
*   **Response Format**: 标准 JSON 包裹
    ```json
    {
      "code": 200,
      "message": "success",
      "data": { ... }
    }
    ```

## 2. 任务管理接口 (Task Management)

### 2.1 提交仿真任务
创建一个新的 simulation 或 analysis 任务。

*   **Endpoint**: `POST /tasks`
*   **Request Body**:
    ```json
    {
      "type": "BASIC", // or "ANALYSIS"
      "name": "My Simulation Run 001",
      "config": {
        // ... 标准 tricys config.json 内容 ...
        "simulation": { ... },
        "paths": { ... }
      },
      "enhanced": true, // optional, default false
      "turbo": false    // optional, default false
    }
    ```
*   **Response**:
    ```json
    {
      "task_id": "550e8400-e29b-41d4-a716-446655440000",
      "status": "PENDING",
      "queue_position": 1
    }
    ```

### 2.2 查询任务列表
获取历史任务列表，支持分页。

*   **Endpoint**: `GET /tasks`
*   **Query Params**:
    *   `page`: int (default 1)
    *   `size`: int (default 20)
    *   `status`: str (optional, filter by PENDING/RUNNING/etc)
*   **Response**:
    ```json
    {
      "total": 50,
      "items": [
        {
          "id": "...",
          "name": "...",
          "status": "COMPLETED",
          "created_at": "2023-10-27T10:00:00Z"
        },
        ...
      ]
    }
    ```

### 2.3 查询任务详情
获取单个任务的详细信息，包括执行结果路径。

*   **Endpoint**: `GET /tasks/{task_id}`
*   **Response**:
    ```json
    {
      "id": "...",
      "status": "COMPLETED",
      "result_summary": {
         "hdf5_path": "/path/to/workspace/sweep_results.h5",
         "csv_path": "/path/to/workspace/results.csv"
      },
      "error": null
    }
    ```

### 2.4 终止任务
强制停止一个正在运行 (RUNNING) 或排队中 (PENDING) 的任务。

*   **Endpoint**: `POST /tasks/{task_id}/stop`
*   **Response**:
    ```json
    {
      "success": true,
      "previous_status": "RUNNING",
      "current_status": "STOPPED"
    }
    ```

### 2.5 HDF5 数据切片 (Data Slicing)
获取 HDF5 结果中的特定数据片段。

*   **Endpoint**: `POST /tasks/{task_id}/results/query`
*   **Request Body**:
    ```json
    {
       "variables": ["sds.inventory", "metrics.TBR"],
       "job_ids": [1, 5, 10], // optional, default all
       "time_range": [0, 1000] // optional, [start, end]
    }
    ```
*   **Response**:
    ```json
    {
      "time": [0.0, 100.0, ...], // Shared time axis if possible
      "data": {
         "1": { "sds.inventory": [...], "metrics.TBR": [...] },
         "5": { ... }
      }
    }
    ```

### 2.6 删除任务
从数据库中软删除记录，并可选择是否清理磁盘上的工作区文件。

*   **Endpoint**: `DELETE /tasks/{task_id}`
*   **Query Params**:
    *   `cleanup_files`: bool (default false)

## 3. 实时交互接口 (Real-time Interaction)

### 3.1 WebSocket 任务监控
建立长连接，实时接收任务的日志和进度更新。

*   **Endpoint**: `WS /ws/tasks/{task_id}`
*   **Protocol**:
    *   **客户端发送**: (暂无，主要用于接收)
    *   **服务端推送 (Message Frames)**:
        *   **日志消息**:
            ```json
            {
              "type": "LOG",
              "level": "INFO",
              "timestamp": "2023-10-27T10:01:05Z",
              "content": "Compiling modelica package..."
            }
            ```
        *   **进度消息**:
            ```json
            {
              "type": "PROGRESS",
              "current": 5,
              "total": 100,
              "percent": 5.0,
              "description": "Running job 5/100"
            }
            ```
        *   **状态变更**:
            ```json
            {
              "type": "STATUS_CHANGE",
              "from": "PENDING",
              "to": "RUNNING"
            }
            ```

## 4. 辅助接口 (Utilities)

### 4.1 获取默认配置模板
获取一份当前版本最新的标准 `config.json` 模板，供前端生成默认表单。

*   **Endpoint**: `GET /config/template`
*   **Response**: JSON Object of default config.

### 4.2 归档下载
下载指定任务的工作区打包文件 (.zip)。

*   **Endpoint**: `GET /tasks/{task_id}/archive`
*   **Response**: Binary Stream (application/zip)

### 4.3 系统健康检查
*   **Endpoint**: `GET /health`
*   **Response**: `{"status": "ok", "version": "1.0.0"}`

## 5. 结果文件服务 (Result Services - Stage 6)
提供对任务结果文件的细粒度访问。

#### 2.7.1 获取结果摘要
*   **Endpoint**: `GET /tasks/{task_id}/result_summary`
*   **Response**: 
    ```json
    {
      "metrics": [{"job_id": 1, "Startup Inventory": 100.5, ...}], // Summary table
      "file_size_mb": 150.2,
      "generated_at": "2023-10-27T10:05:00Z"
    }
    ```

#### 2.7.2 浏览结果文件
*   **Endpoint**: `GET /tasks/{task_id}/files`
*   **Query Params**: `path` (optional sub-directory)
*   **Response**: 
    ```json
    [
      {"name": "results.h5", "type": "file", "size": 1048576, "modified": "..."},
      {"name": "logs", "type": "dir", "size": 0, "modified": "..."}
    ]
    ```

#### 2.7.3 下载结果文件
所有文件均支持 `Range` 请求头，实现流式下载/断点续传。
*   **Endpoint**: `GET /tasks/{task_id}/files/download`
*   **Query Params**: `path` (relative file path)
*   **Response**: `application/octet-stream`
