# ============================================================
# TELEGRAM USER ACTIVITY TRACKER
# ============================================================
#
# Система мониторинга активности пользователей Telegram
#
# 📋 Функции:
#   • Отслеживание входов/выходов пользователей в реальном времени
#   • Построение интерактивных графиков активности
#   • Анализ пересечений сессий (совпадения онлайна)
#   • Полный архив сессий с сохранением в JSON
#
# 📦 Зависимости:
#   pip install telethon aiogram matplotlib rich
#
# 🔗 Документация:
#   - Telethon: https://docs.telethon.dev
#   - Aiogram: https://docs.aiogram.dev
#
# ============================================================

import asyncio, os, io, json, traceback
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import UpdateUserStatus, UserStatusOnline, UserStatusOffline
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
)

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

console = Console()

# Telegram API Credentials
# Получить API_ID и API_HASH на https://my.telegram.org/apps
API_ID = int(os.getenv("TELEGRAM_API_ID", "YOUR_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "YOUR_API_HASH")

# Telegram Bot Token
# Получить от @BotFather в Telegram
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")

# ID пользователей с доступом (разделять запятой)
# Получить свой ID: @userinfobot в Telegram
WHITELIST_IDS = [
    int(uid.strip()) for uid in 
    os.getenv("WHITELIST_IDS", "YOUR_USER_ID_1,YOUR_USER_ID_2").split(",")
]

# Секретный пароль для входа в бот
SECRET_PASS = os.getenv("SECRET_PASS", "YOUR_SECRET_PASSWORD")

# Файлы данных
SESSION_FILE = "session.session"
TARGETS_FILE = "targets.txt"
DB_FILE = "sessions_db.json"
LOG_ONLINE = "online.log"
LOG_ERRORS = "errors.log"

# Временные параметры
MY_TIMEZONE = timezone(timedelta(hours=5))
SCAN_INTERVAL = 10
MESSAGE_AUTO_DELETE_DELAY = 30

# ============================================================
# СОСТОЯНИЕ И ПАМЯТИ
# ============================================================

users_info = {}
online_status = {}
online_start_times = {}
session_history = {}
authenticated_users = {}
tracked_ids = set()
sent_messages = {}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ============================================================
# РАБОТА С ХРАНИЛИЩЕМ
# ============================================================

def write_error_log(message: str):
    """Записывает ошибки в лог файл"""
    try:
        with open(LOG_ERRORS, "a", encoding="utf-8") as f:
            timestamp = datetime.now(MY_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass

def save_db():
    """Сохраняет историю сессий в JSON"""
    try:
        data = {
            "history": {
                str(k): [[s.isoformat(), e.isoformat()] for s, e in v]
                for k, v in session_history.items()
            },
            "info": users_info
        }
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as ex:
        write_error_log(f"save_db error: {ex}\n{traceback.format_exc()}")

def load_db():
    """Загружает историю сессий из JSON"""
    global session_history, users_info
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                h = raw.get("history", {})
                for uid, sessions in h.items():
                    if uid.isdigit():
                        try:
                            session_history[int(uid)] = [
                                [datetime.fromisoformat(s), datetime.fromisoformat(e)]
                                for s, e in sessions
                            ]
                        except Exception:
                            write_error_log(f"load_db: failed parsing sessions for uid={uid}")
                users_info.update(raw.get("info", {}))
        except Exception as ex:
            write_error_log(f"load_db error: {ex}\n{traceback.format_exc()}")

def get_targets():
    """Получает список целей отслеживания"""
    if not os.path.exists(TARGETS_FILE):
        return []
    with open(TARGETS_FILE, "r", encoding="utf-8") as f:
        return list(dict.fromkeys([l.strip() for l in f if l.strip()]))

def save_targets(targets):
    """Сохраняет список целей"""
    try:
        with open(TARGETS_FILE, "w", encoding="utf-8") as f:
            for t in targets:
                f.write(f"{t}\n")
    except Exception as ex:
        write_error_log(f"save_targets error: {ex}")

def write_online_log(message):
    """Записывает события входа/выхода"""
    try:
        with open(LOG_ONLINE, "a", encoding="utf-8") as f:
            timestamp = datetime.now(MY_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass

# ============================================================
# ГЕНЕРАЦИЯ ГРАФИКОВ
# ============================================================

def generate_chart():
    """
    Генерирует профессиональный график активности с улучшенной визуализацией.
    Показывает временные интервалы каждого пользователя горизонтальными линиями.
    Включает только отслеживаемых пользователей.
    """
    if not session_history: 
        return None
    
    targets = get_targets()
    
    # Фильтруем только отслеживаемых пользователей
    filtered_uids = []
    for uid in session_history.keys():
        uid_str = str(uid)
        for target in targets:
            if uid_str == target or users_info.get(uid_str, {}).get('username') == target.replace('@', ''):
                filtered_uids.append(uid)
                break
    
    if not filtered_uids:
        return None
    
    # Находим диапазон дат в данных
    all_dates = []
    for uid in filtered_uids:
        for start, end in session_history[uid]:
            all_dates.extend([start, end])
    
    if all_dates:
        min_date = min(all_dates)
        max_date = max(all_dates)
        date_range = f"{min_date.strftime('%d.%m.%Y')} — {max_date.strftime('%d.%m.%Y')}"
    else:
        date_range = "Период не определен"
    
    # Динамический размер: широко (для 6-часовых интервалов) и высоко (для близко расположенных пользователей)
    height = max(3, len(filtered_uids) * 0.6)
    figsize = (22, height)
    plt.figure(figsize=figsize, dpi=120)
    plt.style.use('dark_background')
    
    y_labels = []
    colors = ['#00D9FF', '#00FF88', '#FFD700', '#FF6B9D', '#C77DFF', '#06FFA5', '#FFB703', '#FB5607']
    
    for i, uid in enumerate(filtered_uids):
        info = users_info.get(str(uid), {})
        name = info.get('first_name', str(uid))
        y_labels.append(name)
        
        sessions = session_history[uid]
        color = colors[i % len(colors)]
        
        for idx, (start, end) in enumerate(sessions):
            try:
                x_start = mdates.date2num(start)
                x_end = mdates.date2num(end)
                # Толстые полосы для видимости даже коротких сессий
                plt.hlines(i, x_start, x_end, colors=color, lw=28, alpha=0.85)
                
            except Exception:
                pass
    
    ax = plt.gca()
    ax.set_yticks(range(len(y_labels)))
    ax.set_yticklabels(y_labels, fontsize=12, fontweight='bold')
    ax.set_xlabel('Дата и время', fontsize=13, fontweight='bold')
    
    # Заголовок с периодом
    title = f'График активности отслеживаемых пользователей\n{date_range}'
    ax.set_title(title, fontsize=15, fontweight='bold', pad=20)
    
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m %H:%M'))
    # Интервал на 6 часов для лучшей читаемости
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
    
    # Время на нижней оси
    ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
    
    plt.xticks(rotation=45, fontsize=10, ha='right')
    plt.yticks(fontsize=11)
    
    ax.grid(True, axis='x', linestyle='--', alpha=0.25, linewidth=0.7, which='major')
    ax.grid(True, axis='x', linestyle=':', alpha=0.1, linewidth=0.5, which='minor')
    ax.set_facecolor('#0a0e27')
    
    # Пользователи расположены очень близко друг к другу
    ax.set_ylim(-0.35, len(filtered_uids) - 0.65)
    
    # Добавляем легенду если много пользователей
    if len(filtered_uids) > 1:
        from matplotlib.patches import Rectangle
        legend_elements = [Rectangle((0, 0), 1, 1, fc=colors[i % len(colors)], alpha=0.85) 
                          for i in range(len(filtered_uids))]
        ax.legend(legend_elements, y_labels, loc='upper right', fontsize=10, 
                 framealpha=0.9, edgecolor='#444', ncol=1)
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=120, facecolor='#0a0e27', edgecolor='none', bbox_inches='tight')
    buf.seek(0)
    plt.close('all')
    return buf



# ============================================================
# ОСНОВНОЙ ИНТЕРФЕЙС БОТА
# ============================================================

async def delete_message_later(message: types.Message, delay: int = MESSAGE_AUTO_DELETE_DELAY):
    """Автоматически удаляет сообщение через N секунд"""
    try:
        await asyncio.sleep(delay)
        await message.delete()
    except Exception:
        pass


async def send_tracked_message(user_id: int, text: str, **kwargs):
    """Отправляет сообщение и отслеживает его для очистки"""
    try:
        msg = await bot.send_message(user_id, text, **kwargs)
        if user_id not in sent_messages:
            sent_messages[user_id] = []
        sent_messages[user_id].append(msg.message_id)
        return msg
    except Exception:
        return None


async def cleanup_old_messages(user_id: int):
    """Удаляет старые отслеживаемые сообщения при перезагрузке"""
    if user_id not in sent_messages:
        return
    msg_ids = sent_messages.pop(user_id, [])
    for msg_id in msg_ids[-20:]:
        try:
            await bot.delete_message(user_id, msg_id)
            await asyncio.sleep(0.1)
        except Exception:
            pass

# ============================================================
# АУТЕНТИФИКАЦИЯ
# ============================================================

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    """Команда /start — проверка доступа"""
    if message.from_user.id in WHITELIST_IDS:
        await message.answer("🔐 Введите пароль:")


@dp.message(F.text == SECRET_PASS)
async def auth_process(message: types.Message):
    """Ввод пароля — активация доступа"""
    authenticated_users[message.from_user.id] = True
    await message.delete()
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 График"), KeyboardButton(text="📄 Отчет")],
        [KeyboardButton(text="📋 Список"), KeyboardButton(text="🔗 Совпадения")],
        [KeyboardButton(text="📦 Архив"), KeyboardButton(text="🔒 Выход")]
    ], resize_keyboard=True)
    await message.answer("🔓 Доступ разрешен:", reply_markup=kb)

# ============================================================
# Обработчики меню отслеживания
# ============================================================

@dp.message(F.text == "📋 Список")
async def btn_show_targets(message: types.Message):
    """Выводит список отслеживаемых целей с актуальным статусом."""
    if message.from_user.id not in authenticated_users:
        return
    targets = get_targets()
    if not targets:
        msg = await message.answer("🎯 Список пуст.")
        asyncio.create_task(delete_message_later(msg, 15))
        return
    
    # Формируем улучшенный список
    lines = []
    for i, t in enumerate(targets, start=1):
        display_name = t
        uid_int = None
        
        # Ищем информацию о пользователе
        for uid_str, info in users_info.items():
            if uid_str == t or info.get('username') == t.replace('@',''):
                display_name = info.get('first_name', display_name)
                if uid_str.isdigit():
                    uid_int = int(uid_str)
                break
        
        # Статус и время
        status_icon = "🟢"
        time_info = "нет данных"
        
        if uid_int and uid_int in online_status and online_status[uid_int]:
            # Онлайн сейчас
            start_t = online_start_times.get(uid_int)
            if start_t:
                elapsed = int((datetime.now(MY_TIMEZONE) - start_t).total_seconds())
                mins, secs = divmod(elapsed, 60)
                time_info = f"онлайн {mins}м {secs}с"
        else:
            # Офлайн
            status_icon = "⚪️"
            info = users_info.get(str(uid_int) if uid_int else t, {})
            last_seen = info.get('last_seen', 'нет данных')
            time_info = f"был(а) {last_seen}"
        
        lines.append(f"{i}. {status_icon} <b>{display_name}</b>\n   {time_info}")
    
    text = "📋 <b>СПИСОК ОТСЛЕЖИВАНИЯ:</b>\n\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛠️ Управлять", callback_data="manage_targets")],
    ])
    msg = await message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "back_list")
