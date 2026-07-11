"""
Hagemaru OTT Store - YT Plan Manager Bot
------------------------------------------
Customers register with their email + manager ID for a YouTube plan.
Bot tracks plan expiry and auto-notifies them (with their manager ID)
when the plan is about to end / has ended.

Requirements: python-telegram-bot==20.7
Run: python bot.py   (set BOT_TOKEN env var first)
"""

import json
import os
import re
import logging
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_FILE = os.path.join(os.path.dirname(__file__), "subscriptions.json")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")  # optional: your own chat id for alerts

EMAIL, MANAGER_ID = range(2)
PRODUCT, ISSUE = range(2, 4)
SEARCH = 4

PLAN_DAYS = 30  # fixed monthly cycle - manager ID changes each renewal

PRODUCTS = [
    "YouTube Premium",
    "Amazon Prime",
    "Hotstar",
    "Hoichoi",
    "Zee5",
    "Sony LIV",
    "Canva Education Pro",
    "Other",
]

TICKETS_FILE = os.path.join(os.path.dirname(__file__), "tickets.json")

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------- storage helpers ----------

def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data: dict) -> None:
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_tickets() -> dict:
    if not os.path.exists(TICKETS_FILE):
        return {}
    with open(TICKETS_FILE, "r") as f:
        return json.load(f)


def save_tickets(data: dict) -> None:
    with open(TICKETS_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ---------- registration conversation ----------

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to Hagemaru's OTT Store!\n\n"
        "📌 /register — track a YT plan & get expiry reminders\n"
        "📌 /mystatus — see all your registered plans\n"
        "📌 /search <email> — look up a specific plan's Manager ID & renewal date\n"
        "📌 /support — report an issue with any product\n"
    )


async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📧 Send me the YouTube account email you want tracked."
    )
    return EMAIL


async def get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if not EMAIL_REGEX.match(email):
        await update.message.reply_text("That doesn't look like a valid email. Try again:")
        return EMAIL
    context.user_data["email"] = email
    await update.message.reply_text("🆔 Now send me your Manager ID (the one I gave you).")
    return MANAGER_ID


async def get_manager_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager_id = update.message.text.strip()

    start_date = datetime.now()
    expiry_date = start_date + timedelta(days=PLAN_DAYS)

    data = load_data()
    user_id = str(update.effective_user.id)
    data.setdefault(user_id, [])
    data[user_id].append({
        "email": context.user_data["email"],
        "manager_id": manager_id,
        "start_date": start_date.isoformat(),
        "expiry_date": expiry_date.isoformat(),
        "notified_soon": False,
        "notified_expired": False,
        "username": update.effective_user.username or "",
    })
    save_data(data)

    await update.message.reply_text(
        f"✅ Registered!\n\n"
        f"📧 Email: {context.user_data['email']}\n"
        f"🆔 Manager ID: {manager_id}\n"
        f"⏳ Expires: {expiry_date.strftime('%d %b %Y')}\n\n"
        f"I'll notify you here when it's about to expire. Use /mystatus anytime, "
        f"or /search <email> to look up any plan you've registered.\n"
        f"Note: you'll get a new Manager ID each renewal — just run /register again after renewing "
        f"(you can register multiple emails, no problem)."
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. Run /register anytime to start again.")
    return ConversationHandler.END


# ---------- support ticket conversation ----------

async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(p, callback_data=p)] for p in PRODUCTS]
    await update.message.reply_text(
        "🛠️ Which product is this about?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return PRODUCT


async def support_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["support_product"] = query.data
    await query.edit_message_text(
        f"📦 {query.data}\n\nDescribe your issue in one message and I'll pass it on."
    )
    return ISSUE


async def support_issue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    issue_text = update.message.text.strip()
    user = update.effective_user
    product = context.user_data.get("support_product", "Unknown")

    tickets = load_tickets()
    ticket_id = str(len(tickets) + 1)
    while ticket_id in tickets:  # avoid collisions after deletions
        ticket_id = str(int(ticket_id) + 1)

    tickets[ticket_id] = {
        "user_id": str(user.id),
        "username": user.username or "",
        "product": product,
        "issue": issue_text,
        "created": datetime.now().isoformat(),
        "status": "open",
    }
    save_tickets(tickets)

    await update.message.reply_text(
        f"✅ Got it! Ticket #{ticket_id} logged for {product}.\n"
        f"We'll get back to you here shortly."
    )

    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=int(ADMIN_CHAT_ID),
                text=(
                    f"🆕 Support Ticket #{ticket_id}\n"
                    f"👤 @{user.username or user.id}\n"
                    f"📦 Product: {product}\n"
                    f"📝 Issue: {issue_text}\n\n"
                    f"Reply with: /reply {ticket_id} <your message>"
                ),
            )
        except Exception as e:
            logger.warning(f"Failed to alert admin: {e}")

    return ConversationHandler.END


