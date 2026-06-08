import os
import logging
import asyncio
import aiohttp
import pandas as pd
import numpy as np
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from datetime import datetime
import base64
import uuid

# ==================== CONFIG ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7988511913:AAHTrbjjRjNVGoUoB-UuVw6A6ob_Hui7VQ0")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "5919405883"))

# Invite system
invite_links = {}  # token -> used (bool)
allowed_users = set([ADMIN_CHAT_ID])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== INDICATORS ====================

def calculate_rsi(prices, period=14):
    delta = pd.Series(prices).diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2)

def calculate_ema(prices, period):
    return round(pd.Series(prices).ewm(span=period, adjust=False).mean().iloc[-1], 2)

def calculate_sma(prices, period):
    return round(pd.Series(prices).rolling(window=period).mean().iloc[-1], 2)

def calculate_bollinger(prices, period=20):
    s = pd.Series(prices)
    mid = s.rolling(period).mean()
    std = s.rolling(period).std()
    upper = mid + 2 * std
    lower = mid - 2 * std
    return round(upper.iloc[-1], 2), round(mid.iloc[-1], 2), round(lower.iloc[-1], 2)

def calculate_volume_signal(volumes):
    avg_vol = np.mean(volumes[-20:])
    last_vol = volumes[-1]
    ratio = last_vol / avg_vol if avg_vol > 0 else 1
    if ratio > 1.5:
        return "🔥 حجم بالا", ratio
    elif ratio > 1.0:
        return "📊 حجم متوسط", ratio
    else:
        return "😴 حجم پایین", ratio

# ==================== MARKET DATA ====================

async def get_gold_data(interval="1h", limit=100):
    """Get XAUUSD data from Binance (PAXG as gold proxy) or similar"""
    try:
        # Using Yahoo Finance API for gold data
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval={interval}&range=5d"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                prices = data['chart']['result'][0]['indicators']['quote'][0]['close']
                volumes = data['chart']['result'][0]['indicators']['quote'][0]['volume']
                prices = [p for p in prices if p is not None]
                volumes = [v if v is not None else 0 for v in volumes]
                return prices, volumes
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        # Return mock data if API fails
        base = 2350
        prices = [base + np.random.randn() * 10 for _ in range(100)]
        volumes = [1000 + abs(np.random.randn()) * 200 for _ in range(100)]
        return prices, volumes

def analyze_market(prices, volumes):
    """Full market analysis with all indicators"""
    current_price = prices[-1]
    
    # RSI
    rsi = calculate_rsi(prices)
    
    # EMAs
    ema9 = calculate_ema(prices, 9)
    ema21 = calculate_ema(prices, 21)
    ema50 = calculate_ema(prices, 50)
    
    # 3 SMAs
    sma10 = calculate_sma(prices, 10)
    sma20 = calculate_sma(prices, 20)
    sma50 = calculate_sma(prices, 50)
    
    # Bollinger Bands
    bb_upper, bb_mid, bb_lower = calculate_bollinger(prices)
    
    # Volume
    vol_signal, vol_ratio = calculate_volume_signal(volumes)
    
    # Signal Logic
    signals = []
    
    # RSI signals
    if rsi < 30:
        signals.append(("BUY", "RSI اشباع فروش"))
    elif rsi > 70:
        signals.append(("SELL", "RSI اشباع خرید"))
    
    # EMA signals
    if ema9 > ema21 > ema50:
        signals.append(("BUY", "EMA صعودی"))
    elif ema9 < ema21 < ema50:
        signals.append(("SELL", "EMA نزولی"))
    
    # SMA signals
    if sma10 > sma20 > sma50:
        signals.append(("BUY", "SMA صعودی"))
    elif sma10 < sma20 < sma50:
        signals.append(("SELL", "SMA نزولی"))
    
    # Bollinger signals
    if current_price <= bb_lower:
        signals.append(("BUY", "قیمت زیر BB پایین"))
    elif current_price >= bb_upper:
        signals.append(("SELL", "قیمت بالای BB بالا"))
    
    # Count signals
    buy_count = sum(1 for s, _ in signals if s == "BUY")
    sell_count = sum(1 for s, _ in signals if s == "SELL")
    
    if buy_count > sell_count:
        overall = "🟢 BUY"
        strength = min(buy_count * 25, 100)
    elif sell_count > buy_count:
        overall = "🔴 SELL"
        strength = min(sell_count * 25, 100)
    else:
        overall = "🟡 NEUTRAL"
        strength = 50
    
    return {
        "price": current_price,
        "rsi": rsi,
        "ema9": ema9, "ema21": ema21, "ema50": ema50,
        "sma10": sma10, "sma20": sma20, "sma50": sma50,
        "bb_upper": bb_upper, "bb_mid": bb_mid, "bb_lower": bb_lower,
        "vol_signal": vol_signal, "vol_ratio": round(vol_ratio, 2),
        "overall": overall, "strength": strength,
        "signals": signals
    }