async def back_list_cb(callback: types.CallbackQuery):
    """Возвращает пользователя в меню отслеживания после управления."""
    targets = get_targets()
    if not targets:
        text = "🎯 Список пуст."
        kb = InlineKeyboardMarkup(inline_keyboard=[])
    else:
        lines = []
        for i, t in enumerate(targets, start=1):
            display_name = t
            uid_int = None
            for uid_str, info in users_info.items():
                if uid_str == t or info.get('username') == t.replace('@',''):
                    display_name = info.get('first_name', display_name)
                    if uid_str.isdigit():
                        uid_int = int(uid_str)
                    break
            
            status_icon = "🟢"
            time_info = "нет данных"
            if uid_int and uid_int in online_status and online_status[uid_int]:
                start_t = online_start_times.get(uid_int)
                if start_t:
                    elapsed = int((datetime.now(MY_TIMEZONE) - start_t).total_seconds())
                    mins, secs = divmod(elapsed, 60)
                    time_info = f"онлайн {mins}м {secs}с"
            else:
                status_icon = "⚪️"
                info = users_info.get(str(uid_int) if uid_int else t, {})
                last_seen = info.get('last_seen', 'нет данных')
                time_info = f"был(а) {last_seen}"
            
            lines.append(f"{i}. {status_icon} <b>{display_name}</b>\n   {time_info}")
        
        text = "📋 <b>СПИСОК ОТСЛЕЖИВАНИЯ:</b>\n\n" + "\n".join(lines)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛠️ Управлять", callback_data="manage_targets")],
        ])
    
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data == "manage_targets")
async def manage_targets_cb(callback: types.CallbackQuery):
    """Показывает список целей для удаления."""
    targets = get_targets()
    if not targets:
        await callback.answer("Список пуст.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for t in targets:
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"🗑 {t}", callback_data=f"del_{t}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад в список", callback_data="back_list")])
    try:
        await callback.message.edit_text("Выберите цель для удаления:", reply_markup=kb)
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data.startswith("del_"))
async def delete_user(callback: types.CallbackQuery):
    """Удаляет цель из списка отслеживания."""
    target = callback.data.replace("del_", "")
    targets = get_targets()
    if target in targets:
        targets.remove(target)
        save_targets(targets)
        await callback.answer("✅ Удалено")
        # Вернуться в меню управления
        remaining_targets = get_targets()
        if remaining_targets:
            kb = InlineKeyboardMarkup(inline_keyboard=[])
            for t in remaining_targets:
                kb.inline_keyboard.append([InlineKeyboardButton(text=f"🗑 {t}", callback_data=f"del_{t}")])
            kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад в список", callback_data="back_list")])
            try:
                await callback.message.edit_text("Выберите цель для удаления:", reply_markup=kb)
            except Exception:
                pass
        else:
            try:
                await callback.message.edit_text("🎯 Список пуст.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
            except Exception:
                pass

# ============================================================
# ОТЧЕТЫ И АНАЛИЗ
# ============================================================

@dp.message(F.text == "📄 Отчет")
async def btn_report(message: types.Message):
    """Отчет активности — кто онлайн, последние сессии"""
    if message.from_user.id not in authenticated_users:
        return

    report = "📋 <b>ОТЧЕТ АКТИВНОСТИ</b>\n" + "—" * 20 + "\n"
    report += "📡 <b>СЕЙЧАС В СЕТИ:</b>\n"
    current_online = False

    for uid_int, is_on in online_status.items():
        if is_on:
            info = users_info.get(str(uid_int), {})
            name = info.get('first_name', f"ID: {uid_int}")
            report += f" 🟢 {name}\n"
            current_online = True

    if not current_online:
        report += " ⚪️ Никого нет\n"
    
    report += "—" * 20 + "\n📜 <b>ПОСЛЕДНИЕ СЕССИИ:</b>\n"

    if not session_history:
        report += " История пока пуста"
    else:
        for uid_int, sessions in list(session_history.items())[-5:]:
            info = users_info.get(str(uid_int), {})
            name = info.get('first_name', f"ID: {uid_int}")
            report += f"👤 <b>{name}:</b>\n"
            for start, end in sessions[-3:]:
                dur = int((end - start).total_seconds())
                report += f"  └ {start.strftime('%H:%M')} - {end.strftime('%H:%M')} ({dur}с)\n"

    await message.answer(report, parse_mode="HTML")

@dp.message(F.text == "🔗 Совпадения")
async def btn_intersections(message: types.Message):
    """Показывает меню выбора периода для анализа совпадений сессий."""
    if message.from_user.id not in authenticated_users: 
        return
    if not session_history or len(session_history) < 2:
        msg = await message.answer("⚠️ Нужно минимум 2 цели с сохраненной историей.")
        asyncio.create_task(delete_message_later(msg, 10))
        return

    today = datetime.now(MY_TIMEZONE).date()
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    kb.inline_keyboard.append([InlineKeyboardButton(text="📅 За последние 5 дней", callback_data="arch_last5")])
    dates_row = []
    for d in range(0, 5):
        date_val = today - timedelta(days=d)
        dates_row.append(InlineKeyboardButton(text=date_val.strftime("%d.%m"), callback_data=f"arch_date_{date_val.isoformat()}"))
    for i in range(0, len(dates_row), 3):
        kb.inline_keyboard.append(dates_row[i:i+3])
    await message.answer("🔍 Выберите период для анализа совпадений:", reply_markup=kb)

@dp.message(F.text == "📦 Архив")
async def btn_archive(message: types.Message):
    """Показывает меню выбора даты для просмотра архива сессий."""
    if message.from_user.id not in authenticated_users:
        return
    if not session_history:
        msg = await message.answer("📦 Архив пуст. Нет сохраненных сессий.")
        asyncio.create_task(delete_message_later(msg, 15))
        return
    
    today = datetime.now(MY_TIMEZONE).date()
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    kb.inline_keyboard.append([InlineKeyboardButton(text="📅 За последние 5 дней", callback_data="arch_last5")])
    dates_row = []
    for d in range(0, 5):
        date_val = today - timedelta(days=d)
        dates_row.append(InlineKeyboardButton(text=date_val.strftime("%d.%m"), callback_data=f"arch_date_{date_val.isoformat()}"))
    for i in range(0, len(dates_row), 3):
        kb.inline_keyboard.append(dates_row[i:i+3])
    await message.answer("📦 Выберите дату для просмотра архива:", reply_markup=kb)

@dp.callback_query(F.data == "arch_last5")
async def arch_last5_cb(callback: types.CallbackQuery):
    """Анализирует совпадения за последние 5 дней."""
    await _send_intersections_for_range(callback.message, days=5)
    await callback.answer()

@dp.callback_query(F.data.startswith("arch_date_"))
async def arch_date_cb(callback: types.CallbackQuery):
    """Анализирует совпадения за выбранную дату."""
    iso = callback.data.replace("arch_date_", "")
    try:
        target_date = datetime.fromisoformat(iso).date()
        start_dt = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=MY_TIMEZONE)
        end_dt = datetime.combine(target_date, datetime.max.time()).replace(tzinfo=MY_TIMEZONE)
        await _send_intersections_for_range(callback.message, start=start_dt, end=end_dt, title=f"Пересечения за {target_date.strftime('%d.%m.%Y')}")
    except Exception as ex:
        await callback.message.answer(f"❌ Ошибка: {str(ex)}")
    await callback.answer()

