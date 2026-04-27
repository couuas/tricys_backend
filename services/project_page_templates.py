import json
import uuid
from typing import Any, Dict, List, Optional

from tricys_backend.models.project import Project
from tricys_backend.models.task import Task


BASE_REQUEST_GLOBAL_CONFIG = {
    "requestDataPond": [],
    "requestOriginUrl": "/api/v2/goview",
    "requestInterval": 30,
    "requestIntervalUnit": "second",
    "requestParams": {
        "Body": {
            "form-data": {},
            "x-www-form-urlencoded": {},
            "json": "",
            "xml": "",
        },
        "Header": {},
        "Params": {},
    },
}

TEXT_COMMON_CONFIG = {
    "key": "TextCommon",
    "chartKey": "VTextCommon",
    "conKey": "VCTextCommon",
    "title": "文字",
    "category": "Texts",
    "categoryName": "文本",
    "package": "Informations",
    "chartFrame": "COMMON",
    "image": "text_static.png",
}

TRICYS_METRICS_CONFIG = {
    "key": "TricysMetrics",
    "chartKey": "VTricysMetrics",
    "conKey": "VCTricysMetrics",
    "title": "Tricys Metrics",
    "category": "More",
    "categoryName": "更多",
    "package": "Informations",
    "chartFrame": "COMMON",
    "image": "info.png",
}

DEFAULT_COMPONENT_STYLES = {
    "filterShow": False,
    "hueRotate": 0,
    "saturate": 1,
    "contrast": 1,
    "brightness": 1,
    "opacity": 1,
    "rotateZ": 0,
    "rotateX": 0,
    "rotateY": 0,
    "skewX": 0,
    "skewY": 0,
    "blendMode": "normal",
    "animations": [],
}

DEFAULT_COMPONENT_PREVIEW = {"overFlowHidden": False}
DEFAULT_COMPONENT_STATUS = {"lock": False, "hide": False}
DEFAULT_COMPONENT_EVENTS = {
    "baseEvent": {
        "click": None,
        "dblclick": None,
        "mouseenter": None,
        "mouseleave": None,
    },
    "advancedEvents": {
        "vnodeMounted": None,
        "vnodeBeforeMount": None,
    },
    "interactEvents": [],
}


def _build_request_params(**params: Any) -> Dict[str, Any]:
    filtered = {key: value for key, value in params.items() if value is not None and value != ""}
    return {
        "Body": {
            "form-data": {},
            "x-www-form-urlencoded": {},
            "json": "",
            "xml": "",
        },
        "Header": {},
        "Params": filtered,
    }


def _build_data_pond_item(
    data_pond_id: str,
    data_pond_name: str,
    request_url: str,
    params: Dict[str, Any],
    filter_code: str = "",
) -> Dict[str, Any]:
    return {
        "dataPondId": data_pond_id,
        "dataPondName": data_pond_name,
        "dataPondRequestConfig": {
            "requestDataType": 1,
            "requestHttpType": "get",
            "requestUrl": request_url,
            "requestInterval": 30,
            "requestIntervalUnit": "second",
            "requestContentType": 0,
            "requestParamsBodyType": "none",
            "requestSQLContent": {"sql": "select * from  where"},
            "requestParams": _build_request_params(**params),
            "filter": filter_code or None,
        },
    }


def list_project_page_data_sources(project: Project) -> List[Dict[str, Any]]:
    return [
        {
            "source_key": "project.summary",
            "title": "Project Summary",
            "description": "Project title, latest update time, and latest task status.",
            "request": _build_data_pond_item(
                "project-summary",
                "Project Summary",
                "/data/summary",
                {"projectId": project.id},
            )["dataPondRequestConfig"],
            "sample_filter": "return '项目：' + (data?.data?.projectName || '-')",
        },
        {
            "source_key": "project.tasks",
            "title": "Recent Tasks",
            "description": "Recent task list for the current project.",
            "request": _build_data_pond_item(
                "project-tasks",
                "Project Tasks",
                "/data/tasks",
                {"projectId": project.id, "limit": 8},
            )["dataPondRequestConfig"],
            "sample_filter": "const items = data?.data || []; return '任务数：' + items.length",
        },
        {
            "source_key": "project.parameters",
            "title": "Project Parameters",
            "description": "Parameter list extracted from the Modelica project structure.",
            "request": _build_data_pond_item(
                "project-parameters",
                "Project Parameters",
                "/data/parameters",
                {"projectId": project.id},
            )["dataPondRequestConfig"],
            "sample_filter": "const items = data?.data || []; return '参数数量：' + items.length",
        },
        {
            "source_key": "project.latestTask",
            "title": "Latest Task",
            "description": "Latest task summary suitable for result and publication templates.",
            "request": _build_data_pond_item(
                "project-latest-task",
                "Latest Task",
                "/data/latest-task",
                {"projectId": project.id},
            )["dataPondRequestConfig"],
            "sample_filter": "return '最新任务：' + (data?.data?.name || '无')",
        },
        {
            "source_key": "project.latestTask.metrics",
            "title": "Latest Task Metrics",
            "description": "Use the latest task as a semantic anchor for TRICYS metrics widgets.",
            "request": _build_data_pond_item(
                "project-latest-task",
                "Latest Task",
                "/data/latest-task",
                {"projectId": project.id},
            )["dataPondRequestConfig"],
            "sample_filter": "return '指标绑定任务：' + (data?.data?.id || '无')",
        },
    ]


