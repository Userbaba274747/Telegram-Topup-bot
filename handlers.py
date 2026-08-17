from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters
)
from datetime import datetime
import database as db
from keyboards import *
from states import UserStates, AdminStates
from config import ADMINS


# ==================== HELPER ====================

async def is_user_banned(user_id):
    user = await db.get_user(user_id)
    return user and user["is_banned"] == 1


async def check_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    maintenance = await db.get_setting("maintenance_mode")
    if maintenance == "True":
        text = "🔧 বট বর্তমানে মেইনটেনেন্স মোডে আছে। কিছুক্ষণ পর আবার চেষ্টা করুন।"
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return True
    return False


async def admin_only(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        if update.callback_query:
            await update.callback_query.answer("আপনার অনুমতি নেই!", show_alert=True)
        else:
            await update.message.reply_text("আপনার অনুমতি নেই!")
        return False
    return True


# ==================== USER HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referred_by = None

    # Referral check
    if context.args and context.args[0].startswith("ref"):
        try:
            referred_by = int(context.args[0].replace("ref", ""))
        except:
            pass

    await db.add_user(user.id, user.username, user.full_name, referred_by)

    if await is_user_banned(user.id):
        await update.message.reply_text("🚫 আপনাকে ব্যান করা হয়েছে। সাপোর্টে যোগাযোগ করুন।")
        return

    if await check_maintenance(update, context):
        return

    user_data = await db.get_user(user.id)
    balance = user_data["balance"] if user_data else 0

    text = (
        f"🎮 Welcome to Free Fire Top-Up Bot!\n\n"
        f"💰 Balance: ৳{balance:.2f}\n\n"
        f"🔥 Choose an option below:"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if await is_user_banned(query.from_user.id):
        await query.edit_message_text("🚫 আপনাকে ব্যান করা হয়েছে।")
        return

    if await check_maintenance(update, context):
        return

    user_data = await db.get_user(query.from_user.id)
    balance = user_data["balance"] if user_data else 0

    text = (
        f"🎮 Welcome to Free Fire Top-Up Bot!\n\n"
        f"💰 Balance: ৳{balance:.2f}\n\n"
        f"🔥 Choose an option below:"
    )
    await query.edit_message_text(text, reply_markup=main_menu_keyboard())


# ---------- Diamond Top-Up ----------
async def diamond_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if await is_user_banned(query.from_user.id) or await check_maintenance(update, context):
        return

    offers = await db.get_all_offers(active_only=True)
    if not offers:
        await query.edit_message_text(
            "😔 এখন কোনো অফার নেই।",
            reply_markup=back_to_main_keyboard()
        )
        return

    text = "💎 FREE FIRE DIAMOND OFFERS\n\n"
    for offer in offers:
        text += f"💎 {offer['name']}\n💰 Price: ৳{offer['price']}\n\n"

    await query.edit_message_text(text, reply_markup=offers_keyboard(offers))


async def select_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    offer_id = int(query.data.split("_")[-1])
    offer = await db.get_offer(offer_id)

    if not offer or offer["is_active"] == 0:
        await query.edit_message_text("এই অফারটি আর নেই।", reply_markup=back_to_main_keyboard())
        return

    context.user_data["selected_offer"] = offer_id

    text = (
        f"💎 {offer['name']}\n\n"
        f"💰 Price: ৳{offer['price']}\n"
        f"⚡ Delivery: {offer['delivery_time']}\n\n"
        f"Please enter your Free Fire UID:"
    )
    await query.edit_message_text(text)
    return UserStates.WAITING_UID


async def receive_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.text.strip()
    offer_id = context.user_data.get("selected_offer")
    offer = await db.get_offer(offer_id)

    if not offer:
        await update.message.reply_text("অফার পাওয়া যায়নি।", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    user = await db.get_user(update.effective_user.id)
    if user["balance"] < offer["price"]:
        await update.message.reply_text(
            f"❌ আপনার ব্যালেন্স অপর্যাপ্ত!\n"
            f"প্রয়োজন: ৳{offer['price']}\n"
            f"আপনার ব্যালেন্স: ৳{user['balance']:.2f}\n\n"
            f"আগে Deposit করুন।",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    context.user_data["uid"] = uid

    text = (
        f"📦 Order Confirmation\n\n"
        f"💎 {offer['name']}\n"
        f"💰 Price: ৳{offer['price']}\n"
        f"🆔 UID: {uid}\n"
        f"⚡ Delivery: {offer['delivery_time']}\n\n"
        f"Confirm করে Order করবেন?"
    )
    await update.message.reply_text(text, reply_markup=confirm_order_keyboard(offer_id))
    return ConversationHandler.END


async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    offer_id = int(query.data.split("_")[-1])
    offer = await db.get_offer(offer_id)
    uid = context.user_data.get("uid")
    user_id = query.from_user.id

    user = await db.get_user(user_id)
    if user["balance"] < offer["price"]:
        await query.edit_message_text("❌ ব্যালেন্স অপর্যাপ্ত!", reply_markup=back_to_main_keyboard())
        return

    # Balance কাটা
    await db.update_balance(user_id, -offer["price"])

    # Order তৈরি
    order_id = await db.create_order(
        user_id, offer_id, offer["name"], offer["diamonds"], offer["price"], uid
    )

    text = (
        f"✅ Order Created Successfully!\n\n"
        f"📦 Order ID: `{order_id}`\n"
        f"💎 {offer['name']}\n"
        f"🆔 UID: {uid}\n"
        f"💰 Amount: ৳{offer['price']}\n"
        f"⏳ Status: Pending\n\n"
        f"অ্যাডমিন শীঘ্রই প্রসেস করবে।"
    )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_to_main_keyboard())

    # Admin কে নোটিফিকেশন (ঐচ্ছিক)
    for admin_id in ADMINS:
        try:
            await context.bot.send_message(
                admin_id,
                f"📦 New Order!\n\nOrder: {order_id}\nUser: {user_id}\nProduct: {offer['name']}\nUID: {uid}"
            )
        except:
            pass


async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Order Cancelled.", reply_markup=back_to_main_keyboard())


# ---------- Deposit ----------
async def deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if await is_user_banned(query.from_user.id) or await check_maintenance(update, context):
        return

    text = "💰 DEPOSIT\n\nSelect Payment Method:"
    await query.edit_message_text(text, reply_markup=deposit_method_keyboard())


async def deposit_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    method = query.data.split("_")[1]  # bkash / nagad / rocket / binance
    context.user_data["deposit_method"] = method.capitalize()

    await query.edit_message_text("💰 Deposit Amount লিখুন (শুধু সংখ্যা):")
    return UserStates.WAITING_DEPOSIT_AMOUNT


async def receive_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except:
        await update.message.reply_text("সঠিক সংখ্যা লিখুন:")
        return UserStates.WAITING_DEPOSIT_AMOUNT

    min_deposit = float(await db.get_setting("min_deposit") or 100)
    if amount < min_deposit:
        await update.message.reply_text(f"সর্বনিম্ন Deposit ৳{min_deposit}")
        return UserStates.WAITING_DEPOSIT_AMOUNT

    context.user_data["deposit_amount"] = amount
    method = context.user_data["deposit_method"]

    if method == "Bkash":
        number = await db.get_setting("bkash_number")
    elif method == "Nagad":
        number = await db.get_setting("nagad_number")
    elif method == "Rocket":
        number = await db.get_setting("rocket_number")
    else:
        number = await db.get_setting("binance_address")

    text = (
        f"💰 Deposit Amount: ৳{amount}\n\n"
        f"Send payment to:\n"
        f"📱 {method}: `{number}`\n\n"
        f"Then enter Transaction ID:"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
    return UserStates.WAITING_TRX_ID


async def receive_trx_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trx_id = update.message.text.strip()
    user_id = update.effective_user.id
    amount = context.user_data["deposit_amount"]
    method = context.user_data["deposit_method"]

    success = await db.create_deposit(user_id, amount, method, trx_id)
    if not success:
        await update.message.reply_text(
            "❌ এই Transaction ID আগে ব্যবহার করা হয়েছে!",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "✅ Deposit Request পাঠানো হয়েছে!\nঅ্যাডমিন Approve করলে Balance যোগ হবে।",
        reply_markup=main_menu_keyboard()
    )

    # Admin Notification
    for admin_id in ADMINS:
        try:
            deposits = await db.get_pending_deposits()
            dep = deposits[0] if deposits else None
            if dep:
                text = (
                    f"💵 NEW DEPOSIT REQUEST\n\n"
                    f"👤 User: @{update.effective_user.username or 'N/A'}\n"
                    f"🆔 ID: {user_id}\n"
                    f"💰 Amount: ৳{amount}\n"
                    f"💳 Method: {method}\n"
                    f"🧾 TxID: `{trx_id}`"
                )
                await context.bot.send_message(
                    admin_id, text, parse_mode="Markdown",
                    reply_markup=deposit_action_keyboard(dep["id"])
                )
        except:
            pass

    return ConversationHandler.END


# ---------- My Account ----------
async def my_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = await db.get_user(query.from_user.id)
    text = (
        f"👤 MY ACCOUNT\n\n"
        f"👤 Name: {user['full_name']}\n"
        f"🆔 ID: {user['user_id']}\n"
        f"🔗 Username: @{user['username'] or 'N/A'}\n\n"
        f"💰 Balance: ৳{user['balance']:.2f}\n"
        f"💵 Total Deposited: ৳{user['total_deposited']:.2f}\n"
        f"💎 Total Spent: ৳{user['total_spent']:.2f}\n"
        f"📅 Joined: {user['joined_at'][:10]}"
    )
    await query.edit_message_text(text, reply_markup=back_to_main_keyboard())


# ---------- My Orders ----------
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    orders = await db.get_user_orders(query.from_user.id)
    if not orders:
        await query.edit_message_text("আপনার কোনো Order নেই।", reply_markup=back_to_main_keyboard())
        return

    text = "📜 MY ORDERS\n\n"
    for order in orders[:10]:
        text += (
            f"📦 `{order['order_id']}`\n"
            f"💎 {order['offer_name']}\n"
            f"💰 ৳{order['price']} | {order['status']}\n\n"
        )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_to_main_keyboard())


# ---------- Promo Code ----------
async def promo_code_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🎟 Promo Code লিখুন:")
    return UserStates.WAITING_PROMO_CODE


async def receive_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    promo = await db.get_promo(code)

    if not promo:
        await update.message.reply_text("❌ অবৈধ Promo Code!", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    if promo["used_count"] >= promo["max_uses"]:
        await update.message.reply_text("❌ এই কোডের ব্যবহার শেষ!", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    await update.message.reply_text(
        f"✅ Promo Applied!\nDiscount: ৳{promo['discount']}\n"
        f"(পরবর্তী পারচেজে কাটা হবে)",
        reply_markup=main_menu_keyboard()
    )
    context.user_data["promo_discount"] = promo["discount"]
    return ConversationHandler.END


# ---------- Referral ----------
async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    bot_info = await context.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref{user_id}"

    text = (
        f"🤝 REFERRAL\n\n"
        f"🔗 Your Link:\n`{link}`\n\n"
        f"বন্ধুদের শেয়ার করুন এবং রিওয়ার্ড পান!"
    )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_to_main_keyboard())


# ---------- Support & Help ----------
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    support_user = await db.get_setting("support_username") or "@Support"
    await query.edit_message_text(
        f"📞 Support: {support_user}\n\nযেকোনো সমস্যায় যোগাযোগ করুন।",
        reply_markup=back_to_main_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "ℹ️ HELP\n\n"
        "1️⃣ আগে Deposit করে Balance যোগ করুন\n"
        "2️⃣ Diamond Top-Up থেকে অফার সিলেক্ট করুন\n"
        "3️⃣ Free Fire UID দিন\n"
        "4️⃣ Confirm করুন\n\n"
        "কোনো সমস্যা হলে Support এ যোগাযোগ করুন।"
    )
    await query.edit_message_text(text, reply_markup=back_to_main_keyboard())


# ==================== ADMIN HANDLERS ====================

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context):
        return

    stats = await db.get_stats()
    text = (
        f"👑 ADMIN DASHBOARD\n\n"
        f"👥 Total Users: {stats['total_users']}\n"
        f"🟢 Active Users: {stats['active_users']}\n"
        f"🚫 Banned Users: {stats['banned_users']}\n"
        f"📦 Total Orders: {stats['total_orders']}\n"
        f"⏳ Pending Orders: {stats['pending_orders']}\n"
        f"💵 Total Deposits: ৳{stats['total_deposits']:.2f}\n"
        f"💎 Total Sales: ৳{stats['total_sales']:.2f}\n\n"
        f"Choose an option:"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=admin_dashboard_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=admin_dashboard_keyboard())


async def admin_offers_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await admin_only(update, context):
        return
    await query.edit_message_text("🎁 Manage Offers", reply_markup=admin_offers_keyboard())


async def admin_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await admin_only(update, context):
        return
    await query.edit_message_text("👥 Users Management", reply_markup=admin_users_keyboard())


async def admin_deposits_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await admin_only(update, context):
        return
    await query.edit_message_text("💵 Deposits", reply_markup=admin_deposits_keyboard())


async def admin_orders_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await admin_only(update, context):
        return
    await query.edit_message_text("📦 Orders", reply_markup=admin_orders_keyboard())


# ---------- Pending Deposits ----------
async def pending_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await admin_only(update, context):
        return

    deposits = await db.get_pending_deposits()
    if not deposits:
        await query.edit_message_text("কোনো Pending Deposit নেই।", reply_markup=back_to_admin_keyboard())
        return

    for dep in deposits[:5]:
        user = await db.get_user(dep["user_id"])
        text = (
            f"💵 DEPOSIT REQUEST\n\n"
            f"👤 User: @{user['username'] or 'N/A'}\n"
            f"🆔 ID: {dep['user_id']}\n"
            f"💰 Amount: ৳{dep['amount']}\n"
            f"💳 Method: {dep['method']}\n"
            f"🧾 TxID: `{dep['trx_id']}`"
        )
        await context.bot.send_message(
            query.from_user.id, text, parse_mode="Markdown",
            reply_markup=deposit_action_keyboard(dep["id"])
        )
    await query.edit_message_text("Pending Deposits পাঠানো হয়েছে।", reply_markup=back_to_admin_keyboard())


async def approve_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await admin_only(update, context):
        return

    deposit_id = int(query.data.split("_")[-1])
    dep = await db.get_deposit(deposit_id)
    if not dep or dep["status"] != "Pending":
        await query.edit_message_text("ইতিমধ্যে প্রসেস করা হয়েছে।")
        return

    await db.update_deposit_status(deposit_id, "Approved")
    await db.update_balance(dep["user_id"], dep["amount"])

    await query.edit_message_text(f"✅ Deposit Approved! ৳{dep['amount']} যোগ করা হয়েছে।")

    try:
        await context.bot.send_message(
            dep["user_id"],
            f"✅ আপনার Deposit Approve হয়েছে!\n💰 ৳{dep['amount']} Balance-এ যোগ করা হয়েছে।"
        )
    except:
        pass


async def reject_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await admin_only(update, context):
        return

    deposit_id = int(query.data.split("_")[-1])
    dep = await db.get_deposit(deposit_id)
    if not dep or dep["status"] != "Pending":
        await query.edit_message_text("ইতিমধ্যে প্রসেস করা হয়েছে।")
        return

    await db.update_deposit_status(deposit_id, "Rejected")
    await query.edit_message_text("❌ Deposit Rejected.")

    try:
        await context.bot.send_message(dep["user_id"], "❌ আপনার Deposit Request Reject করা হয়েছে।")
    except:
        pass


# ---------- Orders Admin ----------
async def pending_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await admin_only(update, context):
        return

    orders = await db.get_orders_by_status("Pending")
    if not orders:
        await query.edit_message_text("কোনো Pending Order নেই।", reply_markup=back_to_admin_keyboard())
        return

    for order in orders[:5]:
        text = (
            f"📦 ORDER `{order['order_id']}`\n\n"
            f"👤 User ID: {order['user_id']}\n"
            f"💎 {order['offer_name']}\n"
            f"🆔 UID: {order['uid']}\n"
            f"💰 ৳{order['price']}\n"
            f"⏳ Status: Pending"
        )
        await context.bot.send_message(
            query.from_user.id, text, parse_mode="Markdown",
            reply_markup=order_action_keyboard(order["order_id"])
        )
    await query.edit_message_text("Pending Orders পাঠানো হয়েছে।", reply_markup=back_to_admin_keyboard())


async def complete_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await admin_only(update, context):
        return

    order_id = query.data.split("_")[-1]
    order = await db.get_order(order_id)
    if not order:
        await query.edit_message_text("Order পাওয়া যায়নি।")
        return

    await db.update_order_status(order_id, "Completed")
    await query.edit_message_text(f"✅ Order `{order_id}` Completed!", parse_mode="Markdown")

    try:
        delivery_msg = await db.get_setting("delivery_message")
        await context.bot.send_message(
            order["user_id"],
            f"✅ আপনার Order সম্পন্ন হয়েছে!\n📦 Order ID: `{order_id}`\n\n{delivery_msg}",
            parse_mode="Markdown"
        )
    except:
        pass


# ---------- Statistics ----------
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await admin_only(update, context):
        return

    stats = await db.get_stats()
    text = (
        f"📊 BOT STATISTICS\n\n"
        f"👥 Total Users: {stats['total_users']}\n"
        f"🟢 Active: {stats['active_users']}\n"
        f"🚫 Banned: {stats['banned_users']}\n\n"
        f"💵 Total Deposit: ৳{stats['total_deposits']:.2f}\n"
        f"💎 Total Sales: ৳{stats['total_sales']:.2f}\n\n"
        f"📦 Orders: {stats['total_orders']}\n"
        f"✅ Completed: {stats['completed_orders']}\n"
        f"⏳ Pending: {stats['pending_orders']}"
    )
    await query.edit_message_text(text, reply_markup=back_to_admin_keyboard())


# ---------- Cancel Conversation ----------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("বাতিল করা হয়েছে।", reply_markup=main_menu_keyboard())
    return ConversationHandler.END