async def _send_intersections_for_range(message_obj, days: int = None, start: datetime = None, end: datetime = None, title: str = None):
    """
    Анализирует и отправляет отчет о совпадениях сессий за период.
    Фильтрует только целей из текущего списка отслеживания.
    """
    if days:
        end = datetime.now(MY_TIMEZONE)
        start = end - timedelta(days=days)
        title = title or f"Совпадения за последние {days} дней"
    if start is None or end is None:
        return await message_obj.answer("Неверный диапазон дат.")
    
    targets = get_targets()
    report = f"🔍 <b>{title}</b>\n" + "—"*20 + "\n"
    found_any = False
    
    uids = [uid for uid in session_history.keys() if any(str(uid) == t or users_info.get(str(uid), {}).get('username') == t.replace('@','') for t in targets)]
    
    for i in range(len(uids)):
        for j in range(i + 1, len(uids)):
            u1, u2 = uids[i], uids[j]
            n1 = users_info.get(str(u1), {}).get('first_name', str(u1))
            n2 = users_info.get(str(u2), {}).get('first_name', str(u2))
            
            for s1, e1 in session_history[u1]:
                s1r, e1r = max(s1, start), min(e1, end)
                if s1r >= e1r:
                    continue
                for s2, e2 in session_history[u2]:
                    s2r, e2r = max(s2, start), min(e2, end)
                    if s2r >= e2r:
                        continue
                    si, ei = max(s1r, s2r), min(e1r, e2r)
                    if si < ei:
                        dur = int((ei - si).total_seconds())
                        if dur > 0:
                            found_any = True
                            report += f"🔹 <b>{n1}</b> + <b>{n2}</b>\n"
                            report += f"  📅 {si.strftime('%d.%m.%Y')}  ⏱ {si.strftime('%H:%M:%S')} - {ei.strftime('%H:%M:%S')}  ({dur} сек.)\n\n"
    
    if not found_any:
        report += "Пересечений не найдено."
    
    try:
        await message_obj.answer(report, parse_mode="HTML")
    except Exception as ex:
        write_error_log(f"_send_intersections_for_range error: {ex}")






