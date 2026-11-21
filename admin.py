"""
Admin and Sudo management module for Kiwi Telegram Bot
Handles Owner, Sudo Admins, Group tracking, and System Stats.
"""

import os
import json
import time
import logging
from pathlib import Path
from typing import Dict, Any, Set, Optional

from config import OWNER_ID, DATA_DIR, SUDO_FILE, STATS_FILE

logger = logging.getLogger(__name__)

# Small Caps mapping table for aesthetic Telegram UI styling
SMALL_CAPS_TABLE = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ",
)


def sc(text: str) -> str:
    """Convert text to Unicode Small Caps, preserving non-alphabet characters and tags."""
    return text.translate(SMALL_CAPS_TABLE)


BOT_START_TIME = time.time()
_sudoers_cache: Dict[str, Any] = {}
_stats_cache: Dict[str, Any] = {}


def init_storage():
    """Ensure data files exist with defaults"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SUDO_FILE.exists():
        data = {
            "owner_id": OWNER_ID,
            "sudo_users": [],
        }
        with open(SUDO_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    if not STATS_FILE.exists():
        stats = {
            "users": {},
            "groups": {},
            "total_downloads": 0,
        }
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)


def get_sudo_data() -> Dict[str, Any]:
    global _sudoers_cache
    if not _sudoers_cache:
        init_storage()
        try:
            with open(SUDO_FILE, "r", encoding="utf-8") as f:
                _sudoers_cache = json.load(f)
        except Exception as e:
            logger.error(f"Error loading sudoers: {e}")
            _sudoers_cache = {"owner_id": OWNER_ID, "sudo_users": []}

    # If owner was specified in config/.env, sync it
    if OWNER_ID and _sudoers_cache.get("owner_id") != OWNER_ID:
        _sudoers_cache["owner_id"] = OWNER_ID

    return _sudoers_cache


def save_sudo_data(data: Dict[str, Any]):
    global _sudoers_cache
    _sudoers_cache = data
    try:
        with open(SUDO_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving sudoers: {e}")


def get_owner_id() -> int:
    data = get_sudo_data()
    return int(data.get("owner_id") or OWNER_ID or 0)


def set_owner_id(owner_id: int):
    data = get_sudo_data()
    data["owner_id"] = owner_id
    save_sudo_data(data)


def get_sudo_users() -> Set[int]:
    data = get_sudo_data()
    return set(int(uid) for uid in data.get("sudo_users", []))


def is_owner(user_id: int) -> bool:
    owner_id = get_owner_id()
    if owner_id == 0:
        return False
    return user_id == owner_id


def is_sudo(user_id: int) -> bool:
    if is_owner(user_id):
        return True
    return user_id in get_sudo_users()


def add_sudo_user(user_id: int) -> bool:
    data = get_sudo_data()
    sudos = set(int(u) for u in data.get("sudo_users", []))
    if user_id in sudos:
        return False
    sudos.add(user_id)
    data["sudo_users"] = sorted(list(sudos))
    save_sudo_data(data)
    return True


def remove_sudo_user(user_id: int) -> bool:
    data = get_sudo_data()
    sudos = set(int(u) for u in data.get("sudo_users", []))
    if user_id not in sudos:
        return False
    sudos.remove(user_id)
    data["sudo_users"] = sorted(list(sudos))
    save_sudo_data(data)
    return True


def get_stats_data() -> Dict[str, Any]:
    global _stats_cache
    if not _stats_cache:
        init_storage()
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                _stats_cache = json.load(f)
        except Exception as e:
            logger.error(f"Error loading stats: {e}")
            _stats_cache = {"users": {}, "groups": {}, "total_downloads": 0}
    return _stats_cache


def save_stats_data():
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(_stats_cache, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving stats: {e}")


def track_activity(chat_id: int, chat_type: str, title: str = "", user_id: Optional[int] = None, user_name: str = ""):
    """Track active groups and users for stats"""
    stats = get_stats_data()
    now = time.time()
    changed = False

    if chat_type in ["group", "supergroup"]:
        groups = stats.setdefault("groups", {})
        cid = str(chat_id)
        if cid not in groups or groups[cid].get("title") != title:
            changed = True
        groups[cid] = {
            "title": title or f"Group {chat_id}",
            "last_active": now,
        }

    if user_id:
        users = stats.setdefault("users", {})
        uid = str(user_id)
        if uid not in users:
            changed = True
        users[uid] = {
            "name": user_name or f"User {user_id}",
            "last_active": now,
        }

    if changed:
        save_stats_data()


def increment_download_count():
    stats = get_stats_data()
    stats["total_downloads"] = stats.get("total_downloads", 0) + 1
    save_stats_data()


def format_uptime(seconds: float) -> str:
    secs = int(seconds)
    days, secs = divmod(secs, 86400)
    hours, secs = divmod(secs, 3600)
    mins, secs = divmod(secs, 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0 or days > 0:
        parts.append(f"{hours}h")
    if mins > 0 or hours > 0 or days > 0:
        parts.append(f"{mins}m")
    parts.append(f"{secs}s")
    return " ".join(parts)
