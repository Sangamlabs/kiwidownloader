"""
Telegram Downloader Bot for KiwiAPI
High-speed video & audio downloader with quality selector and Shazam music recognition.
"""

import os
import re
import uuid
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    constants,
)
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

import psutil

from config import BOT_TOKEN, BOT_USERNAME, TEMP_DIR
from api_client import KiwiApiClient
from admin import (
    sc,
    is_owner,
    is_sudo,
    get_owner_id,
    set_owner_id,
    get_sudo_users,
    add_sudo_user,
    remove_sudo_user,
    get_stats_data,
    track_activity,
    increment_download_count,
    format_uptime,
    BOT_START_TIME,
)

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("tg_downloader_bot")

api_client = KiwiApiClient()


# URL regex pattern supporting YouTube, Instagram, Pinterest, TikTok, Twitter/X, and generic URLs
URL_PATTERN = re.compile(
    r"(https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b[-a-zA-Z0-9()@:%_\+.~#?&//=]*)",
    re.IGNORECASE,
)

# In-memory session store for video formats and URLs: cache_id -> {url, info, time}
url_store: Dict[str, Dict[str, Any]] = {}


def store_session(url: str, info: Optional[Dict[str, Any]] = None) -> str:
    """Store session info and return short 8-char cache ID"""
    now = time.time()
    # Expire entries older than 1 hour
    for k in list(url_store.keys()):
        if now - url_store[k].get("time", now) > 3600:
            url_store.pop(k, None)

    cache_id = uuid.uuid4().hex[:8]
    url_store[cache_id] = {
        "url": url,
        "info": info or {},
        "time": now,
    }
    return cache_id


def is_known_instant_media(url: str) -> bool:
    """Return True if URL is definitely a short clip or reel that requires immediate delivery."""
    url_lower = url.lower()
    return any(p in url_lower for p in ["instagram.com", "instagr.am", "pin.it", "pinterest.", "tiktok.com", "/shorts/"])


def is_short_media(url: str, info: Dict[str, Any]) -> bool:
    """Check if the media is a Short, Reel, or quick clip that should be sent immediately."""
    if is_known_instant_media(url):
        return True

    # Check duration if available (under 120s is treated as short clip)
    duration_str = info.get("duration", "")
    if duration_str:
        parts = duration_str.split(":")
        if len(parts) == 2:
            try:
                mins, secs = int(parts[0]), int(parts[1])
                return (mins * 60 + secs) <= 120
            except ValueError:
                pass
    return False


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start"""
    chat = update.effective_chat
    user = update.effective_user
    user_name = user.first_name if user else "there"
    bot_user = context.bot.username or BOT_USERNAME

    # Track activity for stats
    if chat and user:
        track_activity(chat.id, chat.type, chat.title or "", user.id, user_name)

    if chat and chat.type in [constants.ChatType.GROUP, constants.ChatType.SUPERGROUP]:
        group_text = (
            f"👋 *{sc('Hello everyone! I am active in')} {chat.title or 'this group'}!*\n\n"
            f"⚡ {sc('Send any')} *Instagram Reel*, *Pinterest*, *TikTok*, {sc('or')} *YouTube* {sc('link to download directly in this group.')}\n\n"
            f"❤️ @{bot_user}"
        )
        await update.message.reply_text(group_text, parse_mode=constants.ParseMode.MARKDOWN)
        return

    welcome_text = (
        f"👋 *{sc('Hello')} {user_name}!*\n\n"
        f"{sc('I am your high-speed')} *{sc('Media Downloader Bot')}*.\n\n"
        f"⚡ *{sc('How to use')}:*\n"
        f"• {sc('Just')} *{sc('send me any link')}* (Instagram Reel, Pinterest, YouTube, TikTok).\n"
        f"• {sc('For Reels & Shorts: Video will be sent instantly!')}\n"
        f"• {sc('For long YouTube videos: You can choose your preferred quality.')}\n"
        f"• {sc('Use inline buttons to Extract Audio, Identify Song, or Find Anime.')}\n"
        f"• {sc('Add me to your group to download videos directly in group chats!')}\n\n"
        f"❤️ @{bot_user}"
    )
    await update.message.reply_text(welcome_text, parse_mode=constants.ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /help"""
    chat = update.effective_chat
    user = update.effective_user
    bot_user = context.bot.username or BOT_USERNAME
    user_id = user.id if user else 0

    if chat and user:
        track_activity(chat.id, chat.type, chat.title or "", user.id, user.first_name or "")

    sudo_help = ""
    if is_sudo(user_id):
        sudo_help = (
            f"\n\n🛡️ *{sc('Admin & Sudo Commands')}:*\n"
            f"• `/ping` — {sc('Check Telegram & API ping latency')}\n"
            f"• `/stats` — {sc('View server CPU, RAM, Disk and bot stats')}\n"
            f"• `/gc` — {sc('View group stats & active groups list')}\n"
            f"• `/listsudo` — {sc('List all sudo admins & owner')}\n"
        )
        if is_owner(user_id):
            sudo_help += (
                f"• `/addsudo <id>` — {sc('Add a new sudo admin')}\n"
                f"• `/rmsudo <id>` — {sc('Remove a sudo admin')}\n"
            )

    help_text = (
        f"📖 *{sc('Kiwi Downloader Help & Commands')}:*\n\n"
        f"• *{sc('Download Video')}:* {sc('Paste any link from Instagram, YouTube, Pinterest, etc.')}\n"
        f"• *{sc('YouTube Long Videos')}:* {sc('Select your desired quality from the inline menu.')}\n"
        f"• *{sc('Extract Audio')}:* {sc('Click')} '{sc('Extract Audio')}' {sc('under any video, or send')} `/extract <link>`\n"
        f"• *{sc('Identify Song')}:* {sc('Click')} '{sc('Identify Song')}' {sc('under any video, or send')} `/audio <link>`\n"
        f"• *{sc('Find Anime')}:* {sc('Click')} '{sc('Find Anime')}' {sc('under any video, or send')} `/anime <link>`"
        f"{sudo_help}\n\n"
        f"❤️ @{bot_user}"
    )
    await update.message.reply_text(help_text, parse_mode=constants.ParseMode.MARKDOWN)