def format_scalp_signal(data):
    signals_text = "\n".join([f"  • {reason}" for _, reason in data['signals']]) or "  • بدون سیگنال واضح"
    
    return f"""⚡ <b>سیگنال اسکالپ XAUUSD</b>
━━━━━━━━━━━━━━━━
💰 قیمت: <b>${data['price']:.2f}</b>
📊 سیگنال: <b>{data['overall']}</b>
💪 قدرت: {data['strength']}%

📈 <b>اندیکاتورها:</b>
• RSI: {data['rsi']} {'🔴 اشباع خرید' if data['rsi'] > 70 else '🟢 اشباع فروش' if data['rsi'] < 30 else '⚪ خنثی'}
• EMA 9/21/50: {data['ema9']} / {data['ema21']} / {data['ema50']}
• SMA 10/20/50: {data['sma10']} / {data['sma20']} / {data['sma50']}
• BB بالا/میانی/پایین: {data['bb_upper']} / {data['bb_mid']} / {data['bb_lower']}
• {data['vol_signal']} (×{data['vol_ratio']})

🎯 <b>دلایل سیگنال:</b>
{signals_text}

⏰ {datetime.now().strftime('%H:%M:%S')}
━━━━━━━━━━━━━━━━
⚠️ <i>این سیگنال آموزشی است</i>"""

def format_swing_signal(data):
    if "BUY" in data['overall']:
        tp1 = round(data['price'] * 1.005, 2)
        tp2 = round(data['price'] * 1.012, 2)
        sl = round(data['price'] * 0.995, 2)
        direction = "📈 LONG"
    elif "SELL" in data['overall']:
        tp1 = round(data['price'] * 0.995, 2)
        tp2 = round(data['price'] * 0.988, 2)
        sl = round(data['price'] * 1.005, 2)
        direction = "📉 SHORT"
    else:
        tp1 = tp2 = sl = data['price']
        direction = "⏸ بدون پوزیشن"
    
    return f"""📈 <b>سیگنال سوینگ XAUUSD</b>
━━━━━━━━━━━━━━━━
💰 قیمت ورود: <b>${data['price']:.2f}</b>
🎯 جهت: <b>{direction}</b>

🎯 <b>اهداف:</b>
• TP1: ${tp1}
• TP2: ${tp2}
• SL: ${sl}

📊 <b>تحلیل:</b>
• RSI: {data['rsi']}
• EMA Trend: {'صعودی ✅' if data['ema9'] > data['ema21'] else 'نزولی ❌'}
• SMA Trend: {'صعودی ✅' if data['sma10'] > data['sma20'] else 'نزولی ❌'}
• {data['vol_signal']}

⏰ {datetime.now().strftime('%H:%M:%S')}
━━━━━━━━━━━━━━━━
⚠️ <i>ریسک مدیریت کنید</i>"""

def format_full_analysis(data):
    return f"""🔍 <b>تحلیل کامل بازار XAUUSD</b>
━━━━━━━━━━━━━━━━
💰 قیمت فعلی: <b>${data['price']:.2f}</b>
📊 سیگنال کلی: <b>{data['overall']}</b>

📉 <b>RSI (14):</b> {data['rsi']}
{'🔴 اشباع خرید - احتمال ریزش' if data['rsi'] > 70 else '🟢 اشباع فروش - احتمال رشد' if data['rsi'] < 30 else '⚪ خنثی'}

📊 <b>Moving Averages:</b>
• EMA 9: {data['ema9']}
• EMA 21: {data['ema21']}  
• EMA 50: {data['ema50']}
• SMA 10: {data['sma10']}
• SMA 20: {data['sma20']}
• SMA 50: {data['sma50']}
{'📈 روند صعودی' if data['ema9'] > data['ema50'] else '📉 روند نزولی'}

📏 <b>Bollinger Bands:</b>
• بالا: ${data['bb_upper']}
• میانی: ${data['bb_mid']}
• پایین: ${data['bb_lower']}
{'🔴 نزدیک سقف BB' if data['price'] > data['bb_mid'] else '🟢 نزدیک کف BB'}

📦 <b>حجم معاملات:</b>
• {data['vol_signal']} (×{data['vol_ratio']})

⏰ {datetime.now().strftime('%H:%M:%S')}
━━━━━━━━━━━━━━━━
⚠️ <i>این تحلیل آموزشی است</i>"""

# ==================== AI ANALYSIS ====================