async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_CHAT_ID and str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        return  # only the admin can use this

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /reply <ticket_id> <message>")
        return

    ticket_id, message_text = context.args[0], " ".join(context.args[1:])
    tickets = load_tickets()
    ticket = tickets.get(ticket_id)

    if not ticket:
        await update.message.reply_text(f"No ticket found with ID {ticket_id}.")
        return

    try:
        await context.bot.send_message(
            chat_id=int(ticket["user_id"]),
            text=f"💬 Reply to your ticket #{ticket_id} ({ticket['product']}):\n\n{message_text}",
        )
        ticket["status"] = "replied"
        save_tickets(tickets)
        await update.message.reply_text(f"Sent to customer for ticket #{ticket_id}.")
    except Exception as e:
        await update.message.reply_text(f"Failed to send: {e}")


# ---------- status check ----------

async def my_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = str(update.effective_user.id)
    records = data.get(user_id)
    if not records:
        await update.message.reply_text("No active plans found. Use /register to set one up.")
        return

    lines = []
    for r in records:
        expiry = datetime.fromisoformat(r["expiry_date"])
        days_left = (expiry - datetime.now()).days
        status = f"{days_left} day(s) left" if days_left >= 0 else "EXPIRED"
        lines.append(
            f"📧 {r['email']}\n"
            f"🆔 Manager ID: {r['manager_id']}\n"
            f"⏳ Expiry: {expiry.strftime('%d %b %Y')} ({status})"
        )

    await update.message.reply_text("\n\n".join(lines))


# ---------- search ----------

async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # allow /search <term> directly, or start a conversation if no args
    if context.args:
        return await do_search(update, context, " ".join(context.args))
    await update.message.reply_text("🔍 Send the email (or part of it) you want to look up.")
    return SEARCH


async def search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await do_search(update, context, update.message.text.strip())


async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE, term: str):
    data = load_data()
    user_id = str(update.effective_user.id)
    records = data.get(user_id, [])

    term_lower = term.lower()
    matches = [r for r in records if term_lower in r["email"].lower()]

    if not matches:
        await update.message.reply_text(f"No registered plan found matching '{term}'.")
        return ConversationHandler.END

    lines = []
    for r in matches:
        expiry = datetime.fromisoformat(r["expiry_date"])
        days_left = (expiry - datetime.now()).days
        status = f"{days_left} day(s) left" if days_left >= 0 else "EXPIRED"
        lines.append(
            f"📧 {r['email']}\n"
            f"🆔 Manager ID: {r['manager_id']}\n"
            f"⏳ Expiry: {expiry.strftime('%d %b %Y')} ({status})"
        )

    await update.message.reply_text("\n\n".join(lines))
    return ConversationHandler.END


# ---------- daily expiry check job ----------

async def check_expiries(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    now = datetime.now()
    changed = False

    for user_id, records in data.items():
        for record in records:
            expiry = datetime.fromisoformat(record["expiry_date"])
            remaining = (expiry - now).days

            # 1 day before expiry
            if 0 <= remaining <= 1 and not record.get("notified_soon"):
                try:
                    await context.bot.send_message(
                        chat_id=int(user_id),
                        text=(
                            f"⏰ Heads up! Your YT plan ({record['email']}, Manager ID: "
                            f"{record['manager_id']}) expires on {expiry.strftime('%d %b %Y')}.\n"
                            f"Renew soon to avoid interruption — just message us here!"
                        ),
                    )
                    record["notified_soon"] = True
                    changed = True
                except Exception as e:
                    logger.warning(f"Failed to notify {user_id}: {e}")

            # on/after expiry
            if remaining < 0 and not record.get("notified_expired"):
                try:
                    await context.bot.send_message(
                        chat_id=int(user_id),
                        text=(
                            f"❌ Your YT plan ({record['email']}, Manager ID: "
                            f"{record['manager_id']}) has expired.\n"
                            f"Message us here to renew and get reconnected!"
                        ),
                    )
                    record["notified_expired"] = True
                    changed = True
                except Exception as e:
                    logger.warning(f"Failed to notify {user_id}: {e}")

    if changed:
        save_data(data)


# ---------- setup ----------

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("register", register_start)],
        states={
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_email)],
            MANAGER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_manager_id)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    support_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("support", support_start)],
        states={
            PRODUCT: [CallbackQueryHandler(support_product)],
            ISSUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_issue)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    search_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("search", search_start)],
        states={
            SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(conv_handler)
    app.add_handler(support_conv_handler)
    app.add_handler(search_conv_handler)
    app.add_handler(CommandHandler("mystatus", my_status))
    app.add_handler(CommandHandler("reply", admin_reply))

    # run expiry check once a day (also runs 10s after startup for a quick first pass)
    app.job_queue.run_repeating(check_expiries, interval=timedelta(hours=24), first=10)

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