@dp.message(F.text == "📊 График")
async def btn_show_chart(message: types.Message):
    """Генерирует и отправляет график активности по дням."""
    if message.from_user.id not in authenticated_users: 
        return
    
    msg = await message.answer("⏳ Генерирую график активности...")
    try:
        buf = generate_chart()
        if not buf:
            await msg.edit_text("📊 Нет данных для графика. Добавьте цели и дождитесь сессий.")
            return
        
        buf.seek(0)
        chart_data = buf.read()
        
        await message.answer_photo(
            BufferedInputFile(chart_data, filename="activity_chart.png"),
            caption="📊 <b>График активности</b>\nВизуализация сессий пользователей во времени",
            parse_mode="HTML"
        )
        try:
            await msg.delete()
        except Exception:
            pass
            
    except Exception as ex:
        try:
            await msg.edit_text(f"❌ Ошибка при генерации графика: {str(ex)[:80]}")
        except Exception:
            await message.answer(f"❌ Ошибка: {str(ex)[:80]}")
        write_error_log(f"btn_show_chart error: {ex}\n{traceback.format_exc()}")



@dp.message(F.text == "🔒 Выход")
async def btn_logout(message: types.Message):
    """Завершает сеанс пользователя."""
    authenticated_users.pop(message.from_user.id, None)
    await message.answer("🔒 Выход выполнен.", reply_markup=ReplyKeyboardRemove())

