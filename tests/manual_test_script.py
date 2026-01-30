#!/usr/bin/env python3
"""
手动测试脚本 - Tricys Backend 新功能
Manual test script for Tricys Backend new features

使用方法 / Usage:
    python manual_test_script.py

功能 / Features:
    - 测试进度解析 / Test progress parsing
    - 测试统计端点 / Test statistics endpoint
    - 测试错误处理 / Test error handling
    - 测试配置验证 / Test config validation
"""

import requests
import json
import time
from datetime import datetime

# 配置
BASE_URL = "http://localhost:8000"
API_BASE = f"{BASE_URL}/api/v1"


def print_section(title):
    """打印测试部分标题"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_result(test_name, passed, details=""):
    """打印测试结果"""
    status = "✓ PASS" if passed else "✗ FAIL"
    color = "\033[92m" if passed else "\033[91m"
    reset = "\033[0m"
    print(f"{color}{status}{reset} - {test_name}")
    if details:
        print(f"      {details}")


def test_health_check():
    """测试健康检查"""
    print_section("1. 健康检查 / Health Check")
    
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        passed = response.status_code == 200
        print_result("服务器健康检查", passed, f"状态码: {response.status_code}")
        if passed:
            print(f"      响应: {response.json()}")
        return passed
    except Exception as e:
        print_result("服务器健康检查", False, f"错误: {e}")
        return False


def test_statistics_endpoint():
    """测试统计端点"""
    print_section("2. 统计端点测试 / Statistics Endpoint Test")
    
    try:
        response = requests.get(f"{API_BASE}/tasks/stats/summary", timeout=5)
        passed = response.status_code == 200
        
        if passed:
            data = response.json()
            print_result("统计端点可访问", True, "")
            print(f"      总任务数: {data.get('total_tasks', 'N/A')}")
            print(f"      状态计数: {data.get('status_counts', {})}")
            print(f"      今日完成: {data.get('completed_today', 'N/A')}")
            
            # 验证数据结构
            has_required_fields = all(k in data for k in ['total_tasks', 'status_counts', 'completed_today', 'timestamp'])
            print_result("包含必需字段", has_required_fields, f"字段: {list(data.keys())}")
        else:
            print_result("统计端点可访问", False, f"状态码: {response.status_code}")
        
        return passed
    except Exception as e:
        print_result("统计端点测试", False, f"错误: {e}")
        return False


def test_config_validation():
    """测试配置验证"""
    print_section("3. 配置验证测试 / Config Validation Test")
    
    # 测试1: 空配置应该失败
    test1_passed = False
    try:
        response = requests.post(
            f"{API_BASE}/tasks",
            json={
                "type": "BASIC",
                "config_json": {}
            },
            timeout=5
        )
        test1_passed = response.status_code in [400, 422]
        print_result("拒绝空配置", test1_passed, f"状态码: {response.status_code}")
    except Exception as e:
        print_result("拒绝空配置", False, f"错误: {e}")
    
    # 测试2: 有效配置应该接受
    test2_passed = False
    try:
        response = requests.post(
            f"{API_BASE}/tasks",
            json={
                "type": "BASIC",
                "name": "测试任务",
                "config_json": {
                    "model_name": "ValidModel",
                    "simulation": {
                        "stop_time": 10.0
                    }
                }
            },
            timeout=5
        )
        test2_passed = response.status_code in [200, 201]
        print_result("接受有效配置", test2_passed, f"状态码: {response.status_code}")
        
        if test2_passed:
            task_data = response.json()
            print(f"      创建任务 ID: {task_data.get('id', 'N/A')}")
            return task_data.get('id')
    except Exception as e:
        print_result("接受有效配置", False, f"错误: {e}")
    
    return None


def test_error_handling(task_id=None):
    """测试错误处理"""
    print_section("4. 错误处理测试 / Error Handling Test")
    
    # 测试1: 访问不存在的任务
    try:
        response = requests.get(f"{API_BASE}/tasks/non-existent-task-id", timeout=5)
        passed = response.status_code == 404
        print_result("正确返回404", passed, f"状态码: {response.status_code}")
    except Exception as e:
        print_result("正确返回404", False, f"错误: {e}")
    
    # 测试2: 停止已完成的任务（如果有任务ID）
    if task_id:
        # 先等待任务完成或手动将其标记为完成
        time.sleep(1)
        try:
            # 尝试停止（可能会失败，取决于任务状态）
            response = requests.post(f"{API_BASE}/tasks/{task_id}/stop", timeout=5)
            # 如果任务还在PENDING/RUNNING，应该成功或返回适当错误
            passed = response.status_code in [200, 400]
            print_result("停止任务处理正确", passed, f"状态码: {response.status_code}")
        except Exception as e:
            print_result("停止任务处理", False, f"错误: {e}")


def test_progress_parsing_patterns():
    """测试进度解析模式（单元测试）"""
    print_section("5. 进度解析模式测试 / Progress Parsing Patterns Test")
    
    import re
    
    # 导入解析模式
    PROGRESS_PATTERN_1 = re.compile(r'(?:Running\s+job|Job)\s+(\d+)\s*(?:/|of)\s*(\d+)', re.IGNORECASE)
    PROGRESS_PATTERN_2 = re.compile(r'(?:Progress\s*:|complete\s*:)?\s*(\d+(?:\.\d+)?)\s*%\s*(?:complete)?', re.IGNORECASE)
    PROGRESS_PATTERN_3 = re.compile(r'[\[\(](\d+(?:\.\d+)?)\s*%[\]\)]')
    
    test_cases = [
        ("Running job 5/100", PROGRESS_PATTERN_1, "模式1: Running job X/Y"),
        ("Job 25 of 50", PROGRESS_PATTERN_1, "模式1: Job X of Y"),
        ("Progress: 45.5%", PROGRESS_PATTERN_2, "模式2: Progress: X%"),
        ("[50%] Processing", PROGRESS_PATTERN_3, "模式3: [X%]"),
        ("(80%) Done", PROGRESS_PATTERN_3, "模式3: (X%)"),
        ("No progress here", None, "无进度信息"),
    ]
    
    for line, expected_pattern, description in test_cases:
        matched = False
        for pattern in [PROGRESS_PATTERN_1, PROGRESS_PATTERN_2, PROGRESS_PATTERN_3]:
            if pattern.search(line):
                matched = True
                break
        
        expected_match = (expected_pattern is not None)
        passed = matched == expected_match
        print_result(description, passed, f"测试: '{line}'")


def test_task_lifecycle():
    """测试完整的任务生命周期"""
    print_section("6. 任务生命周期测试 / Task Lifecycle Test")
    
    # 创建任务
    try:
        response = requests.post(
            f"{API_BASE}/tasks",
            json={
                "type": "BASIC",
                "name": "生命周期测试",
                "config_json": {
                    "model_name": "LifecycleTest"
                }
            },
            timeout=5
        )
        
        if response.status_code in [200, 201]:
            task_id = response.json()['id']
            print_result("任务创建", True, f"ID: {task_id}")
            
            # 查询任务
            time.sleep(0.5)
            response = requests.get(f"{API_BASE}/tasks/{task_id}", timeout=5)
            if response.status_code == 200:
                task_data = response.json()
                print_result("任务查询", True, f"状态: {task_data.get('status')}")
                
                # 删除任务（如果不是运行中）
                if task_data.get('status') not in ['RUNNING']:
                    time.sleep(0.5)
                    response = requests.delete(f"{API_BASE}/tasks/{task_id}", timeout=5)
                    print_result("任务删除", response.status_code == 200, f"状态码: {response.status_code}")
            else:
                print_result("任务查询", False, f"状态码: {response.status_code}")
        else:
            print_result("任务创建", False, f"状态码: {response.status_code}")
    except Exception as e:
        print_result("任务生命周期", False, f"错误: {e}")


def main():
    """主测试函数"""
    print("\n" + "🧪" * 30)
    print("Tricys Backend 新功能手动测试")
    print("Manual Test for New Features")
    print("🧪" * 30)
    print(f"\n测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"服务器: {BASE_URL}")
    
    # 运行测试
    results = []
    
    # 1. 健康检查
    if not test_health_check():
        print("\n❌ 服务器未运行或无法访问！")
        print("请先启动服务器: python -m uvicorn tricys_backend.main:app --reload")
        return
    
    # 2. 统计端点
    results.append(("统计端点", test_statistics_endpoint()))
    
    # 3. 配置验证
    task_id = test_config_validation()
    
    # 4. 错误处理
    test_error_handling(task_id)
    
    # 5. 进度解析
    test_progress_parsing_patterns()
    
    # 6. 任务生命周期
    test_task_lifecycle()
    
    # 总结
    print_section("测试总结 / Test Summary")
    print(f"测试完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\n所有测试执行完毕！")
    print("请查看上述结果了解详细信息。")
    print("\n提示: 有些测试可能需要手动验证 WebSocket 连接或日志输出。")
    print("详细的手动测试步骤请参考: manual_test_new_features.html")


if __name__ == "__main__":
    main()
