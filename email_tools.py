"""
AI Suite — Email & Calendar Tools (v4.0)
Windows Outlook 集成：发邮件、读邮件、日历、联系人
依赖: pywin32 (Windows Outlook COM)
"""

import os, json, time
from typing import Optional

HAS_OUTLOOK = False
try:
    import win32com.client
    HAS_OUTLOOK = True
except ImportError:
    pass

# ═══════ Helpers ═══════

def _get_outlook():
    if not HAS_OUTLOOK:
        return None
    try:
        return win32com.client.Dispatch("Outlook.Application")
    except:
        return None

# ═══════ Email Tools ═══════

def tool_send_email(to: str, subject: str, body: str,
                    cc: str = "", bcc: str = "", attachments: str = "[]"):
    """发送邮件。attachments: JSON 数组路径列表"""
    outlook = _get_outlook()
    if not outlook:
        return {"ok": False, "error": "Outlook 不可用。安装 pywin32 并确保 Outlook 已配置。"}
    try:
        mail = outlook.CreateItem(0)  # 0 = olMailItem
        mail.To = to
        mail.Subject = subject
        mail.Body = body
        if cc:
            mail.CC = cc
        if bcc:
            mail.BCC = bcc
        # Attachments
        try:
            att_list = json.loads(attachments) if isinstance(attachments, str) else attachments
            for path in att_list:
                if os.path.exists(path):
                    mail.Attachments.Add(path)
        except:
            pass
        mail.Send()
        return {"ok": True, "to": to, "subject": subject}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tool_read_emails(folder: str = "Inbox", limit: int = 20, unread_only: bool = False):
    """读取邮件"""
    outlook = _get_outlook()
    if not outlook:
        return {"ok": False, "error": "Outlook 不可用"}
    try:
        namespace = outlook.GetNamespace("MAPI")
        inbox = namespace.GetDefaultFolder({"Inbox": 6, "Sent": 5, "Drafts": 16}.get(folder, 6))
        messages = inbox.Items
        messages.Sort("[ReceivedTime]", True)  # newest first
        results = []
        count = 0
        for msg in messages:
            if count >= limit:
                break
            if unread_only and not msg.UnRead:
                continue
            results.append({
                "subject": msg.Subject,
                "sender": msg.SenderName,
                "received": str(msg.ReceivedTime),
                "unread": msg.UnRead,
                "body_preview": (msg.Body or "")[:200]
            })
            count += 1
        return {"ok": True, "folder": folder, "count": len(results), "emails": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ═══════ Calendar Tools ═══════

def tool_list_calendar(days: int = 7):
    """列出日历事件"""
    outlook = _get_outlook()
    if not outlook:
        return {"ok": False, "error": "Outlook 不可用"}
    try:
        namespace = outlook.GetNamespace("MAPI")
        calendar = namespace.GetDefaultFolder(9)  # 9 = olFolderCalendar
        items = calendar.Items
        items.Sort("[Start]")
        items.IncludeRecurrences = True
        now = time.time()
        cutoff = now + days * 86400
        results = []
        for appt in items:
            try:
                start_ts = appt.Start.timestamp()
                if start_ts > cutoff:
                    break
                if start_ts < now:
                    continue
                results.append({
                    "subject": appt.Subject,
                    "start": str(appt.Start),
                    "end": str(appt.End),
                    "location": appt.Location or "",
                    "duration_min": appt.Duration
                })
            except:
                pass
        return {"ok": True, "days": days, "count": len(results), "events": results[:50]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tool_create_event(subject: str, start_iso: str, duration_min: int = 60, location: str = ""):
    """创建日历事件。start_iso: '2026-06-12 15:00'"""
    outlook = _get_outlook()
    if not outlook:
        return {"ok": False, "error": "Outlook 不可用"}
    try:
        import datetime
        start_dt = datetime.datetime.fromisoformat(start_iso)
        appt = outlook.CreateItem(1)  # 1 = olAppointmentItem
        appt.Subject = subject
        appt.Start = start_dt.strftime("%Y-%m-%d %H:%M")
        appt.Duration = duration_min
        if location:
            appt.Location = location
        appt.Save()
        return {"ok": True, "subject": subject, "start": start_iso}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ═══════ Contact Tools ═══════

def tool_search_contacts(query: str, limit: int = 20):
    """搜索联系人"""
    outlook = _get_outlook()
    if not outlook:
        return {"ok": False, "error": "Outlook 不可用"}
    try:
        namespace = outlook.GetNamespace("MAPI")
        contacts_folder = namespace.GetDefaultFolder(10)  # olFolderContacts
        results = []
        for contact in contacts_folder.Items:
            if len(results) >= limit:
                break
            full = f"{contact.FullName or ''} {contact.Email1Address or ''} {contact.CompanyName or ''}".lower()
            if query.lower() in full:
                results.append({
                    "name": contact.FullName,
                    "email": contact.Email1Address or "",
                    "phone": contact.MobileTelephoneNumber or contact.BusinessTelephoneNumber or ""
                })
        return {"ok": True, "count": len(results), "contacts": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════ Register into tools system ═══════

def register_email_tools():
    import tools
    if HAS_OUTLOOK:
        tools.register("send_email", "Send an email via Outlook", tool_send_email,
                       {"to": {"type": "string"}, "subject": {"type": "string"},
                        "body": {"type": "string"}, "cc": {"type": "string", "optional": True},
                        "bcc": {"type": "string", "optional": True},
                        "attachments": {"type": "string", "optional": True}})
        tools.register("read_emails", "Read emails from Outlook inbox", tool_read_emails,
                       {"folder": {"type": "string", "optional": True},
                        "limit": {"type": "integer", "optional": True},
                        "unread_only": {"type": "boolean", "optional": True}})
        tools.register("list_calendar", "List upcoming calendar events", tool_list_calendar,
                       {"days": {"type": "integer", "optional": True}})
        tools.register("create_event", "Create a calendar event", tool_create_event,
                       {"subject": {"type": "string"}, "start_iso": {"type": "string"},
                        "duration_min": {"type": "integer", "optional": True},
                        "location": {"type": "string", "optional": True}})
        tools.register("search_contacts", "Search Outlook contacts", tool_search_contacts,
                       {"query": {"type": "string"}, "limit": {"type": "integer", "optional": True}})
        return True
    return False