# ============================================================
# Обработчик добавления целей
# ============================================================

@dp.message(F.text)
async def handle_text(message: types.Message):
    """Обрабатывает ввод пользователя для добавления целей отслеживания."""
    if message.from_user.id not in authenticated_users: return
    text = message.text.strip()
    if text in ["📊 График", "📄 Отчет", "📋 Список", "🔒 Выход", "🔗 Совпадения", "📦 Архив", SECRET_PASS]: return

    # Валидация: только @username или ID (только цифры)
    is_username = text.startswith('@') and len(text) > 1 and text[1:].replace('_', '').isalnum()
    is_id = text.isdigit() and len(text) >= 5
    
    if not is_username and not is_id:
        msg = await message.answer("❌ Вводите либо юзернейм (<code>@username</code>), либо ID (только цифры).", parse_mode="HTML")
        asyncio.create_task(delete_message_later(msg, 10))
        return
    
    targets = get_targets()
    if text not in targets:
        targets.append(text)
        save_targets(targets)
        msg = await message.answer(f"✅ Цель <code>{text}</code> добавлена.\nТрекер подхватит её через {SCAN_INTERVAL} сек.", parse_mode="HTML")
        asyncio.create_task(delete_message_later(msg, 20))
    else:
        msg = await message.answer("ℹ️ Эта цель уже есть в списке.")
        asyncio.create_task(delete_message_later(msg, 10))

