"""
Templates Router — 模板管理 API
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/templates", tags=["templates"])

# 模板存储路径
import os
import json
from typing import List, Dict

TEMPLATES_FILE = os.path.expanduser("~/.ai-suite/templates.json")


def _load_templates() -> List[Dict]:
    """加载模板列表"""
    if not os.path.exists(TEMPLATES_FILE):
        return []
    try:
        with open(TEMPLATES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def _save_templates(templates: List[Dict]):
    """保存模板列表"""
    os.makedirs(os.path.dirname(TEMPLATES_FILE), exist_ok=True)
    with open(TEMPLATES_FILE, "w", encoding="utf-8") as f:
        json.dump(templates, f, ensure_ascii=False, indent=2)


@router.get("")
async def list_templates():
    """列出所有模板"""
    return {"templates": _load_templates()}


@router.post("")
async def create_template(request: Request):
    """创建新模板"""
    try:
        data = await request.json()
        templates = _load_templates()

        # 生成新 ID
        new_id = str(int(time.time() * 1000))
        template = {
            "id": new_id,
            "name": data.get("name", "Untitled"),
            "content": data.get("content", ""),
            "created_at": new_id,
            "updated_at": new_id
        }

        templates.append(template)
        _save_templates(templates)
        return {"ok": True, "template": template}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 400)


@router.delete("/{template_id}")
async def delete_template(template_id: str):
    """删除模板"""
    try:
        templates = _load_templates()
        templates = [t for t in templates if t.get("id") != template_id]
        _save_templates(templates)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 400)
