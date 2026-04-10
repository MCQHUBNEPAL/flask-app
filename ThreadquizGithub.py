import logging
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Dict, List, Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import os
# =========================
# CONFIG
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Dynamic topic config
ACTIVE_TOPIC_ID: Optional[int] = None
ACTIVE_TOPIC_NAME: Optional[str] = None

# Upload topics as: {topic_id: topic_name}
ALLOWED_UPLOAD_TOPICS: Dict[int, str] = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# =========================
# DATA MODEL
# =========================
@dataclass
class MCQ:
    question: str
    options: List[str]
    correct_option_index: int
    explanation: Optional[str] = None


# =========================
# PARSER
# =========================
def parse_mcq_block(block: str) -> MCQ:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if len(lines) < 6:
        raise ValueError("Block is too short.")

    q_match = re.match(r"^\d+\.\s*(.+)$", lines[0])
    if not q_match:
        raise ValueError(f"Invalid question line: {lines[0]}")
    question = q_match.group(1).strip()

    option_patterns = [
        r"^A\.\s*(.+)$",
        r"^B\.\s*(.+)$",
        r"^C\.\s*(.+)$",
        r"^D\.\s*(.+)$",
    ]

    options = []
    for i in range(4):
        match = re.match(option_patterns[i], lines[i + 1], re.IGNORECASE)
        if not match:
            raise ValueError(f"Invalid option line: {lines[i + 1]}")
        options.append(match.group(1).strip())

    answer_line = lines[5]
    if not re.match(r"^[1-4]$", answer_line):
        raise ValueError(f"Invalid answer number: {answer_line}")

    correct_option_index = int(answer_line) - 1

    explanation = None
    if len(lines) > 6:
        explanation = "\n".join(lines[6:]).strip()

    return MCQ(
        question=question,
        options=options,
        correct_option_index=correct_option_index,
        explanation=explanation,
    )


def parse_mcqs(text: str) -> List[MCQ]:
    raw_blocks = re.split(r"\n(?=\d+\.\s)", text.strip())
    mcqs = []

    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue
        mcqs.append(parse_mcq_block(block))

    return mcqs


# =========================
# ESCAPE MARKDOWN V2
# =========================
def escape_markdown_v2(text: str) -> str:
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join("\\" + ch if ch in escape_chars else ch for ch in text)


# =========================
# HELPERS
# =========================
def get_thread_id(update: Update) -> Optional[int]:
    if not update.message:
        return None
    return getattr(update.message, "message_thread_id", None)


def get_topic_title(update: Update) -> Optional[str]:
    """
    Tries to get the topic title from Telegram forum topic metadata.
    Depending on message type, this may not always exist.
    """
    if not update.message:
        return None

    # Some Telegram updates may include forum topic created/edited info,
    # but ordinary messages usually do not carry topic title directly.
    # So for reliability we let user pass the name in command arguments.
    return None


def is_active_topic(update: Update) -> bool:
    thread_id = get_thread_id(update)
    if ACTIVE_TOPIC_ID is None:
        return False
    return thread_id == ACTIVE_TOPIC_ID


def is_allowed_upload_topic(update: Update) -> bool:
    thread_id = get_thread_id(update)
    return thread_id in ALLOWED_UPLOAD_TOPICS


async def send_mcqs(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    mcqs: List[MCQ],
) -> None:
    if not update.message:
        return

    chat_id = update.effective_chat.id
    thread_id = get_thread_id(update)

    for mcq in mcqs:
        await context.bot.send_poll(
            chat_id=chat_id,
            question=mcq.question,
            options=mcq.options,
            type="quiz",
            correct_option_id=mcq.correct_option_index,
            is_anonymous=True,
            message_thread_id=thread_id,
        )

        if mcq.explanation:
            escaped = escape_markdown_v2(f"Explanation: {mcq.explanation}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"||{escaped}||",
                parse_mode="MarkdownV2",
                message_thread_id=thread_id,
            )


async def delete_source_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id,
        )
    except Exception as e:
        logging.warning("Could not delete source message: %s", e)


# =========================
# COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Send MCQs as plain text or upload a .txt file.\n\n"
        "Commands:\n"
        "/setactive [name] - Set this topic as active for plain text MCQs\n"
        "/addtopic [name] - Allow .txt uploads in this topic with a custom name\n"
        "/removetopic - Remove this topic from upload topics\n"
        "/topics - Show active topic and upload topics\n\n"
        "Examples:\n"
        "/setactive Main Topic\n"
        "/addtopic Biology\n"
        "/addtopic Physics Batch A"
    )