# ============================================================
# ОСНОВНОЙ ЦИКЛ МОНИТОРИНГА
# ============================================================

async def run_tracker(client):
    """Основной цикл — сканирование статуса целей каждые N секунд"""
    load_db()
    console.print(Panel(
        "[bold green]✅ СИСТЕМА ЗАПУЩЕНА[/bold green]\n"
        f"[white]Интервал: {SCAN_INTERVAL} сек[/white]",
        border_style="cyan", title="[bold]Статус[/bold]"
    ))
    
    while True:
        targets = get_targets()
        if not targets:
            console.print("[yellow]⏳ Список целей пуст[/yellow]")
            await asyncio.sleep(SCAN_INTERVAL)
            continue

        table = Table(
            title=f"📡 Сканирование: {datetime.now().strftime('%H:%M:%S')}",
            header_style="bold magenta", border_style="dim"
        )
        table.add_column("Имя", style="bold white")
        table.add_column("ID", style="cyan")
        table.add_column("Статус", justify="center")
        
        now = datetime.now(MY_TIMEZONE)
        tracked_ids.clear()
        
        for t in targets:
            try:
                try:
                    entity = int(t) if t.isdigit() else t
                    user = await client.get_entity(entity)
                except:
                    full = await client(GetFullUserRequest(t))
                    user = full.users[0]

                uid = user.id
                tracked_ids.add(uid)
                
                is_on = False
                last_seen_str = "скрыто"
                
                if getattr(user, "status", None):
                    st_cls = user.status.__class__.__name__
                    if st_cls == "UserStatusOnline":
                        is_on = True
                    elif st_cls == "UserStatusOffline" and hasattr(user.status, 'was_online'):
                        last_ts = user.status.was_online
                        try:
                            last_seen_str = last_ts.astimezone(MY_TIMEZONE).strftime("%d.%m %H:%M")
                        except Exception:
                            if isinstance(last_ts, (int, float)):
                                last_seen_str = datetime.fromtimestamp(
                                    int(last_ts), tz=MY_TIMEZONE
                                ).strftime("%d.%m %H:%M")
                            else:
                                last_seen_str = str(last_ts)

                current_info = users_info.get(str(uid), {})
                new_last_seen = (
                    last_seen_str if last_seen_str != "скрыто"
                    else current_info.get('last_seen', "скрыто")
                )
                
                users_info[str(uid)] = {
                    'first_name': user.first_name or "Без имени",
                    'username': user.username or "—",
                    'last_seen': new_last_seen
                }

                if is_on and not online_status.get(uid):
                    online_status[uid] = True
                    online_start_times[uid] = now
                    write_online_log(f"LOGIN: {user.first_name}")

                elif not is_on and online_status.get(uid):
                    online_status[uid] = False
                    start_t = online_start_times.get(uid)
                    
                    if start_t:
                        session_history.setdefault(uid, []).append([start_t, now])
                        save_db()
                        
                        dur = int((now - start_t).total_seconds())
                        for cid in list(authenticated_users.keys()):
                            try:
                                await send_tracked_message(
                                    cid, f"🔴 <b>{user.first_name}</b> вышел ({dur}с)",
                                    parse_mode="HTML"
                                )
                            except Exception:
                                pass
                    
                    write_online_log(f"LOGOUT: {user.first_name}")

                st_icon = "[green]●[/green] ONLINE" if is_on else f"[dim]○ {last_seen_str}[/dim]"
                table.add_row(user.first_name or "Без имени", str(t), st_icon)

            except Exception as e:
                table.add_row(str(t), "—", f"[red]❌ {str(e)[:20]}[/red]")

        console.clear()
        console.print(table)
        console.print(f"[dim]Целей: {len(targets)}[/dim]")
        await asyncio.sleep(SCAN_INTERVAL)