def _default_request() -> Dict[str, Any]:
    return {
        "requestDataType": 0,
        "requestHttpType": "get",
        "requestUrl": "",
        "requestInterval": None,
        "requestIntervalUnit": "second",
        "requestContentType": 0,
        "requestParamsBodyType": "none",
        "requestSQLContent": {"sql": "select * from  where"},
        "requestParams": _build_request_params(),
    }


def _build_text_component(
    text: str,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    font_size: int,
    color: str,
    weight: str = "normal",
    letter_spacing: int = 0,
    background: str = "#00000000",
    text_align: str = "left",
    pond_id: Optional[str] = None,
    filter_code: Optional[str] = None,
) -> Dict[str, Any]:
    request = _default_request()
    if pond_id:
        request.update({
            "requestDataType": 2,
            "requestDataPondId": pond_id,
        })
    return {
        "id": str(uuid.uuid4()),
        "isGroup": False,
        "attr": {
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "offsetX": 0,
            "offsetY": 0,
            "zIndex": 1,
        },
        "styles": dict(DEFAULT_COMPONENT_STYLES),
        "preview": dict(DEFAULT_COMPONENT_PREVIEW),
        "status": dict(DEFAULT_COMPONENT_STATUS),
        "request": request,
        "filter": filter_code,
        "events": json.loads(json.dumps(DEFAULT_COMPONENT_EVENTS)),
        "key": "TextCommon",
        "chartConfig": dict(TEXT_COMMON_CONFIG),
        "option": {
            "link": "",
            "linkHead": "http://",
            "dataset": text,
            "fontSize": font_size,
            "fontColor": color,
            "paddingX": 10,
            "paddingY": 10,
            "textAlign": text_align,
            "fontWeight": weight,
            "borderWidth": 0,
            "borderColor": "#ffffff",
            "borderRadius": 5,
            "letterSpacing": letter_spacing,
            "writingMode": "horizontal-tb",
            "backgroundColor": background,
        },
    }


def _build_tricys_metrics_component(
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    task_id: str,
    metrics: Optional[List[str]] = None,
    font_size: int = 26,
    color: str = "#ffffff",
    item_gap: int = 18,
) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "isGroup": False,
        "attr": {
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "offsetX": 0,
            "offsetY": 0,
            "zIndex": 1,
        },
        "styles": dict(DEFAULT_COMPONENT_STYLES),
        "preview": dict(DEFAULT_COMPONENT_PREVIEW),
        "status": dict(DEFAULT_COMPONENT_STATUS),
        "request": _default_request(),
        "filter": None,
        "events": json.loads(json.dumps(DEFAULT_COMPONENT_EVENTS)),
        "key": "TricysMetrics",
        "chartConfig": dict(TRICYS_METRICS_CONFIG),
        "option": {
            "dataset": {
                "taskId": task_id,
                "metrics": metrics or ["efficiency", "max_temp"],
            },
            "style": {
                "fontSize": font_size,
                "color": color,
                "itemGap": item_gap,
            },
        },
    }