async def set_active(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global ACTIVE_TOPIC_ID, ACTIVE_TOPIC_NAME

    if not update.message:
        return

    thread_id = get_thread_id(update)
    if thread_id is None:
        await update.message.reply_text("Use this command inside a forum topic.")
        return

    custom_name = " ".join(context.args).strip() if context.args else ""
    if custom_name:
        topic_name = custom_name
    else:
        topic_name = f"Topic {thread_id}"

    ACTIVE_TOPIC_ID = thread_id
    ACTIVE_TOPIC_NAME = topic_name

    await update.message.reply_text(
        f"✅ Active topic set:\n"
        f"Name: {topic_name}\n"
        f"ID: {thread_id}"
    )


async def add_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    thread_id = get_thread_id(update)
    if thread_id is None:
        await update.message.reply_text("Use this command inside a forum topic.")
        return

    custom_name = " ".join(context.args).strip() if context.args else ""
    if not custom_name:
        await update.message.reply_text(
            "Please provide a topic name.\n\n"
            "Example:\n"
            "/addtopic Biology"
        )
        return

    ALLOWED_UPLOAD_TOPICS[thread_id] = custom_name

    await update.message.reply_text(
        f"✅ Upload topic added:\n"
        f"Name: {custom_name}\n"
        f"ID: {thread_id}"
    )


async def remove_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    thread_id = get_thread_id(update)
    if thread_id is None:
        await update.message.reply_text("Use this command inside a forum topic.")
        return

    if thread_id in ALLOWED_UPLOAD_TOPICS:
        removed_name = ALLOWED_UPLOAD_TOPICS.pop(thread_id)
        await update.message.reply_text(
            f"❌ Removed upload topic:\n"
            f"Name: {removed_name}\n"
            f"ID: {thread_id}"
        )
    else:
        await update.message.reply_text("This topic is not in the upload topic list.")


async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if ACTIVE_TOPIC_ID is None:
        active_text = "🎯 Active Topic: None"
    else:
        active_name = ACTIVE_TOPIC_NAME or f"Topic {ACTIVE_TOPIC_ID}"
        active_text = (
            f"🎯 Active Topic:\n"
            f"• Name: {active_name}\n"
            f"• ID: {ACTIVE_TOPIC_ID}"
        )

    if not ALLOWED_UPLOAD_TOPICS:
        upload_text = "📂 Upload Topics:\nNone"
    else:
        lines = ["📂 Upload Topics:"]
        for topic_id, topic_name in sorted(ALLOWED_UPLOAD_TOPICS.items()):
            lines.append(f"• {topic_name} — {topic_id}")
        upload_text = "\n".join(lines)

    await update.message.reply_text(f"{active_text}\n\n{upload_text}")


# =========================
# HANDLERS
# =========================
async def handle_mcq_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    if not is_active_topic(update):
        return

    text = update.message.text.strip()

    try:
        mcqs = parse_mcqs(text)
        await send_mcqs(update, context, mcqs)
        await delete_source_message(update, context)
    except ValueError as e:
        await update.message.reply_text(f"Format error:\n{e}")
    except Exception as e:
        await update.message.reply_text(f"Unexpected error:\n{e}")


async def handle_txt_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.document:
        return

    if not is_allowed_upload_topic(update):
        return

    document = update.message.document
    file_name = (document.file_name or "").lower()

    if not file_name.endswith(".txt"):
        await update.message.reply_text("Please upload a .txt file only.")
        return

    try:
        telegram_file = await document.get_file()

        buffer = BytesIO()
        await telegram_file.download_to_memory(out=buffer)
        text = buffer.getvalue().decode("utf-8-sig", errors="replace").strip()

        if not text:
            await update.message.reply_text("The .txt file is empty.")
            return

        mcqs = parse_mcqs(text)
        await send_mcqs(update, context, mcqs)
        await delete_source_message(update, context)

    except ValueError as e:
        await update.message.reply_text(f"Format error in .txt file:\n{e}")
    except UnicodeDecodeError:
        await update.message.reply_text("Could not read the file. Please save it as UTF-8 .txt.")
    except Exception as e:
        await update.message.reply_text(f"Unexpected file error:\n{e}")


# =========================
# MAIN
# =========================
def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setactive", set_active))
    app.add_handler(CommandHandler("addtopic", add_topic))
    app.add_handler(CommandHandler("removetopic", remove_topic))
    app.add_handler(CommandHandler("topics", list_topics))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_mcq_text,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Document.FileExtension("txt"),
            handle_txt_file,
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