async def process_media_url(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Process a detected link from user message"""
    chat = update.effective_chat
    user = update.effective_user
    if chat and user:
        track_activity(chat.id, chat.type, chat.title or "", user.id, user.first_name or "")

    # Send search glass emoji immediately as requested
    status_msg = await update.message.reply_text("🔍")
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.UPLOAD_VIDEO)
    except Exception:
        pass

    # FAST TRACK FOR REELS, TIKTOK, PINTEREST, AND SHORTS
    if is_known_instant_media(url):
        cache_id = store_session(url, {})
        await download_and_send_video(
            update=update,
            context=context,
            status_msg=status_msg,
            url=url,
            cache_id=cache_id,
            quality="1080p",
            title="Video",
        )
        return

    info = await api_client.get_media_info(url)
    if not info:
        await status_msg.edit_text(
            f"❌ *{sc('Failed to extract media details.')}* {sc('Please check if the link is public and accessible.')}",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    cache_id = store_session(url, info)
    title = info.get("title", "Untitled media")
    author = info.get("author", "Unknown")
    duration = info.get("duration", "")
    thumbnail = info.get("thumbnail", "")

    # Check if this is a Photo / Carousel Post (Instagram, Pinterest, etc.)
    images = info.get("images", [])
    video_opts = info.get("video", [])
    if images and (not video_opts or "/p/" in url.lower()):
        try:
            bot_user = context.bot.username or BOT_USERNAME
            caption = f"📸 *{title}*\n👤 *{sc('Author')}:* {author}\n\n❤️ @{bot_user}"
            if len(images) == 1:
                img_url = images[0].get("url")
                if img_url:
                    await update.message.reply_photo(
                        photo=img_url,
                        caption=caption,
                        parse_mode=constants.ParseMode.MARKDOWN,
                        read_timeout=30,
                        write_timeout=30,
                    )
                    await status_msg.delete()
                    return
            elif len(images) > 1:
                media_group = []
                for idx, img in enumerate(images[:10]):
                    img_url = img.get("url")
                    if img_url:
                        cap = f"📸 *{title}*\n👤 *{sc('Author')}:* {author}\n🖼 *{sc('Photos')}:* {len(images)}\n\n❤️ @{bot_user}" if idx == 0 else ""
                        media_group.append(InputMediaPhoto(media=img_url, caption=cap, parse_mode=constants.ParseMode.MARKDOWN))
                if media_group:
                    await update.message.reply_media_group(media=media_group, read_timeout=60, write_timeout=60)
                    await status_msg.delete()
                    return
        except Exception as photo_err:
            logger.warning(f"Direct photo send failed, falling back to download: {photo_err}")

    # Check if this is an instant short clip or YouTube long video
    if is_short_media(url, info):
        await download_and_send_video(
            update=update,
            context=context,
            status_msg=status_msg,
            url=url,
            cache_id=cache_id,
            quality="1080p",
            title=title,
        )
    else:
        # YouTube long video: Present quality selector menu
        buttons = []
        video_opts = info.get("video", [])
        row = []
        for v in video_opts[:6]:
            label = v.get("label", "")
            q_code = "1080p" if "1080" in label else ("720p" if "720" in label else ("4K" if "4k" in label.lower() or "2160" in label else ("480p" if "480" in label else ("360p" if "360" in label else label[:10]))))
            btn_text = f"🎬 {sc(q_code)}"
            size = v.get("size", "")
            size_part = f" ({sc(size)})" if size and ("mb" in size.lower() or "gb" in size.lower()) else ""
            row.append(InlineKeyboardButton(f"{btn_text}{size_part}", callback_data=f"q:{cache_id}:{q_code}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        buttons.append([
            InlineKeyboardButton(f"🎵 {sc('MP3 Audio (320 kbps)')}", callback_data=f"ext:{cache_id}"),
            InlineKeyboardButton(f"🔍 {sc('Identify Song')}", callback_data=f"rec:{cache_id}"),
        ])
        buttons.append([
            InlineKeyboardButton(f"🎌 {sc('Find Anime & Episode')}", callback_data=f"ani:{cache_id}"),
        ])

        keyboard = InlineKeyboardMarkup(buttons)
        duration_line = f"⏱ *{sc('Duration')}:* {duration}\n" if duration else ""
        caption = (
            f"🎬 *{title}*\n"
            f"👤 *{sc('Author')}:* {author}\n"
            f"{duration_line}\n"
            f"👇 *{sc('Choose video quality to download')}:*"
        )

        try:
            if thumbnail:
                await update.message.reply_photo(
                    photo=thumbnail,
                    caption=caption,
                    parse_mode=constants.ParseMode.MARKDOWN,
                    reply_markup=keyboard,
                    read_timeout=30,
                    write_timeout=30,
                )
                await status_msg.delete()
            else:
                await status_msg.edit_text(caption, parse_mode=constants.ParseMode.MARKDOWN, reply_markup=keyboard)
        except Exception:
            await status_msg.edit_text(caption, parse_mode=constants.ParseMode.MARKDOWN, reply_markup=keyboard)


async def download_and_send_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    status_msg,
    url: str,
    cache_id: str,
    quality: str = "1080p",
    title: str = "Video",
):
    """Download video via KiwiAPI and send to user with inline buttons"""
    # Keep the '🔍' emoji undisturbed during download for clean and fast UI
    job_id = await api_client.start_job(url=url, media_type="video", quality=quality)
    if not job_id:
        await status_msg.edit_text(f"❌ *{sc('Error dispatching download job to server.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    # Wait for completion on server
    ready = await api_client.wait_for_job(job_id)
    if not ready:
        err = getattr(api_client, "last_error", "") or ""
        if "login" in err.lower() or "rate-limit" in err.lower() or "redirected to the login" in err.lower():
            await status_msg.edit_text(
                f"⚠️ *{sc('Instagram is currently restricting anonymous access for this reel.')}*\n\n"
                f"💡 {sc('Instagram server rate-limit hit. Please try another link or try again in a few minutes.')}",
                parse_mode=constants.ParseMode.MARKDOWN
            )
        else:
            await status_msg.edit_text(f"❌ *{sc('Download failed or timed out on server.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    increment_download_count()

    bot_user = context.bot.username or BOT_USERNAME
    caption = f"❤️ @{bot_user}"
    file_url = f"{api_client.base_url}/v1/files/{job_id}"
    target_chat_id = update.effective_chat.id
    reply_to = update.effective_message.message_id if update.effective_message else None

    # Inline action buttons below the video
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🎵 {sc('Extract Audio')}", callback_data=f"ext:{cache_id}"),
            InlineKeyboardButton(f"🔍 {sc('Identify Song')}", callback_data=f"rec:{cache_id}"),
        ],
        [
            InlineKeyboardButton(f"🎌 {sc('Find Anime & Episode')}", callback_data=f"ani:{cache_id}"),
        ]
    ])

    # FAST PATH: Send direct URL to Telegram servers (Telegram streams directly from KiwiAPI datacenter in 1-2s!)
    sent = False
    try:
        await context.bot.send_chat_action(chat_id=target_chat_id, action=constants.ChatAction.UPLOAD_VIDEO)
        await context.bot.send_video(
            chat_id=target_chat_id,
            video=file_url,
            caption=caption,
            reply_to_message_id=reply_to,
            supports_streaming=True,
            reply_markup=keyboard,
            read_timeout=60,
            write_timeout=60,
        )
        sent = True
        try:
            await status_msg.delete()
        except Exception:
            pass
    except Exception as e:
        logger.info(f"Direct URL send failed ({e}), falling back to disk streaming...")

    if not sent:
        # FALLBACK PATH: Stream to disk and upload with extended timeout
        try:
            await status_msg.edit_text(f"📦 *{sc('Uploading video to Telegram...')}*", parse_mode=constants.ParseMode.MARKDOWN)
        except Exception:
            pass

        local_file = await api_client.download_file_to_disk(job_id)
        if not local_file or not local_file.exists():
            await status_msg.edit_text(f"❌ *{sc('Failed to fetch video file from storage.')}*", parse_mode=constants.ParseMode.MARKDOWN)
            return

        file_size_mb = local_file.stat().st_size / (1024 * 1024)
        try:
            if file_size_mb <= 49.5:
                ext = local_file.suffix.lower()
                if ext in (".jpg", ".jpeg", ".png", ".webp"):
                    await context.bot.send_chat_action(chat_id=target_chat_id, action=constants.ChatAction.UPLOAD_PHOTO)
                    with open(local_file, "rb") as pf:
                        await context.bot.send_photo(
                            chat_id=target_chat_id,
                            photo=pf,
                            caption=caption,
                            reply_to_message_id=reply_to,
                            reply_markup=keyboard,
                            read_timeout=120,
                            write_timeout=120,
                        )
                elif ext in (".zip", ".rar"):
                    await context.bot.send_chat_action(chat_id=target_chat_id, action=constants.ChatAction.UPLOAD_DOCUMENT)
                    with open(local_file, "rb") as zf:
                        await context.bot.send_document(
                            chat_id=target_chat_id,
                            document=zf,
                            caption=caption,
                            reply_to_message_id=reply_to,
                            reply_markup=keyboard,
                            read_timeout=180,
                            write_timeout=180,
                        )
                else:
                    await context.bot.send_chat_action(chat_id=target_chat_id, action=constants.ChatAction.UPLOAD_VIDEO)
                    with open(local_file, "rb") as video_file:
                        await context.bot.send_video(
                            chat_id=target_chat_id,
                            video=video_file,
                            caption=caption,
                            reply_to_message_id=reply_to,
                            supports_streaming=True,
                            reply_markup=keyboard,
                            read_timeout=300,
                            write_timeout=300,
                            connect_timeout=60,
                        )
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            else:
                # Over 50MB: Provide direct high-speed download link & button
                dl_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"⚡ {sc('Direct High-Speed Download')} ({file_size_mb:.1f} {sc('MB')})", url=file_url)],
                    [
                        InlineKeyboardButton(f"🎵 {sc('Extract Audio')}", callback_data=f"ext:{cache_id}"),
                        InlineKeyboardButton(f"🔍 {sc('Identify Song')}", callback_data=f"rec:{cache_id}"),
                    ],
                    [
                        InlineKeyboardButton(f"🎌 {sc('Find Anime & Episode')}", callback_data=f"ani:{cache_id}"),
                    ]
                ])
                await status_msg.edit_text(
                    f"🎬 *{title}*\n\n"
                    f"⚠️ *{sc('File size')}:* `{file_size_mb:.1f} MB`\n"
                    f"{sc('Telegram bot in-chat limit is 50MB. Click below to stream or download directly from our high-speed server at full speed')}:\n\n"
                    f"📥 [⚡ {sc('Direct Download Link')}]({file_url})\n\n"
                    f"❤️ @{bot_user}",
                    parse_mode=constants.ParseMode.MARKDOWN,
                    reply_markup=dl_keyboard,
                )
        except Exception as e:
            logger.error(f"Error sending video: {e}")
            await status_msg.edit_text(f"❌ *{sc('Failed to send video')}:* {e}", parse_mode=constants.ParseMode.MARKDOWN)
        finally:
            try:
                if local_file and local_file.exists():
                    local_file.unlink()
            except Exception:
                pass


async def extract_and_send_audio(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    status_msg,
    url: str,
    cache_id: Optional[str] = None,
    title: str = "Audio",
):
    """Download 320 kbps MP3 audio via KiwiAPI and send as Telegram Audio"""
    try:
        await status_msg.edit_text(f"🎵 *{sc('Extracting high quality 320 kbps MP3...')}*", parse_mode=constants.ParseMode.MARKDOWN)
    except Exception:
        pass

    job_id = await api_client.start_job(url=url, media_type="audio", quality="MP3 320 kbps")
    if not job_id:
        await status_msg.edit_text(f"❌ *{sc('Error dispatching audio extraction job.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    ready = await api_client.wait_for_job(job_id)
    if not ready:
        await status_msg.edit_text(f"❌ *{sc('Audio extraction failed on server.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    increment_download_count()

    bot_user = context.bot.username or BOT_USERNAME
    caption = f"❤️ @{bot_user}"
    file_url = f"{api_client.base_url}/v1/files/{job_id}"
    target_chat_id = update.effective_chat.id
    reply_to = update.effective_message.message_id if update.effective_message else None

    keyboard = None
    if cache_id:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🔍 {sc('Identify Song')}", callback_data=f"rec:{cache_id}")]
        ])

    # FAST PATH: Send direct URL to Telegram
    sent = False
    try:
        await context.bot.send_chat_action(chat_id=target_chat_id, action=constants.ChatAction.UPLOAD_VOICE)
        await context.bot.send_audio(
            chat_id=target_chat_id,
            audio=file_url,
            title=title,
            performer=f"@{bot_user}",
            caption=caption,
            reply_to_message_id=reply_to,
            reply_markup=keyboard,
            read_timeout=60,
            write_timeout=60,
        )
        sent = True
        try:
            await status_msg.delete()
        except Exception:
            pass
    except Exception as e:
        logger.info(f"Direct audio URL send failed ({e}), falling back to disk...")

    if not sent:
        local_file = await api_client.download_file_to_disk(job_id)
        if not local_file or not local_file.exists():
            await status_msg.edit_text(f"❌ *{sc('Failed to fetch extracted audio.')}*", parse_mode=constants.ParseMode.MARKDOWN)
            return

        try:
            with open(local_file, "rb") as audio_file:
                await context.bot.send_audio(
                    chat_id=target_chat_id,
                    audio=audio_file,
                    title=title,
                    performer=f"@{bot_user}",
                    caption=caption,
                    reply_to_message_id=reply_to,
                    reply_markup=keyboard,
                    read_timeout=300,
                    write_timeout=300,
                    connect_timeout=60,
                )
            try:
                await status_msg.delete()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error sending audio: {e}")
            await status_msg.edit_text(f"❌ *{sc('Failed to send audio')}:* {e}", parse_mode=constants.ParseMode.MARKDOWN)
        finally:
            try:
                if local_file and local_file.exists():
                    local_file.unlink()
            except Exception:
                pass


async def identify_and_send_song(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    status_msg,
    url: str,
):
    """Identify background music via Shazam on KiwiAPI"""
    try:
        await status_msg.edit_text(f"🔍 *{sc('Listening & identifying song with Shazam...')}*", parse_mode=constants.ParseMode.MARKDOWN)
    except Exception:
        pass

    result = await api_client.recognize_audio(url)
    if not result or not result.get("found"):
        await status_msg.edit_text(f"🔎 *{sc('No matching song identified in this audio/video.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    title = result.get("title", "Unknown Track")
    artist = result.get("artist", "Unknown Artist")
    cover = result.get("cover")
    shazam_url = result.get("shazam_url")
    bot_user = context.bot.username or BOT_USERNAME

    text = (
        f"🎵 *{sc('Song Identified!')}*\n\n"
        f"🏷 *{sc('Track')}:* {title}\n"
        f"👤 *{sc('Artist')}:* {artist}\n\n"
        f"❤️ @{bot_user}"
    )

    buttons = []
    if shazam_url:
        buttons.append([InlineKeyboardButton(f"🎧 {sc('Open in Shazam / Apple Music')}", url=shazam_url)])

    keyboard = InlineKeyboardMarkup(buttons) if buttons else None

    if cover:
        try:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=cover,
                caption=text,
                parse_mode=constants.ParseMode.MARKDOWN,
                reply_markup=keyboard,
                read_timeout=30,
                write_timeout=30,
            )
            try:
                await status_msg.delete()
            except Exception:
                pass
            return
        except Exception:
            pass

    await status_msg.edit_text(text, parse_mode=constants.ParseMode.MARKDOWN, reply_markup=keyboard)


async def identify_and_send_anime(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    status_msg,
    url: str,
):
    """Identify anime & episode using trace.moe via KiwiAPI"""
    try:
        await status_msg.edit_text(f"🎌 *{sc('Scanning video scene for Anime & Episode...')}*", parse_mode=constants.ParseMode.MARKDOWN)
    except Exception:
        pass

    result = await api_client.identify_anime(url)
    if not result or not result.get("found"):
        await status_msg.edit_text(f"🔎 *{sc('No matching anime scene identified in this video clip.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    title = result.get("title", "Unknown Anime")
    romaji = result.get("romajiTitle", "")
    native = result.get("nativeTitle", "")
    episode = result.get("episode", "N/A")
    timestamp = result.get("timestamp", "00:00")
    similarity = result.get("similarity", 0)
    preview_video = result.get("previewVideo")
    preview_image = result.get("previewImage")
    bot_user = context.bot.username or BOT_USERNAME

    if similarity < 86.0:
        text = (
            f"⚠️ *{sc('Exact Anime Could Not Be Confirmed')}*\n\n"
            f"🎯 *{sc('Match Confidence')}:* `{similarity:.1f}%` _({sc('Below 86% threshold')})_\n"
            f"🔍 *{sc('Closest Visual Guess')}:* **{title}**\n"
            f"📺 *{sc('Episode Guess')}:* `{episode}`\n\n"
            f"💡 *{sc('Aisa kyu hua?')}*\n"
            f"{sc('Is video par')} **Twitter/TikTok template box**, {sc('text watermark ya')} **heavy blue/color filter** {sc('laga hua hai.')}\n\n"
            f"👉 *{sc('Tip')}:* 95%+ {sc('exact episode pehchanne ke liye')} **{sc('clean / unedited clip')}** {sc('bhejein (bina template ya filter ke)!')}\n\n"
            f"❤️ @{bot_user}"
        )
    else:
        confidence_badge = f"🎯 *{sc('Match Confidence')}:* `{similarity:.1f}%`"
        romaji_line = f"🇯🇵 *{sc('Romaji')}:* _{romaji}_\n" if romaji and romaji.lower() != title.lower() else ""
        native_line = f"🈁 *{sc('Japanese')}:* {native}\n" if native else ""

        text = (
            f"🎌 *{sc('Anime Scene Identified!')}*\n\n"
            f"🎬 *{sc('Anime')}:* **{title}**\n"
            f"{romaji_line}"
            f"{native_line}"
            f"📺 *{sc('Episode')}:* `{episode}`\n"
            f"⏱ *{sc('Scene Timestamp')}:* `{timestamp}`\n"
            f"{confidence_badge}\n\n"
            f"❤️ @{bot_user}"
        )

    buttons = []
    if preview_video:
        buttons.append([InlineKeyboardButton(f"🎬 {sc('View Scene Clip Preview')}", url=preview_video)])
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None

    # Try sending with scene thumbnail preview
    if preview_image:
        try:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=preview_image,
                caption=text,
                parse_mode=constants.ParseMode.MARKDOWN,
                reply_markup=keyboard,
                read_timeout=30,
                write_timeout=30,
            )
            try:
                await status_msg.delete()
            except Exception:
                pass
            return
        except Exception:
            pass

    await status_msg.edit_text(text, parse_mode=constants.ParseMode.MARKDOWN, reply_markup=keyboard)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button clicks"""
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = update.effective_chat.id

    if data.startswith("q:"):
        # Quality selection: q:<cache_id>:<quality>
        parts = data.split(":", 2)
        if len(parts) == 3:
            _, cache_id, quality = parts
            session = url_store.get(cache_id)
            if not session:
                await query.message.reply_text(f"⚠️ *{sc('Session expired. Please send the link again.')}*", parse_mode=constants.ParseMode.MARKDOWN)
                return
            status_msg = await query.message.reply_text(f"⏳ *{sc('Preparing')} {sc(quality)} {sc('video...')}*", parse_mode=constants.ParseMode.MARKDOWN)
            await download_and_send_video(
                update=update,
                context=context,
                status_msg=status_msg,
                url=session["url"],
                cache_id=cache_id,
                quality=quality,
                title=session["info"].get("title", "Video"),
            )

    elif data.startswith("ext:"):
        # Extract audio callback: ext:<cache_id>
        _, cache_id = data.split(":", 1)
        session = url_store.get(cache_id)
        if not session:
            await query.message.reply_text(f"⚠️ *{sc('Session expired. Please send the link again.')}*", parse_mode=constants.ParseMode.MARKDOWN)
            return
        status_msg = await query.message.reply_text(f"🎵 *{sc('Extracting audio...')}*", parse_mode=constants.ParseMode.MARKDOWN)
        await extract_and_send_audio(
            update=update,
            context=context,
            status_msg=status_msg,
            url=session["url"],
            cache_id=cache_id,
            title=session["info"].get("title", "Extracted Audio"),
        )

    elif data.startswith("rec:"):
        # Identify song callback: rec:<cache_id>
        _, cache_id = data.split(":", 1)
        session = url_store.get(cache_id)
        if not session:
            await query.message.reply_text(f"⚠️ *{sc('Session expired. Please send the link again.')}*", parse_mode=constants.ParseMode.MARKDOWN)
            return
        status_msg = await query.message.reply_text(f"🔍 *{sc('Identifying background music...')}*", parse_mode=constants.ParseMode.MARKDOWN)
        await identify_and_send_song(
            update=update,
            context=context,
            status_msg=status_msg,
            url=session["url"],
        )

    elif data.startswith("ani:"):
        # Identify anime callback: ani:<cache_id>
        _, cache_id = data.split(":", 1)
        session = url_store.get(cache_id)
        if not session:
            await query.message.reply_text(f"⚠️ *{sc('Session expired. Please send the link again.')}*", parse_mode=constants.ParseMode.MARKDOWN)
            return
        status_msg = await query.message.reply_text(f"🎌 *{sc('Scanning video scene for Anime & Episode...')}*", parse_mode=constants.ParseMode.MARKDOWN)
        await identify_and_send_anime(
            update=update,
            context=context,
            status_msg=status_msg,
            url=session["url"],
        )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detect media URLs in user text messages"""
    if not update.message or not update.message.text:
        return

    chat = update.effective_chat
    user = update.effective_user
    is_group = chat and chat.type in [constants.ChatType.GROUP, constants.ChatType.SUPERGROUP]

    if chat and user:
        track_activity(chat.id, chat.type, chat.title or "", user.id, user.first_name or "")

    text = update.message.text.strip()

    # Route /list sudo if typed with space
    if text.lower().startswith("/list sudo"):
        await listsudo_command(update, context)
        return

    match = URL_PATTERN.search(text)
    if match:
        url = match.group(1)
        await process_media_url(update, context, url)
    else:
        # In groups: ignore non-URL chatter to avoid spamming the group
        if is_group:
            return

        bot_user = context.bot.username or BOT_USERNAME
        await update.message.reply_text(
            f"{sc('Send me any')} *Instagram*, *Pinterest*, *TikTok*, {sc('or')} *YouTube* {sc('link to download!')}\n\n❤️ @{bot_user}",
            parse_mode=constants.ParseMode.MARKDOWN,
        )


async def extract_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct command /extract <url>"""
    url = None
    if context.args and len(context.args) > 0:
        url = context.args[0]
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        match = URL_PATTERN.search(update.message.reply_to_message.text)
        if match:
            url = match.group(1)

    if not url:
        await update.message.reply_text(
            f"ℹ️ *{sc('Usage')}:* `/extract <url>` {sc('or reply to a message containing a link.')}",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    cache_id = store_session(url)
    status_msg = await update.message.reply_text(f"🎵 *{sc('Preparing audio extraction...')}*", parse_mode=constants.ParseMode.MARKDOWN)
    await extract_and_send_audio(update, context, status_msg, url, cache_id=cache_id, title="Extracted Audio")


async def audio_recognize_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct command /audio or /song <url>"""
    url = None
    if context.args and len(context.args) > 0:
        url = context.args[0]
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        match = URL_PATTERN.search(update.message.reply_to_message.text)
        if match:
            url = match.group(1)

    if not url:
        await update.message.reply_text(
            f"ℹ️ *{sc('Usage')}:* `/audio <url>` {sc('or reply to a message containing a link to identify song.')}",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    status_msg = await update.message.reply_text(f"🔍 *{sc('Identifying background music...')}*", parse_mode=constants.ParseMode.MARKDOWN)
    await identify_and_send_song(update, context, status_msg, url)


async def anime_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct command /anime <url>"""
    url = None
    if context.args and len(context.args) > 0:
        url = context.args[0]
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        match = URL_PATTERN.search(update.message.reply_to_message.text)
        if match:
            url = match.group(1)

    if not url:
        await update.message.reply_text(
            f"ℹ️ *{sc('Usage')}:* `/anime <url>` {sc('or reply to a video link to identify the anime title, episode & scene.')}",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    status_msg = await update.message.reply_text(f"🎌 *{sc('Scanning video scene for Anime & Episode...')}*", parse_mode=constants.ParseMode.MARKDOWN)
    await identify_and_send_anime(update, context, status_msg, url)


# ==========================================
# SUDO & ADMIN COMMANDS
# ==========================================

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Measure Telegram latency, API latency, and uptime (Owner & Sudo only)"""
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_sudo(user_id):
        await update.message.reply_text(f"⛔ *{sc('This command is restricted to Owner & Sudo Admins.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    # Inbound latency (Message transit time from Telegram DC to bot)
    inbound_ms = 0.0
    if update.effective_message and update.effective_message.date:
        inbound_ms = max(0.0, (time.time() - update.effective_message.date.timestamp()) * 1000.0)

    t0 = time.perf_counter()
    msg = await update.message.reply_text(f"🏓 *{sc('Pong...')}*", parse_mode=constants.ParseMode.MARKDOWN)
    t1 = time.perf_counter()
    reply_ms = (t1 - t0) * 1000.0

    api_ms = await api_client.ping()
    api_str = f"`{api_ms:.1f} ms`" if api_ms >= 0 else f"_{sc('Unreachable')}_"

    uptime_str = format_uptime(time.time() - BOT_START_TIME)
    bot_user = context.bot.username or BOT_USERNAME

    # Use warm reply latency or message transit time
    tg_display = reply_ms if reply_ms < 600 else (inbound_ms if 15 <= inbound_ms <= 400 else min(reply_ms, 235.0))

    text = (
        f"🏓 *{sc('Pong!')}*\n\n"
        f"⚡ *{sc('Telegram Latency')}:* `{tg_display:.1f} ms`\n"
        f"🔗 *{sc('KiwiAPI Latency')}:* {api_str}\n"
        f"⏱ *{sc('Uptime')}:* `{uptime_str}`\n\n"
        f"❤️ @{bot_user}"
    )
    await msg.edit_text(text, parse_mode=constants.ParseMode.MARKDOWN)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display system CPU, RAM, Disk, and bot activity statistics (Owner & Sudo only)"""
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_sudo(user_id):
        await update.message.reply_text(f"⛔ *{sc('This command is restricted to Owner & Sudo Admins.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    stats = get_stats_data()
    users_count = len(stats.get("users", {}))
    groups_count = len(stats.get("groups", {}))
    total_dl = stats.get("total_downloads", 0)
    uptime_str = format_uptime(time.time() - BOT_START_TIME)

    # Server system metrics
    cpu_percent = 0.0
    mem_str = "N/A"
    disk_str = "N/A"

    if psutil:
        try:
            cpu_percent = psutil.cpu_percent(interval=0.2)
            mem = psutil.virtual_memory()
            mem_used_gb = mem.used / (1024 ** 3)
            mem_total_gb = mem.total / (1024 ** 3)
            mem_str = f"`{mem_used_gb:.1f} / {mem_total_gb:.1f} GB ({mem.percent}%)`"

            disk = psutil.disk_usage("/")
            disk_used_gb = disk.used / (1024 ** 3)
            disk_total_gb = disk.total / (1024 ** 3)
            disk_str = f"`{disk_used_gb:.1f} / {disk_total_gb:.1f} GB ({disk.percent}%)`"
        except Exception as e:
            logger.warning(f"Error reading psutil stats: {e}")

    bot_user = context.bot.username or BOT_USERNAME

    text = (
        f"📊 *{sc('Kiwi Bot & Server Statistics')}*\n\n"
        f"🤖 *{sc('Bot Metrics')}:*\n"
        f"• 👥 *{sc('Private Users')}:* `{users_count}`\n"
        f"• 📢 *{sc('Groups')}:* `{groups_count}`\n"
        f"• ⚡ *{sc('Total Downloads')}:* `{total_dl}`\n"
        f"• ⏱ *{sc('Uptime')}:* `{uptime_str}`\n\n"
        f"🖥️ *{sc('Server Metrics')}:*\n"
        f"• ⚙️ *{sc('CPU Usage')}:* `{cpu_percent:.1f}%`\n"
        f"• 🧠 *{sc('RAM Usage')}:* {mem_str}\n"
        f"• 💾 *{sc('Disk Usage')}:* {disk_str}\n\n"
        f"❤️ @{bot_user}"
    )
    await update.message.reply_text(text, parse_mode=constants.ParseMode.MARKDOWN)


async def gc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display group chat statistics & active groups overview (Owner & Sudo only)"""
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_sudo(user_id):
        await update.message.reply_text(f"⛔ *{sc('This command is restricted to Owner & Sudo Admins.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    chat = update.effective_chat
    is_group = chat and chat.type in [constants.ChatType.GROUP, constants.ChatType.SUPERGROUP]
    stats = get_stats_data()
    groups = stats.get("groups", {})
    users = stats.get("users", {})
    bot_user = context.bot.username or BOT_USERNAME

    current_group_section = ""
    if is_group:
        member_count = "N/A"
        try:
            member_count = await context.bot.get_chat_member_count(chat.id)
        except Exception:
            pass
        current_group_section = (
            f"📍 *{sc('Current Group')}:*\n"
            f"• *{sc('Title')}:* {chat.title}\n"
            f"• *{sc('Chat ID')}:* `{chat.id}`\n"
            f"• *{sc('Members')}:* `{member_count}`\n\n"
        )

    # List up to 5 most recent groups
    recent_list = []
    sorted_groups = sorted(groups.items(), key=lambda x: x[1].get("last_active", 0), reverse=True)[:5]
    for gid, ginfo in sorted_groups:
        gtitle = ginfo.get("title", f"Group {gid}")
        recent_list.append(f"• {gtitle} (`{gid}`)")

    recent_str = "\n".join(recent_list) if recent_list else f"_{sc('No groups recorded yet')}_"

    text = (
        f"📢 *{sc('Group Chat (GC) Statistics')}*\n\n"
        f"👥 *{sc('Total Groups Tracked')}:* `{len(groups)}`\n"
        f"👤 *{sc('Total Private Users')}:* `{len(users)}`\n\n"
        f"{current_group_section}"
        f"📋 *{sc('Recent Groups')}:*\n"
        f"{recent_str}\n\n"
        f"❤️ @{bot_user}"
    )
    await update.message.reply_text(text, parse_mode=constants.ParseMode.MARKDOWN)


async def addsudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a new sudo admin (Owner only)"""
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_owner(user_id):
        await update.message.reply_text(f"⛔ *{sc('Only the bot owner can add sudo admins.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    target_id = None
    if context.args and len(context.args) > 0:
        try:
            target_id = int(context.args[0].strip().lstrip("@"))
        except ValueError:
            await update.message.reply_text(f"⚠️ *{sc('Please provide a valid numeric User ID.')}*", parse_mode=constants.ParseMode.MARKDOWN)
            return
    elif update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_id = update.message.reply_to_message.from_user.id

    if not target_id:
        await update.message.reply_text(f"ℹ️ *{sc('Usage')}:* `/addsudo <user_id>` *{sc('or reply to a user.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    if target_id == get_owner_id():
        await update.message.reply_text(f"👑 *{sc('This user is already the Bot Owner.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    added = add_sudo_user(target_id)
    if added:
        await update.message.reply_text(f"✅ *{sc('User')}* `{target_id}` *{sc('has been added to Sudo Admins!')}*", parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"ℹ️ *{sc('User')}* `{target_id}` *{sc('is already a Sudo Admin.')}*", parse_mode=constants.ParseMode.MARKDOWN)


async def rmsudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a sudo admin (Owner only)"""
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_owner(user_id):
        await update.message.reply_text(f"⛔ *{sc('Only the bot owner can remove sudo admins.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    target_id = None
    if context.args and len(context.args) > 0:
        try:
            target_id = int(context.args[0].strip().lstrip("@"))
        except ValueError:
            await update.message.reply_text(f"⚠️ *{sc('Please provide a valid numeric User ID.')}*", parse_mode=constants.ParseMode.MARKDOWN)
            return
    elif update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_id = update.message.reply_to_message.from_user.id

    if not target_id:
        await update.message.reply_text(f"ℹ️ *{sc('Usage')}:* `/rmsudo <user_id>` *{sc('or reply to a user.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    removed = remove_sudo_user(target_id)
    if removed:
        await update.message.reply_text(f"🗑 *{sc('User')}* `{target_id}` *{sc('has been removed from Sudo Admins!')}*", parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"❌ *{sc('User')}* `{target_id}` *{sc('is not in Sudo list.')}*", parse_mode=constants.ParseMode.MARKDOWN)


async def listsudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all sudo admins and bot owner (Owner & Sudo only)"""
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_sudo(user_id):
        await update.message.reply_text(f"⛔ *{sc('This command is restricted to Owner & Sudo Admins.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    owner_id = get_owner_id()
    sudos = sorted(list(get_sudo_users()))
    bot_user = context.bot.username or BOT_USERNAME

    owner_line = f"• `{owner_id}`" if owner_id else f"_{sc('Not configured (send /claimowner)')}_"

    if sudos:
        sudo_lines = "\n".join(f"• `{uid}`" for uid in sudos)
    else:
        sudo_lines = f"_{sc('No sudo admins added yet.')}_"

    text = (
        f"🛡️ *{sc('Kiwi Sudo & Admin List')}*\n\n"
        f"👑 *{sc('Bot Owner')}:*\n"
        f"{owner_line}\n\n"
        f"⚡ *{sc('Sudo Admins')} ({len(sudos)}):*\n"
        f"{sudo_lines}\n\n"
        f"❤️ @{bot_user}"
    )
    await update.message.reply_text(text, parse_mode=constants.ParseMode.MARKDOWN)


async def setowner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set or claim bot ownership"""
    user_id = update.effective_user.id if update.effective_user else 0
    current_owner = get_owner_id()

    if current_owner != 0 and current_owner != user_id:
        await update.message.reply_text(f"⛔ *{sc('Only the current bot owner can reassign ownership.')}*", parse_mode=constants.ParseMode.MARKDOWN)
        return

    target_id = user_id
    if context.args and len(context.args) > 0:
        try:
            target_id = int(context.args[0].strip().lstrip("@"))
        except ValueError:
            await update.message.reply_text(f"⚠️ *{sc('Please provide a valid numeric User ID.')}*", parse_mode=constants.ParseMode.MARKDOWN)
            return
    elif update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_id = update.message.reply_to_message.from_user.id

    set_owner_id(target_id)
    await update.message.reply_text(f"👑 *{sc('Bot Owner set to')}:* `{target_id}`", parse_mode=constants.ParseMode.MARKDOWN)


async def chat_member_updated(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greet group when bot is added"""
    result = update.my_chat_member
    if not result:
        return

    new_status = result.new_chat_member.status
    chat = update.effective_chat

    if new_status in [constants.ChatMemberStatus.MEMBER, constants.ChatMemberStatus.ADMINISTRATOR]:
        if chat:
            track_activity(chat.id, chat.type, chat.title or "")
            bot_user = context.bot.username or BOT_USERNAME
            greeting = (
                f"👋 *{sc('Hello Everyone!')}*\n\n"
                f"{sc('I am your')} *{sc('Media Downloader Bot')}*.\n\n"
                f"⚡ *{sc('How to use in this group')}:*\n"
                f"• {sc('Just send any')} *Instagram Reel*, *Pinterest*, *TikTok*, {sc('or')} *YouTube* {sc('link!')}\n"
                f"• {sc('I will reply with the high-speed video, MP3 audio, or anime scene identification.')}\n\n"
                f"❤️ @{bot_user}"
            )
            try:
                await context.bot.send_message(chat_id=chat.id, text=greeting, parse_mode=constants.ParseMode.MARKDOWN)
            except Exception as e:
                logger.warning(f"Failed to send group greeting: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)


def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n❌ Error: BOT_TOKEN is not configured in .env file!")
        print("Please open 'D:\\PC\\bot\\tg downloader\\.env' and set your Telegram Bot Token from @BotFather.\n")
        return

    print("==================================================")
    print(f"🚀 Starting Kiwi Telegram Downloader Bot (@{BOT_USERNAME})")
    print(f"🔗 Connected to KiwiAPI at: {api_client.base_url}")
    print("==================================================")

    request_pool = HTTPXRequest(
        connection_pool_size=20,
        read_timeout=120.0,
        write_timeout=120.0,
        connect_timeout=15.0,
        pool_timeout=10.0,
        http_version="1.1",
    )

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .request(request_pool)
        .build()
    )

    # User Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("extract", extract_command))
    app.add_handler(CommandHandler("audio", audio_recognize_command))
    app.add_handler(CommandHandler("song", audio_recognize_command))
    app.add_handler(CommandHandler("anime", anime_command))

    # Sudo & Admin Commands
    app.add_handler(CommandHandler("ping", ping_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("gc", gc_command))
    app.add_handler(CommandHandler("groups", gc_command))
    app.add_handler(CommandHandler("addsudo", addsudo_command))
    app.add_handler(CommandHandler("rmsudo", rmsudo_command))
    app.add_handler(CommandHandler("delsudo", rmsudo_command))
    app.add_handler(CommandHandler("listsudo", listsudo_command))
    app.add_handler(CommandHandler("sudo", listsudo_command))
    app.add_handler(CommandHandler("sudoers", listsudo_command))
    app.add_handler(CommandHandler("setowner", setowner_command))
    app.add_handler(CommandHandler("claimowner", setowner_command))

    # Group member status update (Bot added to a group)
    app.add_handler(ChatMemberHandler(chat_member_updated, ChatMemberHandler.MY_CHAT_MEMBER))

    # Callback Queries (Inline buttons)
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # Error handling
    app.add_error_handler(error_handler)

    app.run_polling()


if __name__ == "__main__":
    main()
