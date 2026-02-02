from typing import List, Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Body
from tricys_backend.api.deps import get_current_user
from tricys_backend.models.user import User
from tricys_backend.models.task import Task
from tricys_backend.services.analysis_service import AnalysisService

from tricys_backend.services.analysis_templates import AnalysisTemplates

router = APIRouter()

@router.get("/templates")
def get_analysis_templates():
    """Get available analysis configuration templates."""
    return AnalysisTemplates.get_templates()

@router.get("/tasks", response_model=List[Task])
def list_tasks(
    project_id: str = None,
    current_user: User = Depends(get_current_user)
):
    """
    List all analysis tasks for the current user, optionally filtered by project.
    """
    return AnalysisService.get_tasks(current_user.id, project_id)

@router.post("/submit")
async def submit_analysis(
    project_id: str = Body(..., embed=True),
    name: str = Body(..., embed=True),
    config: Dict[str, Any] = Body(..., embed=True),
    template_id: str = Body(None, embed=True),
    current_user: User = Depends(get_current_user)
):
    """
    Submit a new analysis task.
    If template_id is provided, 'config' is treated as form data for that template.
    Otherwise 'config' is treated as raw analysis configuration.
    """
    # Create Task Record
    task = AnalysisService.create_analysis_task(current_user.id, project_id, name, config, template_id)
    
    # Enqueue
    await AnalysisService.submit_task(task.id)
    
    return {"status": "submitted", "task_id": task.id}

@router.get("/tasks/{task_id}", response_model=Task)
def get_task(
    task_id: int,
    current_user: User = Depends(get_current_user)
):
    task = AnalysisService.get_task(task_id, current_user.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: int,
    current_user: User = Depends(get_current_user)
):
    success = AnalysisService.delete_task(task_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "deleted"}

@router.get("/tasks/{task_id}/report")
def get_task_report(
    task_id: int,
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve the markdown report content for a completed analysis task.
    """
    task = AnalysisService.get_task(task_id, current_user.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    if task.status != "COMPLETED":
         raise HTTPException(status_code=400, detail="Task not completed yet")

    # Read the report file from the task's result path
    # Assuming task.result_path points to the output directory
    # We need to find the .md report file there.
    
    import os
    from pathlib import Path
    
    if not task.result_path or not os.path.exists(task.result_path):
        return {"content": "# Report not found\nResult path does not exist."}
        
    # Search for report file
    try:
        result_dir = Path(task.result_path)
        # Usually report is analysis_report_{name}.md or similar
        # Let's simple look for any .md file that contains "report"
        report_files = list(result_dir.glob("*report*.md"))
        
        if not report_files:
             # Fallback: look for any .md
             report_files = list(result_dir.glob("*.md"))
             
        if report_files:
            # Pick the first one for now, or prefer 'analysis_report'
            target = report_files[0]
            for f in report_files:
                if "analysis_report" in f.name:
                    target = f
                    break
            
            return {"content": target.read_text(encoding='utf-8')}
            
    except Exception as e:
        return {"content": f"# Error reading report\n{str(e)}"}

    return {"content": "# Report not generated yet."}