def _build_template_components(template_key: str, project: Project, latest_task: Optional[Task] = None) -> List[Dict[str, Any]]:
    latest_task_id = latest_task.id if latest_task else ""
    if template_key == "project-overview":
        components = [
            _build_text_component(
                project.name or "Project Overview",
                x=120,
                y=96,
                w=760,
                h=88,
                font_size=52,
                color="#f2f7fb",
                weight="bold",
                letter_spacing=2,
            ),
            _build_text_component(
                "TRICYS PROJECT SURFACE",
                x=124,
                y=60,
                w=420,
                h=34,
                font_size=18,
                color="#65d6ff",
                weight="bold",
                letter_spacing=4,
            ),
            _build_text_component(
                "项目：-",
                x=124,
                y=230,
                w=560,
                h=58,
                font_size=28,
                color="#ffffff",
                pond_id="project-summary",
                filter_code="return '项目：' + (data?.data?.projectName || '-')",
            ),
            _build_text_component(
                "状态：-",
                x=124,
                y=304,
                w=420,
                h=54,
                font_size=24,
                color="#91f7c4",
                pond_id="project-summary",
                filter_code="return '状态：' + (data?.data?.status || 'NO_TASK')",
            ),
            _build_text_component(
                "更新时间：-",
                x=124,
                y=370,
                w=620,
                h=54,
                font_size=22,
                color="#a7b8c7",
                pond_id="project-summary",
                filter_code="return '更新时间：' + (data?.data?.lastUpdated || '-')",
            ),
            _build_text_component(
                "任务数：0",
                x=1120,
                y=214,
                w=360,
                h=74,
                font_size=34,
                color="#ffd56a",
                weight="bold",
                text_align="center",
                background="rgba(255,213,106,0.08)",
                pond_id="project-tasks",
                filter_code="const items = data?.data || []; return '任务数：' + items.length",
            ),
            _build_text_component(
                "最新任务：无",
                x=1120,
                y=316,
                w=500,
                h=62,
                font_size=24,
                color="#ecf4fb",
                pond_id="project-tasks",
                filter_code="const items = data?.data || []; const head = items[0] || {}; return '最新任务：' + (head.name || '无')",
            ),
            _build_text_component(
                "该模板已预置项目摘要与任务数据池，可在 GoView 编辑器中继续绑定更复杂组件。",
                x=124,
                y=880,
                w=1280,
                h=56,
                font_size=20,
                color="#7f95a5",
            ),
        ]
        if latest_task_id:
            components.extend([
                _build_text_component(
                    "Latest Task Metrics",
                    x=1120,
                    y=122,
                    w=420,
                    h=48,
                    font_size=22,
                    color="#7fdfff",
                    weight="bold",
                    text_align="center",
                ),
                _build_tricys_metrics_component(
                    x=1080,
                    y=404,
                    w=540,
                    h=240,
                    task_id=latest_task_id,
                    metrics=["efficiency", "max_temp"],
                    font_size=28,
                    color="#f3fbff",
                ),
            ])
        return components
    if template_key == "parameter-board":
        return [
            _build_text_component(
                "Parameter Board",
                x=120,
                y=96,
                w=760,
                h=88,
                font_size=50,
                color="#f4f6e8",
                weight="bold",
            ),
            _build_text_component(
                "参数数量：0",
                x=120,
                y=238,
                w=420,
                h=64,
                font_size=30,
                color="#a7f3b0",
                pond_id="project-parameters",
                filter_code="const items = data?.data || []; return '参数数量：' + items.length",
            ),
            _build_text_component(
                "首个参数：-",
                x=120,
                y=318,
                w=860,
                h=56,
                font_size=24,
                color="#dfe7ea",
                pond_id="project-parameters",
                filter_code="const items = data?.data || []; const head = items[0] || {}; return '首个参数：' + (head.name || '-')",
            ),
            _build_text_component(
                "该模板适合继续扩展参数分组卡片、运行窗口和默认值对比布局。",
                x=120,
                y=410,
                w=1100,
                h=56,
                font_size=22,
                color="#9fb1b8",
            ),
        ]
    if template_key == "result-analysis":
        components = [
            _build_text_component(
                "Result Analysis",
                x=120,
                y=96,
                w=760,
                h=88,
                font_size=50,
                color="#eef1ff",
                weight="bold",
            ),
            _build_text_component(
                "最新任务：无",
                x=120,
                y=238,
                w=760,
                h=64,
                font_size=28,
                color="#8dd5ff",
                pond_id="project-latest-task",
                filter_code="return '最新任务：' + (data?.data?.name || '无')",
            ),
            _build_text_component(
                "任务状态：-",
                x=120,
                y=314,
                w=520,
                h=56,
                font_size=24,
                color="#aef4c5",
                pond_id="project-latest-task",
                filter_code="return '任务状态：' + (data?.data?.status || '-')",
            ),
            _build_text_component(
                "该模板面向指标、时序曲线和分析叙述发布，已预置最新任务语义数据源。",
                x=120,
                y=410,
                w=1200,
                h=56,
                font_size=22,
                color="#adb6d5",
            ),
        ]
        if latest_task_id:
            components.extend([
                _build_tricys_metrics_component(
                    x=980,
                    y=212,
                    w=520,
                    h=260,
                    task_id=latest_task_id,
                    metrics=["efficiency", "max_temp"],
                    font_size=26,
                    color="#edf6ff",
                ),
            ])
        return components
    return []


