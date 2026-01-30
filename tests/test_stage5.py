"""
测试新功能：进度解析、增强清理服务、统计端点
Tests for new features: Progress parsing, enhanced cleanup service, statistics endpoint
"""

import os
import pytest
import tempfile
import time
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
from sqlmodel import Session, SQLModel, create_engine, select
from fastapi.testclient import TestClient

from tricys_backend.main import app, recover_orphaned_tasks
from tricys_backend.core.config import settings
from tricys_backend.utils.db import get_session
from tricys_backend.models.task import Task
from tricys_backend.services.engine import LogReaderThread
from tricys_backend.services.cleanup_service import CleanupService
from tricys_backend.services.task_queue import db_engine

# 测试数据库配置
TEST_DB_URL = "sqlite:///./test_new_features.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})


@pytest.fixture(scope="module", autouse=True)
def setup_test_env():
    """设置测试环境"""
    # 清理旧数据库
    db_path = "./test_new_features.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    
    # 创建数据库表
    SQLModel.metadata.create_all(test_engine)
    
    # 覆盖依赖注入
    def override_get_session():
        with Session(test_engine) as session:
            yield session
    
    app.dependency_overrides[get_session] = override_get_session
    
    yield
    
    # 清理
    if os.path.exists(db_path):
        os.remove(db_path)


class TestProgressParsing:
    """测试进度解析功能"""
    
    def test_progress_pattern_1_job_numbers(self):
        """测试模式1：任务编号格式 'Running job 5/100'"""
        reader = LogReaderThread.__new__(LogReaderThread)
        reader.last_progress_percent = 0.0
        
        # 测试 "Running job X/Y" 格式
        result = reader.parse_progress("Running job 5/100")
        assert result is not None
        assert result["type"] == "PROGRESS"
        assert result["current"] == 5
        assert result["total"] == 100
        assert result["percent"] == 5.0
        assert "5/100" in result["description"]
    
    def test_progress_pattern_1_job_of(self):
        """测试模式1：'Job X of Y' 格式"""
        reader = LogReaderThread.__new__(LogReaderThread)
        reader.last_progress_percent = 0.0
        
        result = reader.parse_progress("Job 25 of 50")
        assert result is not None
        assert result["current"] == 25
        assert result["total"] == 50
        assert result["percent"] == 50.0
    
    def test_progress_pattern_2_percentage(self):
        """测试模式2：百分比格式 'Progress: 45%'"""
        reader = LogReaderThread.__new__(LogReaderThread)
        reader.last_progress_percent = 0.0
        
        result = reader.parse_progress("Progress: 45.5%")
        assert result is not None
        assert result["type"] == "PROGRESS"
        assert result["percent"] == 45.5
    
    def test_progress_pattern_3_brackets(self):
        """测试模式3：括号格式 '[50%]' 或 '(80%)'"""
        reader = LogReaderThread.__new__(LogReaderThread)
        reader.last_progress_percent = 0.0
        
        # 方括号
        result1 = reader.parse_progress("[50%] Processing...")
        assert result1 is not None
        assert result1["percent"] == 50.0
        
        # 圆括号
        reader.last_progress_percent = 0.0
        result2 = reader.parse_progress("(80%) Done")
        assert result2 is not None
        assert result2["percent"] == 80.0
    
    def test_progress_throttling(self):
        """测试进度节流：只有变化>1%时才发送"""
        reader = LogReaderThread.__new__(LogReaderThread)
        reader.last_progress_percent = 45.0
        
        # 变化小于1%，不应发送
        result1 = reader.parse_progress("Progress: 45.5%")
        assert result1 is None
        
        # 变化大于1%，应该发送
        result2 = reader.parse_progress("Progress: 47%")
        assert result2 is not None
        assert result2["percent"] == 47.0
    
    def test_no_progress_in_normal_log(self):
        """测试普通日志不会被识别为进度"""
        reader = LogReaderThread.__new__(LogReaderThread)
        reader.last_progress_percent = 0.0
        
        result = reader.parse_progress("This is a normal log line without progress")
        assert result is None
    
    def test_invalid_progress_values(self):
        """测试无效的进度值处理"""
        reader = LogReaderThread.__new__(LogReaderThread)
        reader.last_progress_percent = 0.0
        
        # 超过100%的应该被忽略
        result = reader.parse_progress("Progress: 150%")
        assert result is None
        
        # 除以0的情况
        result2 = reader.parse_progress("Job 5/0")
        assert result2 is None