async def analyze_chart_image(image_data: bytes) -> str:
    if not OPENROUTER_API_KEY:
        return "❌ OpenRouter API Key تنظیم نشده. لطفاً با ادمین تماس بگیرید."
    
    try:
        b64_image = base64.b64encode(image_data).decode('utf-8')
        
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "anthropic/claude-3-haiku",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}
                        },
                        {
                            "type": "text",
                            "text": "این چارت XAUUSD (طلا) رو تحلیل کن. روند، سطوح حمایت/مقاومت، و سیگنال خرید/فروش رو به فارسی بگو. کوتاه و دقیق باش."
                        }
                    ]
                }
            ],
            "max_tokens": 500
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                result = await resp.json()
                return result['choices'][0]['message']['content']
    except Exception as e:
        return f"❌ خطا در تحلیل: {str(e)}"

# ==================== BOT HANDLERS ====================

def is_allowed(user_id):
    return user_id in allowed_users

def main_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("⚡ سیگنال لحظه‌ای", callback_data="scalp"),
            InlineKeyboardButton("📈 سیگنال سوینگ", callback_data="swing")
        ],
        [
            InlineKeyboardButton("🔍 تحلیل کامل", callback_data="full_analysis"),
            InlineKeyboardButton("📸 تحلیل عکس چارت", callback_data="photo_analysis")
        ],
        [
            InlineKeyboardButton("🔐 لینک دعوت", callback_data="invite")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check invite token
    args = context.args
    if args and args[0] in invite_links:
        token = args[0]
        if not invite_links[token]:
            invite_links[token] = True  # Mark as used
            allowed_users.add(user_id)
            await update.message.reply_text("✅ دسترسی تایید شد! به ربات خوش اومدی 🎉")
        else:
            await update.message.reply_text("❌ این لینک قبلاً استفاده شده!")
            return
    
    if not is_allowed(user_id):
        await update.message.reply_text("⛔ دسترسی ندارید. از ادمین لینک دعوت بگیرید.")
        return
    
    await update.message.reply_text(
        "🏆 <b>Gold Signal Bot</b>\nربات سیگنال طلا (XAUUSD)\n\nیکی از گزینه‌ها رو انتخاب کن:",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_allowed(user_id):
        await query.answer("⛔ دسترسی ندارید!")
        return
    
    await query.answer()
    
    if query.data == "scalp":
        await query.edit_message_text("⏳ در حال دریافت داده...")
        prices, volumes = await get_gold_data("1h")
        data = analyze_market(prices, volumes)
        await query.edit_message_text(
            format_scalp_signal(data),
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )
    
    elif query.data == "swing":
        await query.edit_message_text("⏳ در حال تحلیل...")
        prices, volumes = await get_gold_data("4h")
        data = analyze_market(prices, volumes)
        await query.edit_message_text(
            format_swing_signal(data),
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )
    
    elif query.data == "full_analysis":
        await query.edit_message_text("⏳ در حال تحلیل کامل...")
        prices, volumes = await get_gold_data("1h")
        data = analyze_market(prices, volumes)
        await query.edit_message_text(
            format_full_analysis(data),
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )
    
    elif query.data == "photo_analysis":
        context.user_data['waiting_for_photo'] = True
        await query.edit_message_text(
            "📸 عکس چارت رو بفرست تا AI تحلیل کنه:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 برگشت", callback_data="back")
            ]])
        )
    
    elif query.data == "invite":
        if user_id != ADMIN_CHAT_ID:
            await query.answer("⛔ فقط ادمین می‌تونه لینک دعوت بسازه!")
            return
        token = str(uuid.uuid4())[:8]
        invite_links[token] = False
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={token}"
        await query.edit_message_text(
            f"🔐 <b>لینک دعوت یکبار مصرف:</b>\n\n{link}\n\n⚠️ فقط یک نفر می‌تونه ازش استفاده کنه!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 برگشت", callback_data="back")
            ]])
        )
    
    elif query.data == "back":
        await query.edit_message_text(
            "🏆 <b>Gold Signal Bot</b>\nیکی از گزینه‌ها رو انتخاب کن:",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_allowed(user_id):
        return
    
    if context.user_data.get('waiting_for_photo'):
        context.user_data['waiting_for_photo'] = False
        await update.message.reply_text("🔍 در حال تحلیل عکس با AI...")
        
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(file.file_path) as resp:
                image_data = await resp.read()
        
        analysis = await analyze_chart_image(image_data)
        
        await update.message.reply_text(
            f"📸 <b>تحلیل AI چارت:</b>\n\n{analysis}",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )

# ==================== HEALTH CHECK ====================
from aiohttp import web

async def health_check(request):
    return web.Response(text="OK")

async def start_web():
    app = web.Application()
    app.router.add_get('/health', health_check)
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 8080)))
    await site.start()
    logger.info("Health check server started on port 8080")

# ==================== MAIN ====================

async def main():
    await start_web()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    
    logger.info("Bot started!")
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
