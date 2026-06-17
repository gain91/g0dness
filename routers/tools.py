"""
Tools Router — 工具和 Skills API
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["tools"])

# 工具导入
try:
    from tools import list_tools, execute as tool_execute
    HAS_TOOLS = True
except:
    HAS_TOOLS = False

# Skills 导入
try:
    from plugin_manager import pm
    HAS_SKILLS = True
except:
    HAS_SKILLS = False
    pm = None


@router.get("/tools")
async def list_available_tools():
    """列出可用工具"""
    if not HAS_TOOLS:
        return {"tools": []}
    return {"tools": list_tools()}


@router.post("/tools/{tool_name}")
async def execute_tool(tool_name: str, request: Request):
    """执行工具"""
    if not HAS_TOOLS:
        return JSONResponse({"ok": False, "error": "tools not available"}, 500)
    try:
        args = await request.json()
    except:
        args = {}
    try:
        result = tool_execute(tool_name, args)
        return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/skills")
async def list_skills():
    """列出可用 Skills"""
    if not HAS_SKILLS:
        return {"skills": []}
    return {"skills": pm.list_skills()}


@router.post("/skills/{skill_name}")
async def execute_skill(skill_name: str, request: Request):
    """执行 Skill"""
    if not HAS_SKILLS:
        return JSONResponse({"ok": False, "error": "skills not available"}, 500)
    try:
        data = await request.json()
        result = pm.execute_skill(skill_name, data)
        return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/audit/tools")
async def audit_tools():
    """工具审计日志"""
    import os
    log_path = "logs/tool_audit.jsonl"
    if not os.path.exists(log_path):
        return {"logs": []}
    try:
        logs = []
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    import json
                    logs.append(json.loads(line))
                except:
                    pass
        return {"logs": logs[-100:]}  # 最后100条
    except Exception as e:
        return {"logs": [], "error": str(e)}