# ============================================================
# ОБРАБОТЧИКИ СОБЫТИЙ TELETHON
# ============================================================

def register_event_handlers(client):
    """Регистрирует обработчик real-time событий смены статуса"""
    @client.on(events.Raw(UpdateUserStatus))
    async def _on_user_status(update):
        try:
            u_id = getattr(update, "user_id", None)
            status = getattr(update, "status", None)
            if u_id is None or u_id not in tracked_ids:
                return

            display_name = users_info.get(str(u_id), {}).get("first_name", str(u_id))

            if isinstance(status, UserStatusOnline):
                if not online_status.get(u_id):
                    online_status[u_id] = True
                    online_start_times[u_id] = datetime.now(MY_TIMEZONE)
                    write_online_log(f"LOGIN(event): {display_name}")
                    for cid in list(authenticated_users.keys()):
                        try:
                            await send_tracked_message(
                                cid, f"🟢 <b>{display_name}</b> вошел",
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass

            elif isinstance(status, UserStatusOffline):
                was_online = getattr(status, "was_online", None)
                end_dt = None
                try:
                    if isinstance(was_online, (int, float)):
                        end_dt = datetime.fromtimestamp(int(was_online), tz=MY_TIMEZONE)
                    elif hasattr(was_online, "astimezone"):
                        end_dt = was_online.astimezone(MY_TIMEZONE)
                except Exception:
                    end_dt = None

                if online_status.get(u_id):
                    online_status[u_id] = False
                    start_t = online_start_times.get(u_id)
                    if end_dt is None:
                        end_dt = datetime.now(MY_TIMEZONE)
                    if start_t and start_t <= end_dt:
                        session_history.setdefault(u_id, []).append([start_t, end_dt])
                        try:
                            save_db()
                        except Exception:
                            pass
                        dur = int((end_dt - start_t).total_seconds())
                        for cid in list(authenticated_users.keys()):
                            try:
                                await send_tracked_message(
                                    cid, f"🔴 <b>{display_name}</b> вышел ({dur}с)",
                                    parse_mode="HTML"
                                )
                            except Exception:
                                pass
                    write_online_log(f"LOGOUT(event): {display_name}")
        except Exception:
            try:
                write_online_log(f"event_handler: exception")
            except Exception:
                pass

# ============================================================
# Точка входа
# ============================================================

async def main():
    """Инициализирует клиент Telegram и запускает основные циклы."""
    if not os.path.exists(SESSION_FILE):
        print("❌ Нет файла сессии!")
        return
    try:
        with open(SESSION_FILE, "r") as f:
            s = f.read().strip()
        client = TelegramClient(StringSession(s), API_ID, API_HASH)
        await client.start()
        
        print("🧹 Очистка старых сообщений...")
        for user_id in list(sent_messages.keys()):
            await cleanup_old_messages(user_id)
        
        for user_id in WHITELIST_IDS:
            try:
                await send_tracked_message(user_id, "🚀 <b>БОТ ПЕРЕЗАГРУЖЕН</b>", parse_mode="HTML")
            except Exception:
                pass
        
        register_event_handlers(client)
        print("🚀 БОТ ЗАПУЩЕН")
        await asyncio.gather(dp.start_polling(bot), run_tracker(client))
    except Exception as ex:
        write_error_log(f"main error: {ex}\n{traceback.format_exc()}")
        raise

if __name__ == "__main__":
    asyncio.run(main()) 