def list_project_page_templates() -> List[Dict[str, Any]]:
    return [
        {
            "template_key": "project-overview",
            "page_type": "overview",
            "default_page_name": "Project Overview",
            "title": "Project Overview",
            "description": "A project landing page for model context, latest tasks, and overall platform presentation.",
        },
        {
            "template_key": "parameter-board",
            "page_type": "parameters",
            "default_page_name": "Parameter Board",
            "title": "Parameter Board",
            "description": "A parameter-centric page prepared for grouped variables, defaults, overrides, and operating windows.",
        },
        {
            "template_key": "result-analysis",
            "page_type": "analysis",
            "default_page_name": "Result Analysis",
            "title": "Result Analysis",
            "description": "A results-oriented page for analysis narratives, metrics, time series, and published conclusions.",
        },
        {
            "template_key": "blank",
            "page_type": "custom",
            "default_page_name": "Blank Page",
            "title": "Blank Page",
            "description": "A clean canvas for fully custom project presentation layouts.",
        },
    ]


def _build_base_content(project: Project, page_name: str, background: str, theme: str) -> Dict[str, Any]:
    return {
        "editCanvasConfig": {
            "projectName": page_name,
            "width": 1920,
            "height": 1080,
            "filterShow": False,
            "hueRotate": 0,
            "saturate": 1,
            "contrast": 1,
            "brightness": 1,
            "opacity": 1,
            "rotateZ": 0,
            "rotateX": 0,
            "rotateY": 0,
            "skewX": 0,
            "skewY": 0,
            "blendMode": "normal",
            "background": background,
            "backgroundImage": None,
            "selectColor": True,
            "chartThemeColor": theme,
            "chartCustomThemeColorInfo": None,
            "chartThemeSetting": {},
            "vChartThemeName": "vScreenVolcanoBlue",
            "previewScaleType": "full",
        },
        "requestGlobalConfig": json.loads(json.dumps(BASE_REQUEST_GLOBAL_CONFIG)),
        "componentList": [],
        "tricysTemplateMeta": {
            "projectId": project.id,
            "projectName": project.name,
            "templateReady": True,
        },
    }


def build_project_page_template(
    project: Project,
    template_key: str,
    page_name: str,
    latest_task: Optional[Task] = None,
) -> Dict[str, Any]:
    normalized_key = (template_key or "blank").strip().lower()

    if normalized_key == "project-overview":
        content = _build_base_content(project, page_name, "#09141d", "dark")
        remarks = f"Template page for project overview and platform landing content of {project.name}."
        page_type = "overview"
    elif normalized_key == "parameter-board":
        content = _build_base_content(project, page_name, "#10110f", "avocado")
        remarks = f"Template page for grouped parameter presentation of {project.name}."
        page_type = "parameters"
    elif normalized_key == "result-analysis":
        content = _build_base_content(project, page_name, "#0f1018", "gradient")
        remarks = f"Template page for metrics, analysis, and published results of {project.name}."
        page_type = "analysis"
    else:
        content = _build_base_content(project, page_name, "#0b0f14", "dark")
        remarks = f"Blank custom project page for {project.name}."
        page_type = "custom"
        normalized_key = "blank"

    content["requestGlobalConfig"]["requestDataPond"] = [
        _build_data_pond_item("project-summary", "Project Summary", "/data/summary", {"projectId": project.id}),
        _build_data_pond_item("project-tasks", "Project Tasks", "/data/tasks", {"projectId": project.id, "limit": 8}),
        _build_data_pond_item("project-parameters", "Project Parameters", "/data/parameters", {"projectId": project.id}),
        _build_data_pond_item("project-latest-task", "Latest Task", "/data/latest-task", {"projectId": project.id}),
    ]
    content["componentList"] = _build_template_components(normalized_key, project, latest_task=latest_task)
    content["tricysTemplateMeta"]["semanticDataSources"] = [
        source["source_key"] for source in list_project_page_data_sources(project)
    ]
    content["tricysTemplateMeta"]["latestTaskId"] = latest_task.id if latest_task else None

    return {
        "template_key": normalized_key,
        "page_type": page_type,
        "remarks": remarks,
        "content": json.dumps(content),
    }