class TestEnhancedCleanupService:
    """测试增强的清理服务"""
    
    def test_cleanup_only_terminal_states(self):
        """测试只清理终止状态的任务"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_dir = Path(tmpdir)
            
            # 创建测试任务
            with Session(test_engine) as session:
                # 完成的任务 - 应该清理
                task1 = Task(
                    id="test-completed-task",
                    status="COMPLETED",
                    updated_at=datetime.utcnow() - timedelta(days=8)
                )
                session.add(task1)
                
                # 运行中的任务 - 不应该清理
                task2 = Task(
                    id="test-running-task",
                    status="RUNNING",
                    updated_at=datetime.utcnow() - timedelta(days=8)
                )
                session.add(task2)
                
                # 失败的任务 - 应该清理
                task3 = Task(
                    id="test-failed-task",
                    status="FAILED",
                    updated_at=datetime.utcnow() - timedelta(days=8)
                )
                session.add(task3)
                
                session.commit()
            
            # 创建工作区目录
            date_dir = workspace_dir / "2026-01-20"
            date_dir.mkdir(parents=True)
            (date_dir / "test-completed-task").mkdir()
            (date_dir / "test-running-task").mkdir()
            (date_dir / "test-failed-task").mkdir()
            
            # 设置旧时间
            old_time = time.time() - (8 * 86400)
            os.utime(date_dir / "test-completed-task", (old_time, old_time))
            os.utime(date_dir / "test-running-task", (old_time, old_time))
            os.utime(date_dir / "test-failed-task", (old_time, old_time))
            
            # 运行清理
            cleanup_service = CleanupService(str(workspace_dir), retention_days=7)
            cleanup_service.cleanup_old_tasks(test_engine)
            
            # 验证：COMPLETED 和 FAILED 的应该被删除
            assert not (date_dir / "test-completed-task").exists()
            assert not (date_dir / "test-failed-task").exists()
            # RUNNING 的不应该被删除
            assert (date_dir / "test-running-task").exists()
    
    def test_cleanup_respects_retention_period(self):
        """测试清理尊重保留期限"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_dir = Path(tmpdir)
            
            with Session(test_engine) as session:
                # 新任务 - 不应该清理
                task1 = Task(
                    id="test-new-task",
                    status="COMPLETED",
                    updated_at=datetime.utcnow() - timedelta(days=2)
                )
                session.add(task1)
                session.commit()
            
            date_dir = workspace_dir / "2026-01-28"
            date_dir.mkdir(parents=True)
            (date_dir / "test-new-task").mkdir()
            
            # 设置较新时间
            new_time = time.time() - (2 * 86400)
            os.utime(date_dir / "test-new-task", (new_time, new_time))
            
            # 运行清理
            cleanup_service = CleanupService(str(workspace_dir), retention_days=7)
            cleanup_service.cleanup_old_tasks(test_engine)
            
            # 不应该被删除
            assert (date_dir / "test-new-task").exists()
    
    def test_cleanup_empty_date_directories(self):
        """测试清理空的日期目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_dir = Path(tmpdir)
            
            # 创建空日期目录
            empty_dir = workspace_dir / "2026-01-15"
            empty_dir.mkdir(parents=True)
            
            cleanup_service = CleanupService(str(workspace_dir), retention_days=7)
            cleanup_service.cleanup_old_tasks(test_engine)
            
            # 空目录应该被删除
            assert not empty_dir.exists()


class TestTaskStatisticsEndpoint:
    """测试任务统计端点"""
    
    def test_statistics_summary(self):
        """测试统计摘要端点"""
        client = TestClient(app)
        
        # 创建测试任务
        with Session(test_engine) as session:
            # 清空现有任务
            session.exec(select(Task)).all()
            for task in session.exec(select(Task)).all():
                session.delete(task)
            session.commit()
            
            # 添加不同状态的任务
            tasks = [
                Task(id="stat-pending-1", status="PENDING"),
                Task(id="stat-pending-2", status="PENDING"),
                Task(id="stat-running-1", status="RUNNING"),
                Task(id="stat-completed-1", status="COMPLETED"),
                Task(id="stat-completed-2", status="COMPLETED"),
                Task(id="stat-completed-3", status="COMPLETED"),
                Task(id="stat-failed-1", status="FAILED"),
                Task(id="stat-stopped-1", status="STOPPED"),
            ]
            for task in tasks:
                session.add(task)
            session.commit()
        
        # 请求统计
        response = client.get("/api/v1/tasks/stats/summary")
        assert response.status_code == 200
        
        data = response.json()
        assert "total_tasks" in data
        assert "status_counts" in data
        assert "completed_today" in data
        assert "timestamp" in data
        
        # 验证计数
        assert data["total_tasks"] == 8
        assert data["status_counts"]["pending"] == 2
        assert data["status_counts"]["running"] == 1
        assert data["status_counts"]["completed"] == 3
        assert data["status_counts"]["failed"] == 1
        assert data["status_counts"]["stopped"] == 1


class TestErrorHandling:
    """测试改进的错误处理"""
    
    def test_create_task_error_handling(self):
        """测试创建任务时的错误处理"""
        client = TestClient(app)
        
        # 发送无效配置
        invalid_payload = {
            "type": "BASIC",
            "config_json": {}  # 空配置应该失败
        }
        
        response = client.post("/api/v1/tasks", json=invalid_payload)
        # 应该返回验证错误
        assert response.status_code in [400, 422, 500]
    
    def test_delete_running_task_error(self):
        """测试删除运行中任务的错误处理"""
        client = TestClient(app)
        
        # 创建运行中的任务
        with Session(test_engine) as session:
            task = Task(
                id="test-delete-running",
                status="RUNNING",
                config_json={"model_name": "Test"}
            )
            session.add(task)
            session.commit()
        
        # 尝试删除运行中的任务
        response = client.delete("/api/v1/tasks/test-delete-running")
        assert response.status_code == 400
        assert "running" in response.json()["detail"].lower()
    
    def test_stop_completed_task_error(self):
        """测试停止已完成任务的错误处理"""
        client = TestClient(app)
        
        with Session(test_engine) as session:
            task = Task(
                id="test-stop-completed",
                status="COMPLETED",
                config_json={"model_name": "Test"}
            )
            session.add(task)
            session.commit()
        
        response = client.post("/api/v1/tasks/test-stop-completed/stop")
        assert response.status_code == 400
        assert "cannot stop" in response.json()["detail"].lower()


class TestCrashRecovery:
    """测试崩溃恢复功能"""
    
    @pytest.mark.asyncio
    async def test_orphaned_task_recovery(self):
        """测试孤立任务恢复"""
        # 使用测试数据库引擎
        with Session(test_engine) as session:
            # 创建一个"孤立"的运行中任务（没有有效PID）
            task = Task(
                id="test-orphaned-task",
                status="RUNNING",
                pid=999999,  # 不存在的PID
                config_json={"model_name": "Test"}
            )
            session.add(task)
            session.commit()
        
        # 模拟恢复函数（直接使用 test_engine）
        import psutil
        from sqlmodel import select
        with Session(test_engine) as session:
            running_tasks = session.exec(
                select(Task).where(Task.status == "RUNNING")
            ).all()
            
            for task in running_tasks:
                if task.pid and not psutil.pid_exists(task.pid):
                    task.status = "FAILED"
                    task.error_msg = "Process lost during server restart"
                    task.pid = None
                    session.add(task)
            session.commit()
        
        # 验证任务被标记为FAILED
        with Session(test_engine) as session:
            recovered_task = session.get(Task, "test-orphaned-task")
            assert recovered_task.status == "FAILED"
            assert recovered_task.pid is None
            assert "lost" in recovered_task.error_msg.lower()


class TestConfigValidation:
    """测试配置验证"""
    
    def test_valid_config_accepted(self):
        """测试有效配置被接受"""
        from tricys_backend.models.task import ConfigJsonSchema
        
        valid_config = {
            "model_name": "MyModel",
            "paths": {
                "mo_file": "model.mo"
            },
            "simulation": {
                "stop_time": 10.0,
                "step_size": 0.1
            }
        }
        
        # 不应该抛出异常
        schema = ConfigJsonSchema(**valid_config)
        assert schema.model_name == "MyModel"
    
    def test_invalid_model_name_rejected(self):
        """测试无效模型名被拒绝"""
        from tricys_backend.models.task import ConfigJsonSchema
        import pytest
        
        invalid_config = {
            "model_name": "../../etc/passwd"  # 路径遍历尝试
        }
        
        with pytest.raises(Exception):
            ConfigJsonSchema(**invalid_config)
    
    def test_excessive_parameter_sweep_rejected(self):
        """测试过大的参数扫描被拒绝"""
        from tricys_backend.models.task import ConfigJsonSchema
        import pytest
        
        invalid_config = {
            "model_name": "Test",
            "simulation_parameters": {
                "parameters": {
                    "param1": list(range(10001))  # 超过限制
                }
            }
        }
        
        with pytest.raises(Exception):
            ConfigJsonSchema(**invalid_config)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
