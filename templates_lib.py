"""Prompt 模板库 — 用户可自定义的提示词模板"""
import json
import os
import time

TEMPLATES_DIR = os.path.expanduser("~/.ai-suite")
TEMPLATES_FILE = os.path.join(TEMPLATES_DIR, "templates.json")
os.makedirs(TEMPLATES_DIR, exist_ok=True)

DEFAULT_TEMPLATES = [
    {"id": "code_review", "name": "🔍 Code Review", "prompt": "请审查以下代码，指出潜在的 bug、安全问题和改进建议：", "category": "开发"},
    {"id": "explain", "name": "💡 通俗解释", "prompt": "请用通俗易懂的语言解释以下内容，就像在给一个 12 岁的孩子讲解：", "category": "学习"},
    {"id": "translate_en", "name": "🌐 翻译英文", "prompt": "请将以下内容翻译为地道的英文：", "category": "翻译"},
    {"id": "translate_zh", "name": "🌐 翻译中文", "prompt": "请将以下内容翻译为流畅的中文：", "category": "翻译"},
    {"id": "write_email", "name": "📧 写邮件", "prompt": "请帮我写一封专业的邮件，语气友好但正式：", "category": "写作"},
    {"id": "summarize", "name": "📋 摘要", "prompt": "请用 3-5 个要点总结以下内容的核心信息：", "category": "学习"},
    {"id": "bug_fix", "name": "🐛 修 Bug", "prompt": "以下代码有 bug，请分析原因并给出修复方案：", "category": "开发"},
    {"id": "refactor", "name": "♻️ 重构", "prompt": "请重构以下代码，提高可读性和可维护性，保持功能不变：", "category": "开发"},
    {"id": "write_test", "name": "🧪 写测试", "prompt": "请为以下代码编写全面的单元测试：", "category": "开发"},
    {"id": "brainstorm", "name": "🧠 头脑风暴", "prompt": "请围绕以下主题进行头脑风暴，给出 10 个创意方向：", "category": "创意"},
]


def load_templates() -> list:
    """加载模板列表"""
    if os.path.exists(TEMPLATES_FILE):
        try:
            with open(TEMPLATES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # 首次初始化
    save_templates(DEFAULT_TEMPLATES)
    return list(DEFAULT_TEMPLATES)


def save_templates(templates: list):
    """保存模板列表"""
    with open(TEMPLATES_FILE, "w", encoding="utf-8") as f:
        json.dump(templates, f, ensure_ascii=False, indent=2)


def add_template(name: str, prompt: str, category: str = "自定义") -> dict:
    """添加新模板"""
    templates = load_templates()
    tid = f"tpl_{int(time.time())}"
    tpl = {"id": tid, "name": name, "prompt": prompt, "category": category}
    templates.append(tpl)
    save_templates(templates)
    return tpl


def delete_template(tid: str) -> bool:
    """删除模板"""
    templates = load_templates()
    new_list = [t for t in templates if t["id"] != tid]
    if len(new_list) == len(templates):
        return False
    save_templates(new_list)
    return True
