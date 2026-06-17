"""
Conversations Router — 对话管理 API
"""
from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

# 数据库导入
try:
    from db import list_convs, create_conv, delete_conv, add_message, get_messages, clear_messages, search_messages
    HAS_DB = True
except:
    HAS_DB = False


@router.get("")
async def list_conversations():
    """列出所有对话"""
    if not HAS_DB:
        return {"convs": []}
    return {"convs": list_convs()}


@router.post("")
async def create_conversation(request: Request):
    """创建新对话"""
    if not HAS_DB:
        return JSONResponse({"error": "db not available"}, 500)
    data = await request.json() or {}
    cid = create_conv(title=data.get("title", "New Chat"), model=data.get("model", "ollama"))
    return {"id": cid}


@router.get("/{cid}/messages")
async def get_conversation_messages(cid: str):
    """获取对话消息"""
    if not HAS_DB:
        return {"messages": []}
    return {"messages": get_messages(cid)}


@router.post("/{cid}/messages")
async def add_conversation_message(cid: str, request: Request):
    """添加消息到对话"""
    if not HAS_DB:
        return {"ok": True}
    data = await request.json()
    add_message(cid, data.get("role", "user"), data.get("content", ""), data.get("tokens", 0))
    return {"ok": True}


@router.delete("/{cid}")
async def delete_conversation(cid: str):
    """删除对话"""
    if not HAS_DB:
        return {"ok": True}
    delete_conv(cid)
    return {"ok": True}


@router.delete("/{cid}/messages")
async def clear_conversation_messages(cid: str):
    """清空对话消息"""
    if not HAS_DB:
        return {"ok": True}
    clear_messages(cid)
    return {"ok": True}


@router.get("/search")
async def search_conversations(q: str = Query("")):
    """搜索对话内容"""
    if not q or not HAS_DB:
        return {"results": []}
    return {"results": search_messages(q)}
