import telebot
from telebot import types
import sqlite3
import json
import time
import threading
from datetime import datetime
import random
import string
from channel import WithdrawalChannel  # Импортируем модуль канала

# Настройки бота
TOKEN = "8337396229:AAFe_IhYtzv9Ts2OiEVhIkHJQB0yY4NAKgg"
bot = telebot.TeleBot(TOKEN)

# Инициализация канала для уведомлений
withdrawal_channel = WithdrawalChannel(TOKEN)

# ID канала для уведомлений (замените на свой)
WITHDRAWAL_CHANNEL_ID = "-1002990005205"  # Пример ID канала

# Установка канала для уведомлений
withdrawal_channel.set_channel(WITHDRAWAL_CHANNEL_ID)

# ID администратора (замените на свой)
ADMIN_IDS = [8118184388]  # Замените на ваш ID телеграм

# Глобальные переменные для каналов
REQUIRED_CHANNELS = []

# Словарь для хранения соответствия withdrawal_id -> message_id в канале
withdrawal_messages = {}

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С КАНАЛАМИ ==========
def check_user_subscription(user_id, channel_id):
    """Проверка подписки пользователя на канал"""
    try:
        member = bot.get_chat_member(channel_id, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        print(f"Ошибка при проверке подписки: {e}")
        return False

def check_all_subscriptions(user_id):
    """Проверка всех обязательных подписок для пользователя"""
    if not REQUIRED_CHANNELS:
        return True, []  # Нет обязательных каналов

    not_subscribed = []
    all_subscribed = True

    for channel in REQUIRED_CHANNELS:
        is_subscribed = check_user_subscription(user_id, channel['channel_id'])

        if not is_subscribed:
            all_subscribed = False
            not_subscribed.append(channel)

    return all_subscribed, not_subscribed

def check_subscription_required(user_id):
    """Проверка обязательных подписок"""
    if not REQUIRED_CHANNELS:
        return True, None

    all_subscribed, not_subscribed = check_all_subscriptions(user_id)

    if all_subscribed:
        return True, None
    else:
        # Создаем сообщение с кнопками для подписки
        channels_text = "<blockquote>✅ <b>ПОДПИШИТЕСЬ НА КАНАЛЫ</b> \n\n"
        channels_text += "Для использования бота необходимо подписаться на каналы:\n\n"

        keyboard = types.InlineKeyboardMarkup()

        for channel in not_subscribed:
            channels_text += f"• {channel['channel_name']}\n"
            keyboard.add(
                types.InlineKeyboardButton(
                    f"📺 {channel['channel_name']}",
                    url=f"https://t.me/{channel['channel_username'].replace('@', '')}"
                )
            )

        channels_text += "\n✅ <b>После подписки нажмите кнопку 'Проверить подписку'</b></blockquote>"

        keyboard.add(
            types.InlineKeyboardButton("✅ Я подписался", callback_data="check_subscription_after")
        )

        return False, (channels_text, keyboard)

# ========== ФУНКЦИИ ДЛЯ ЧЕКОВ ==========
def init_checks_db():
    """Инициализация таблицы для чеков"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS checks (
            check_id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_code TEXT UNIQUE NOT NULL,
            amount INTEGER NOT NULL,
            max_activations INTEGER NOT NULL,
            current_activations INTEGER DEFAULT 0,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            description TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS check_activations (
            activation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_code TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')

    conn.commit()
    conn.close()

def generate_check_code(length=8):
    """Генерация уникального кода чека"""
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def create_check(amount, max_activations, created_by, description=None):
    """Создание нового чека"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    check_code = generate_check_code()
    while True:
        cursor.execute("SELECT check_code FROM checks WHERE check_code = ?", (check_code,))
        if not cursor.fetchone():
            break
        check_code = generate_check_code()

    cursor.execute('''
        INSERT INTO checks (check_code, amount, max_activations, created_by, description)
        VALUES (?, ?, ?, ?, ?)
    ''', (check_code, amount, max_activations, created_by, description))

    conn.commit()
    conn.close()

    return check_code

def activate_check(check_code, user_id):
    """Активация чека пользователем"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    # Проверяем существование чека
    cursor.execute('''
        SELECT amount, max_activations, current_activations, is_active
        FROM checks WHERE check_code = ?
    ''', (check_code,))

    check_data = cursor.fetchone()

    if not check_data:
        conn.close()
        return False, "Чек не найден"

    amount, max_activations, current_activations, is_active = check_data

    if not is_active:
        conn.close()
        return False, "Чек деактивирован"

    if current_activations >= max_activations:
        conn.close()
        return False, "Достигнут лимит активаций"

    # Проверяем, активировал ли уже этот пользователь этот чек
    cursor.execute('''
        SELECT activation_id FROM check_activations
        WHERE check_code = ? AND user_id = ?
    ''', (check_code, user_id))

    if cursor.fetchone():
        conn.close()
        return False, "Вы уже активировали этот чек"

    # Активируем чек
    cursor.execute('''
        UPDATE checks
        SET current_activations = current_activations + 1
        WHERE check_code = ?
    ''', (check_code,))

    # Начисляем звезды пользователю
    cursor.execute("UPDATE users SET stars = stars + ? WHERE user_id = ?", (amount, user_id))

    # Записываем активацию
    cursor.execute('''
        INSERT INTO check_activations (check_code, user_id, amount)
        VALUES (?, ?, ?)
    ''', (check_code, user_id, amount))

    # Записываем транзакцию
    cursor.execute('''
        INSERT INTO transactions (user_id, amount, type, description)
        VALUES (?, ?, ?, ?)
    ''', (user_id, amount, 'check_activation', f'Активация чека {check_code}'))

    conn.commit()
    conn.close()

    return True, f"Чек успешно активирован! Получено {amount} звезд ⭐"

def get_check_info(check_code):
    """Получение информации о чеке"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT c.check_code, c.amount, c.max_activations, c.current_activations,
               c.created_at, c.is_active, c.description,
               u.full_name as creator_name
        FROM checks c
        LEFT JOIN users u ON c.created_by = u.user_id
        WHERE c.check_code = ?
    ''', (check_code,))

    check_data = cursor.fetchone()
    conn.close()

    if not check_data:
        return None

    return {
        'check_code': check_data[0],
        'amount': check_data[1],
        'max_activations': check_data[2],
        'current_activations': check_data[3],
        'created_at': check_data[4],
        'is_active': bool(check_data[5]),
        'description': check_data[6],
        'creator_name': check_data[7]
    }

def get_all_checks(limit=50):
    """Получение всех чеков"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT c.check_code, c.amount, c.max_activations, c.current_activations,
               c.created_at, c.is_active, c.description,
               u.full_name as creator_name
        FROM checks c
        LEFT JOIN users u ON c.created_by = u.user_id
        ORDER BY c.created_at DESC
        LIMIT ?
    ''', (limit,))

    checks = cursor.fetchall()
    conn.close()

    result = []
    for check in checks:
        result.append({
            'check_code': check[0],
            'amount': check[1],
            'max_activations': check[2],
            'current_activations': check[3],
            'created_at': check[4],
            'is_active': bool(check[5]),
            'description': check[6],
            'creator_name': check[7]
        })

    return result

def deactivate_check(check_code):
    """Деактивация чека"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("UPDATE checks SET is_active = 0 WHERE check_code = ?", (check_code,))

    conn.commit()
    conn.close()

    return True

# ========== ОБРАБОТЧИКИ ==========
@bot.callback_query_handler(func=lambda call: call.data == "check_subscription_after")
def check_subscription_after_callback(call):
    """Проверка подписки после нажатия кнопки"""
    user_id = call.from_user.id
    all_subscribed, not_subscribed = check_all_subscriptions(user_id)

    if all_subscribed:
        bot.edit_message_text(
            "✅ <b>Отлично! Вы подписаны на все каналы!</b>\n\n"
            "Теперь вы можете пользоваться ботом.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML'
        )

        # Показываем главное меню
        bot.send_message(
            call.message.chat.id,
            "<blockquote>🎉 <b>Добро пожаловать в бота!</b></blockquote>",
            parse_mode='HTML',
            reply_markup=create_main_menu()
        )
        
        # НОВОЕ: Проверяем и начисляем реферальные бонусы
        check_and_award_referral_bonus(user_id)
    else:
        channels_text = "<blockquote>❌ <b>Вы еще не подписались на все каналы!</b>\n\n"
        channels_text += "Осталось подписаться:\n\n"

        keyboard = types.InlineKeyboardMarkup()

        for channel in not_subscribed:
            channels_text += f"• {channel['channel_name']}\n"
            keyboard.add(
                types.InlineKeyboardButton(
                    f"📺 {channel['channel_name']}",
                    url=f"https://t.me/{channel['channel_username'].replace('@', '')}"
                )
            )

        channels_text += "\n✅ <b>После подписки нажмите кнопку ниже</b></blockquote>"

        keyboard.add(
            types.InlineKeyboardButton("🔄 Проверить подписку", callback_data="check_subscription_after")
        )

        bot.edit_message_text(
            channels_text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML',
            reply_markup=keyboard
        )

def check_and_award_referral_bonus(user_id):
    """Проверяет и начисляет реферальные бонусы после подписки на все каналы"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()
    
    # Получаем информацию о пользователе
    cursor.execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if result and result[0]:  # Если у пользователя есть реферер
        referrer_id = result[0]
        
        # Проверяем, были ли уже начислены бонусы за этого реферала
        cursor.execute('''
            SELECT transaction_id FROM transactions
            WHERE user_id = ? AND type = 'referral_bonus'
            AND description LIKE ?
        ''', (referrer_id, f'%приглашение пользователя {user_id}%'))
        
        existing_bonus = cursor.fetchone()
        
        # Если бонусы еще не начислялись - начисляем
        if not existing_bonus:
            # Начисляем рефереру
            cursor.execute("UPDATE users SET stars = stars + 5 WHERE user_id = ?", (referrer_id,))
            cursor.execute('''
                INSERT INTO transactions (user_id, amount, type, description)
                VALUES (?, ?, ?, ?)
            ''', (referrer_id, 5, 'referral_bonus', f'Бонус за приглашение пользователя {user_id}'))
            
            # Начисляем рефералу приветственный бонус
            cursor.execute("UPDATE users SET stars = stars + 1 WHERE user_id = ?", (user_id,))
            cursor.execute('''
                INSERT INTO transactions (user_id, amount, type, description)
                VALUES (?, ?, ?, ?)
            ''', (user_id, 1, 'welcome_bonus', 'Приветственный бонус за регистрацию по реферальной ссылке'))
            
            conn.commit()
            
            # Отправляем уведомление рефереру
            try:
                cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,))
                user_name = cursor.fetchone()[0] or f"User_{user_id}"
                
                bot.send_message(
                    referrer_id,
                    f'<blockquote>🎉 <b>Поздравляем!</b>\n\n'
                    f'Приглашенный вами пользователь подписался на все каналы!\n'
                    f'👤 <b>Пользователь:</b> {user_name}\n'
                    f'✅ <b>Вам начислено:</b> +5 звезд!\n\n'
                    f'🎯 <b>Продолжайте приглашать друзей!</b></blockquote>',
                    parse_mode='HTML'
                )
            except Exception as e:
                print(f"Не удалось отправить уведомление рефереру: {e}")
    
    conn.close()

# ========== АДМИН ПАНЕЛЬ ==========
def create_admin_keyboard():
    """Клавиатура админ панели"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "📊 Статистика бота",
        "📢 Рассылка всем",
        "📺 Управление каналами",
        "💰 Управление выводами",
        "⭐ Добавить звезды",
        "🎫 Управление чеками",
        "⬅️ Главное меню"
    ]
    keyboard.add(*buttons)
    return keyboard

@bot.message_handler(commands=['admin'])
def admin_command(message):
    """Команда /admin для доступа к админ панели"""
    if message.from_user.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "❌ У вас нет доступа к админ панели")
        return

    admin_text = '''
<blockquote>⚙️ <b>АДМИН ПАНЕЛЬ</b> ⚙️

👑 <b>Добро пожаловать в панель управления!</b>

👇 <b>Выберите раздел:</b></blockquote>
'''

    bot.send_message(
        message.chat.id,
        admin_text,
        parse_mode='HTML',
        reply_markup=create_admin_keyboard()
    )

@bot.message_handler(func=lambda message: message.text == "📊 Статистика бота" and message.from_user.id in ADMIN_IDS)
def bot_stats_command(message):
    """Статистика бота"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE referred_by IS NOT NULL")
        ref_users = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(stars) FROM users")
        total_stars = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM withdrawals WHERE status = 'approved'")
        approved_withdrawals = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(amount) FROM withdrawals WHERE status = 'approved'")
        withdrawn_stars = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM withdrawals WHERE status = 'pending'")
        pending_withdrawals = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(amount) FROM withdrawals WHERE status = 'pending'")
        pending_stars = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM checks")
        total_checks = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM check_activations")
        total_check_activations = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(amount) FROM check_activations")
        total_check_stars = cursor.fetchone()[0] or 0

        stats_text = f'''
<blockquote>📊 <b>СТАТИСТИКА БОТА</b> 📊

👥 <b>Пользователи:</b>
• Всего: <b>{total_users}</b> 👤
• По реф.ссылкам: <b>{ref_users}</b> 🔗

⭐ <b>Звезды:</b>
• Всего звезд: <b>{total_stars} ⭐</b>
• Средний баланс: <b>{round(total_stars/total_users if total_users > 0 else 0, 1)} ⭐</b>

💰 <b>Выводы:</b>
• Одобрено: <b>{approved_withdrawals}</b> на {withdrawn_stars} ⭐
• Ожидает: <b>{pending_withdrawals}</b> на {pending_stars} ⭐

🎫 <b>Чеки:</b>
• Всего чеков: <b>{total_checks}</b>
• Активаций: <b>{total_check_activations}</b>
• Выдано через чеки: <b>{total_check_stars} ⭐</b>

📺 <b>Каналы для подписки:</b>
• Всего каналов: <b>{len(REQUIRED_CHANNELS)}</b></blockquote>
'''

        bot.send_message(message.chat.id, stats_text, parse_mode='HTML')

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
    finally:
        conn.close()

@bot.message_handler(func=lambda message: message.text == "📢 Рассылка всем" and message.from_user.id in ADMIN_IDS)
def mailing_all_command(message):
    """Рассылка всем пользователям"""
    msg = bot.send_message(
        message.chat.id,
        "<blockquote>📢 <b>РАССЫЛКА ВСЕМ ПОЛЬЗОВАТЕЛЯМ</b>\n\n"
        "Отправьте сообщение для рассылки:</blockquote>",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_mailing_all)

def process_mailing_all(message):
    """Обработка рассылки всем"""
    mailing_text = message.text

    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()

    bot.send_message(
        message.chat.id,
        f"⏳ Начинаю рассылку для {len(users)} пользователей...",
        parse_mode='HTML'
    )

    success_count = 0
    fail_count = 0

    for user in users:
        try:
            bot.send_message(user[0], mailing_text, parse_mode='HTML')
            success_count += 1
            time.sleep(0.05)
        except:
            fail_count += 1

    bot.send_message(
        message.chat.id,
        f"<blockquote>✅ <b>Рассылка завершена!</b>\n\n"
        f"📊 <b>Результаты:</b>\n"
        f"• Успешно: {success_count} пользователей\n"
        f"• Не удалось: {fail_count} пользователей\n"
        f"• Всего: {len(users)} пользователей</blockquote>",
        parse_mode='HTML',
        reply_markup=create_admin_keyboard()
    )

@bot.message_handler(func=lambda message: message.text == "📺 Управление каналами" and message.from_user.id in ADMIN_IDS)
def manage_channels_command(message):
    """Управление каналами для подписки"""
    channels_text = '''
<blockquote>📺 <b>УПРАВЛЕНИЕ КАНАЛАМИ</b> 📺

🔗 <b>Обязательные каналы для подписки:</b>
Пользователи должны подписаться на эти каналы для доступа к боту.

➕ <b>Как добавить канал:</b>
Отправьте команду /addchannel

➖ <b>Как удалить канал:</b>
Отправьте команду /removechannel

📋 <b>Список каналов:</b>
Отправьте команду /listchannels

👥 <b>Проверить подписки:</b>
Отправьте команду /checksubs</blockquote>
'''

    bot.send_message(
        message.chat.id,
        channels_text,
        parse_mode='HTML'
    )

@bot.message_handler(commands=['addchannel'])
def add_channel_command(message):
    """Добавление канала"""
    if message.from_user.id not in ADMIN_IDS:
        return

    msg = bot.send_message(
        message.chat.id,
        "<blockquote>➕ <b>ДОБАВЛЕНИЕ КАНАЛА</b>\n\n"
        "Отправьте ссылку на канал в формате:\n"
        "• @username\n"
        "• https://t.me/username\n\n"
        "<i>Бот должен быть администратором в канале!</i></blockquote>",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_add_channel)

def process_add_channel(message):
    """Обработка добавления канала"""
    try:
        channel_link = message.text.strip()

        # Извлекаем username из ссылки
        if 't.me/' in channel_link:
            channel_username = channel_link.split('t.me/')[-1].replace('@', '').split('/')[0]
        elif channel_link.startswith('@'):
            channel_username = channel_link[1:]
        else:
            channel_username = channel_link

        # Проверяем канал
        try:
            chat = bot.get_chat(f"@{channel_username}")
            channel_id = chat.id
            channel_name = chat.title

            # Проверяем права бота в канале
            try:
                bot.get_chat_member(channel_id, bot.get_me().id)
            except:
                bot.send_message(
                    message.chat.id,
                    f"❌ Бот не является администратором в канале {channel_name}\n"
                    f"Добавьте бота как администратора и попробуйте снова."
                )
                return

            # Добавляем канал в список
            global REQUIRED_CHANNELS
            REQUIRED_CHANNELS.append({
                'channel_id': channel_id,
                'channel_username': f"@{channel_username}",
                'channel_name': channel_name
            })

            # Сохраняем в базу данных
            conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    channel_id INTEGER PRIMARY KEY,
                    channel_username TEXT NOT NULL,
                    channel_name TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    added_by INTEGER,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                INSERT OR REPLACE INTO channels (channel_id, channel_username, channel_name, added_by)
                VALUES (?, ?, ?, ?)
            ''', (channel_id, f"@{channel_username}", channel_name, message.from_user.id))

            conn.commit()
            conn.close()

            bot.send_message(
                message.chat.id,
                f"✅ <b>Канал успешно добавлен!</b>\n\n"
                f"📺 <b>Название:</b> {channel_name}\n"
                f"🔗 <b>Ссылка:</b> @{channel_username}\n"
                f"🆔 <b>ID:</b> {channel_id}\n\n"
                f"Теперь пользователи должны подписаться на этот канал.",
                parse_mode='HTML'
            )

        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Не удалось найти канал: {e}")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['listchannels'])
def list_channels_command(message):
    """Список каналов"""
    if message.from_user.id not in ADMIN_IDS:
        return

    if not REQUIRED_CHANNELS:
        channels_text = "<blockquote>📭 <b>Список каналов пуст</b>\n\nДобавьте каналы для обязательной подписки.</blockquote>"
    else:
        channels_text = "<blockquote>📋 <b>СПИСОК КАНАЛОВ</b> 📋\n\n"

        for i, ch in enumerate(REQUIRED_CHANNELS, 1):
            channels_text += f'{i}. <b>{ch["channel_name"]}</b>\n'
            channels_text += f'   🔗 {ch["channel_username"]} | 🆔 {ch["channel_id"]}\n\n'

    channels_text += "</blockquote>"

    bot.send_message(
        message.chat.id,
        channels_text,
        parse_mode='HTML'
    )

@bot.message_handler(commands=['removechannel'])
def remove_channel_command(message):
    """Удаление канала"""
    if message.from_user.id not in ADMIN_IDS:
        return

    if not REQUIRED_CHANNELS:
        bot.send_message(message.chat.id, "❌ Нет каналов для удаления")
        return

    # Показываем список каналов с кнопками
    keyboard = types.InlineKeyboardMarkup()

    for i, ch in enumerate(REQUIRED_CHANNELS):
        keyboard.add(
            types.InlineKeyboardButton(
                f"❌ {ch['channel_name']}",
                callback_data=f"remove_channel_{ch['channel_id']}"
            )
        )

    bot.send_message(
        message.chat.id,
        "<blockquote>➖ <b>УДАЛЕНИЕ КАНАЛА</b>\n\n"
        "Выберите канал для удаления:</blockquote>",
        parse_mode='HTML',
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_channel_'))
def remove_channel_callback(call):
    """Обработка удаления канала"""
    try:
        channel_id = int(call.data.replace('remove_channel_', ''))

        global REQUIRED_CHANNELS
        channel_to_remove = None

        for ch in REQUIRED_CHANNELS:
            if ch['channel_id'] == channel_id:
                channel_to_remove = ch
                break

        if channel_to_remove:
            REQUIRED_CHANNELS = [ch for ch in REQUIRED_CHANNELS if ch['channel_id'] != channel_id]

            # Удаляем из базы данных
            conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
            conn.commit()
            conn.close()

            bot.edit_message_text(
                f"✅ <b>Канал удален!</b>\n\n"
                f"📺 <b>Название:</b> {channel_to_remove['channel_name']}\n"
                f"🔗 <b>Ссылка:</b> {channel_to_remove['channel_username']}",
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML'
            )
        else:
            bot.answer_callback_query(call.id, "Канал не найден")

    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка: {e}")

@bot.message_handler(commands=['checksubs'])
def check_subs_command(message):
    """Проверка подписок пользователя"""
    if message.from_user.id not in ADMIN_IDS:
        return

    msg = bot.send_message(
        message.chat.id,
        "<blockquote>👥 <b>ПРОВЕРКА ПОДПИСОК</b>\n\n"
        "Отправьте ID пользователя для проверки его подписок:</blockquote>",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_check_subs)

def process_check_subs(message):
    """Обработка проверки подписок"""
    try:
        user_id = int(message.text.strip())
        all_subscribed, not_subscribed = check_all_subscriptions(user_id)

        if all_subscribed:
            bot.send_message(
                message.chat.id,
                f"✅ <b>Пользователь {user_id} подписан на все каналы!</b>",
                parse_mode='HTML'
            )
        else:
            channels_text = "\n".join([f"• {ch['channel_name']} ({ch['channel_username']})" for ch in not_subscribed])

            bot.send_message(
                message.chat.id,
                f"❌ <b>Пользователь {user_id} не подписан на каналы:</b>\n\n{channels_text}",
                parse_mode='HTML'
            )

    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный формат ID пользователя")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

@bot.message_handler(func=lambda message: message.text == "⭐ Добавить звезды" and message.from_user.id in ADMIN_IDS)
def add_stars_manual_command(message):
    """Добавление звезд вручную"""
    msg = bot.send_message(
        message.chat.id,
        "<blockquote>➕ <b>ДОБАВЛЕНИЕ ЗВЕЗД</b>\n\n"
        "Введите ID пользователя и количество звезд через пробел:\n\n"
        "<i>Пример: 123456789 100</i></blockquote>",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_add_stars_manual)

def process_add_stars_manual(message):
    """Обработка добавления звезд"""
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.send_message(message.chat.id, "❌ Неверный формат!")
            return

        user_id = int(parts[0])
        amount = int(parts[1])

        if amount <= 0:
            bot.send_message(message.chat.id, "❌ Количество должно быть больше 0!")
            return

        conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
        cursor = conn.cursor()

        # Проверяем существование пользователя
        cursor.execute("SELECT username, full_name, stars FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()

        if not user:
            bot.send_message(message.chat.id, "❌ Пользователь не найден!")
            return

        # Добавляем звезды
        cursor.execute("UPDATE users SET stars = stars + ? WHERE user_id = ?", (amount, user_id))

        # Записываем транзакцию
        cursor.execute('''
            INSERT INTO transactions (user_id, amount, type, description)
            VALUES (?, ?, ?, ?)
        ''', (user_id, amount, 'admin_add', f'Добавлено администратором {message.from_user.id}'))

        conn.commit()

        # Получаем обновленные данные
        cursor.execute("SELECT stars FROM users WHERE user_id = ?", (user_id,))
        new_balance = cursor.fetchone()[0]

        conn.close()

        # Уведомляем пользователя
        try:
            bot.send_message(
                user_id,
                f"<blockquote>🎁 <b>Вам начислен бонус!</b>\n\n"
                f"Администратор добавил вам <b>{amount} звезд ⭐</b>\n"
                f"💰 <b>Новый баланс:</b> {new_balance} ⭐\n\n"
                f"🎯 <b>Теперь вы можете выводить звезды!</b></blockquote>",
                parse_mode='HTML'
            )
        except:
            pass

        bot.send_message(
            message.chat.id,
            f"✅ <b>Звезды успешно добавлены!</b>\n\n"
            f"👤 <b>Пользователь:</b> {user[1]} (@{user[0]})\n"
            f"💰 <b>Добавлено:</b> +{amount} ⭐\n"
            f"💎 <b>Новый баланс:</b> {new_balance} ⭐",
            parse_mode='HTML'
        )

    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный формат данных!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

@bot.message_handler(func=lambda message: message.text == "💰 Управление выводами" and message.from_user.id in ADMIN_IDS)
def manage_withdrawals_command(message):
    """Управление выводами"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT w.*, u.full_name, u.stars as user_balance
        FROM withdrawals w
        LEFT JOIN users u ON w.user_id = u.user_id
        WHERE w.status = 'pending'
        ORDER BY w.created_at DESC
        LIMIT 10
    ''')

    withdrawals = cursor.fetchall()
    conn.close()

    if not withdrawals:
        withdrawals_text = "<blockquote>📭 <b>Нет ожидающих заявок на вывод</b></blockquote>"
        bot.send_message(
            message.chat.id,
            withdrawals_text,
            parse_mode='HTML'
        )
        return

    withdrawals_text = "<blockquote>💰 <b>ОЖИДАЮЩИЕ ЗАЯВКИ НА ВЫВОД</b> 💰\n\n"

    keyboard = types.InlineKeyboardMarkup(row_width=2)

    for w in withdrawals:
        withdrawal_id, user_id, username, amount, status, admin_message, created_at, processed_at, full_name, user_balance = w

        withdrawals_text += f'<b>#{withdrawal_id}</b> - {amount} ⭐\n'
        withdrawals_text += f'👤 {full_name} (ID: {user_id})\n'
        withdrawals_text += f'💰 Баланс: {user_balance} ⭐\n\n'

        keyboard.add(
            types.InlineKeyboardButton(
                f"✅ #{withdrawal_id} - {amount}⭐",
                callback_data=f"admin_approve_{withdrawal_id}"
            ),
            types.InlineKeyboardButton(
                f"❌ #{withdrawal_id}",
                callback_data=f"admin_reject_{withdrawal_id}"
            )
        )

    withdrawals_text += "</blockquote>"

    bot.send_message(
        message.chat.id,
        withdrawals_text,
        parse_mode='HTML',
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_approve_'))
def admin_approve_callback(call):
    """Одобрение заявки админом - ФИКСИРОВАННАЯ ВЕРСИЯ"""
    try:
        withdrawal_id = int(call.data.replace('admin_approve_', ''))

        # Удаляем сообщение с кнопками
        bot.delete_message(call.message.chat.id, call.message.message_id)

        msg = bot.send_message(
            call.message.chat.id,
            f"<blockquote>💬 <b>ОДОБРЕНИЕ ЗАЯВКИ #{withdrawal_id}</b>\n\n"
            "Введите сообщение для пользователя (или 'нет' если не нужно):</blockquote>",
            parse_mode='HTML'
        )

        bot.register_next_step_handler(msg, process_approve_withdrawal, withdrawal_id)

    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка: {e}")

def process_approve_withdrawal(message, withdrawal_id):
    """Обработка одобрения заявки"""
    admin_message = message.text if message.text.lower() != 'нет' else None

    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT user_id, amount, username, created_at FROM withdrawals WHERE withdrawal_id = ?", (withdrawal_id,))
        withdrawal = cursor.fetchone()

        if withdrawal:
            user_id, amount, username, created_at = withdrawal

            cursor.execute('''
                UPDATE withdrawals
                SET status = 'approved', admin_message = ?, processed_at = CURRENT_TIMESTAMP
                WHERE withdrawal_id = ?
            ''', (admin_message, withdrawal_id))

            try:
                bot.send_message(
                    user_id,
                    f"<blockquote>✅ <b>Ваша заявка на вывод одобрена!</b>\n\n"
                    f"💰 <b>Сумма:</b> {amount} ⭐\n"
                    f"🆔 <b>Номер заявки:</b> #{withdrawal_id}\n"
                    f"📅 <b>Дата обработки:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"{'💬 <b>Сообщение от администратора:</b> ' + admin_message if admin_message else ''}</blockquote>",
                    parse_mode='HTML'
                )
            except:
                pass

            conn.commit()

            # Обновляем сообщение в канале
            if withdrawal_id in withdrawal_messages:
                channel_data = {
                    'withdrawal_id': withdrawal_id,
                    'user_id': user_id,
                    'username': username,
                    'amount': amount,
                    'created_at': created_at[:19] if created_at else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                withdrawal_channel.update_withdrawal_status(
                    withdrawal_messages[withdrawal_id],
                    channel_data,
                    'approved',
                    admin_message
                )

            bot.send_message(
                message.chat.id,
                f"✅ <b>Заявка #{withdrawal_id} одобрена!</b>",
                parse_mode='HTML',
                reply_markup=create_admin_keyboard()
            )
        else:
            bot.send_message(message.chat.id, "❌ Заявка не найдена!")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
    finally:
        conn.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_reject_'))
def admin_reject_callback(call):
    """Отклонение заявки админом - ФИКСИРОВАННАЯ ВЕРСИЯ"""
    try:
        withdrawal_id = int(call.data.replace('admin_reject_', ''))

        # Удаляем сообщение с кнопками
        bot.delete_message(call.message.chat.id, call.message.message_id)

        msg = bot.send_message(
            call.message.chat.id,
            f"<blockquote>💬 <b>ОТКЛОНЕНИЕ ЗАЯВКИ #{withdrawal_id}</b>\n\n"
            "Введите причину отклонения:</blockquote>",
            parse_mode='HTML'
        )

        bot.register_next_step_handler(msg, process_reject_withdrawal, withdrawal_id)

    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка: {e}")

def process_reject_withdrawal(message, withdrawal_id):
    """Обработка отклонения заявки"""
    reject_reason = message.text

    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT user_id, amount, username, created_at FROM withdrawals WHERE withdrawal_id = ?", (withdrawal_id,))
        withdrawal = cursor.fetchone()

        if withdrawal:
            user_id, amount, username, created_at = withdrawal

            cursor.execute('''
                UPDATE withdrawals
                SET status = 'rejected', admin_message = ?, processed_at = CURRENT_TIMESTAMP
                WHERE withdrawal_id = ?
            ''', (reject_reason, withdrawal_id))

            cursor.execute("UPDATE users SET stars = stars + ? WHERE user_id = ?", (amount, user_id))

            cursor.execute('''
                INSERT INTO transactions (user_id, amount, type, description)
                VALUES (?, ?, ?, ?)
            ''', (user_id, amount, 'withdrawal_refund', f'Возврат из-за отклонения заявки #{withdrawal_id}'))

            try:
                bot.send_message(
                    user_id,
                    f"<blockquote>❌ <b>Ваша заявка на вывод отклонена</b>\n\n"
                    f"💰 <b>Сумма:</b> {amount} ⭐\n"
                    f"🆔 <b>Номер заявки:</b> #{withdrawal_id}\n"
                    f"📅 <b>Дата обработки:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"💎 <b>Звезды возвращены на баланс</b>\n\n"
                    f"💬 <b>Причина:</b> {reject_reason}</blockquote>",
                    parse_mode='HTML'
                )
            except:
                pass

            conn.commit()

            # Обновляем сообщение в канале
            if withdrawal_id in withdrawal_messages:
                channel_data = {
                    'withdrawal_id': withdrawal_id,
                    'user_id': user_id,
                    'username': username,
                    'amount': amount,
                    'created_at': created_at[:19] if created_at else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                withdrawal_channel.update_withdrawal_status(
                    withdrawal_messages[withdrawal_id],
                    channel_data,
                    'rejected',
                    reject_reason
                )

            bot.send_message(
                message.chat.id,
                f"❌ <b>Заявка #{withdrawal_id} отклонена!</b>",
                parse_mode='HTML',
                reply_markup=create_admin_keyboard()
            )
        else:
            bot.send_message(message.chat.id, "❌ Заявка не найден!")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
    finally:
        conn.close()

# Добавьте обработчики для кнопок из канала
@bot.callback_query_handler(func=lambda call: call.data.startswith('channel_approve_'))
def channel_approve_callback(call):
    """Одобрение заявки из канала"""
    try:
        withdrawal_id = int(call.data.replace('channel_approve_', ''))

        # Проверяем, является ли пользователь админом
        if call.from_user.id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "❌ У вас нет прав для одобрения заявок")
            return

        # Удаляем клавиатуру из сообщения
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )

        bot.answer_callback_query(call.id, "✅ Заявка будет одобрена через админ-панель")

        # Перенаправляем в админ-панель для завершения
        bot.send_message(
            call.from_user.id,
            f"<blockquote>🎯 <b>Одобрение заявки #{withdrawal_id}</b>\n\n"
            "Перейдите в админ-панель для завершения обработки.</blockquote>",
            parse_mode='HTML'
        )

    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('channel_reject_'))
def channel_reject_callback(call):
    """Отклонение заявки из канала"""
    try:
        withdrawal_id = int(call.data.replace('channel_reject_', ''))

        # Проверяем, является ли пользователь админом
        if call.from_user.id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "❌ У вас нет прав для отклонения заявок")
            return

        # Удаляем клавиатуру из сообщения
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )

        bot.answer_callback_query(call.id, "❌ Заявка будет отклонена через админ-панель")

        # Перенаправляем в админ-панель для завершения
        bot.send_message(
            call.from_user.id,
            f"<blockquote>🎯 <b>Отклонение заявки #{withdrawal_id}</b>\n\n"
            "Перейдите в админ-панель для завершения обработки.</blockquote>",
            parse_mode='HTML'
        )

    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка: {e}")

@bot.message_handler(func=lambda message: message.text == "🎫 Управление чеками" and message.from_user.id in ADMIN_IDS)
def manage_checks_command(message):
    """Управление чеками"""
    checks_text = '''
<blockquote>🎫 <b>УПРАВЛЕНИЕ ЧЕКАМИ</b> 🎫

🔗 <b>Что такое чеки?</b>
Чеки - это промо-коды, которые можно активировать для получения звезд.

👇 <b>Доступные действия:</b>
• /createcheck - Создать новый чек
• /listchecks - Список всех чеков
• /checkinfo [код] - Информация о чеке
• /deactivatecheck [код] - Деактивировать чек
• /checkstats - Статистика по чекам</blockquote>
'''

    bot.send_message(
        message.chat.id,
        checks_text,
        parse_mode='HTML'
    )

# Команда для создания чека
@bot.message_handler(commands=['createcheck'])
def create_check_command(message):
    """Создание чека"""
    if message.from_user.id not in ADMIN_IDS:
        return

    msg = bot.send_message(
        message.chat.id,
        "<blockquote>🎫 <b>СОЗДАНИЕ ЧЕКА</b>\n\n"
        "Введите данные в формате:\n"
        "<code>сумма_звезд количество_активаций описание(опционально)</code>\n\n"
        "<b>Примеры:</b>\n"
        "<code>100 10 Приветственный бонус</code>\n"
        "<code>50 5</code>\n"
        "<code>500 1 Специальный приз</code></blockquote>",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_create_check)

def process_create_check(message):
    """Обработка создания чека"""
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.send_message(message.chat.id, "❌ Неверный формат!")
            return

        amount = int(parts[0])
        max_activations = int(parts[1])
        description = ' '.join(parts[2:]) if len(parts) > 2 else None

        if amount <= 0 or max_activations <= 0:
            bot.send_message(message.chat.id, "❌ Сумма и количество активаций должны быть больше 0!")
            return

        # Создаем чек
        check_code = create_check(amount, max_activations, message.from_user.id, description)

        # Формируем ссылку для активации
        try:
            bot_username = bot.get_me().username
            activation_link = f"https://t.me/{bot_username}?start=check_{check_code}"
        except:
            activation_link = f"https://t.me/ваш_бот?start=check_{check_code}"

        response_text = f'''
<blockquote>✅ <b>Чек успешно создан!</b> 🎫

📋 <b>Информация о чеке:</b>
• Код: <code>{check_code}</code>
• Сумма: <b>{amount} ⭐</b>
• Активаций: <b>{max_activations}</b>
• Описание: <b>{description or 'Не указано'}</b>

🔗 <b>Ссылка для активации:</b>
<code>{activation_link}</code>

📝 <b>Команда для активации:</b>
<code>/activate {check_code}</code>

💡 <b>Как активировать:</b>
1. Отправьте пользователю ссылку
2. Или попросите ввести команду /activate {check_code}
3. После активации пользователь получит {amount} звезд</blockquote>
'''

        bot.send_message(
            message.chat.id,
            response_text,
            parse_mode='HTML'
        )

    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный формат чисел!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

# Команда для списка чеков
@bot.message_handler(commands=['listchecks'])
def list_checks_command(message):
    """Список всех чеков"""
    if message.from_user.id not in ADMIN_IDS:
        return

    checks = get_all_checks(20)

    if not checks:
        checks_text = "<blockquote>📭 <b>Список чеков пуст</b>\n\nСоздайте первый чек командой /createcheck</blockquote>"
    else:
        checks_text = "<blockquote>📋 <b>СПИСОК ЧЕКОВ</b> 📋\n\n"

        for check in checks:
            status = "✅ Активен" if check['is_active'] else "❌ Деактивирован"
            checks_text += f"🎫 <b>{check['check_code']}</b>\n"
            checks_text += f"   💰 {check['amount']} ⭐ | 👥 {check['current_activations']}/{check['max_activations']}\n"
            checks_text += f"   📅 {check['created_at'][:10]} | {status}\n"
            if check['description']:
                checks_text += f"   📝 {check['description']}\n"
            checks_text += "\n"

    checks_text += "</blockquote>"

    bot.send_message(
        message.chat.id,
        checks_text,
        parse_mode='HTML'
    )

# Команда для информации о чеке
@bot.message_handler(commands=['checkinfo'])
def check_info_command(message):
    """Информация о чеке"""
    if message.from_user.id not in ADMIN_IDS:
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "❌ Укажите код чека: /checkinfo КОД")
        return

    check_code = parts[1].upper()
    check_info = get_check_info(check_code)

    if not check_info:
        bot.send_message(message.chat.id, f"❌ Чек с кодом {check_code} не найден")
        return

    status = "✅ Активен" if check_info['is_active'] else "❌ Деактивирован"

    check_text = f'''
<blockquote>🎫 <b>ИНФОРМАЦИЯ О ЧЕКЕ</b> 🎫

📋 <b>Основная информация:</b>
• Код: <code>{check_info['check_code']}</code>
• Сумма: <b>{check_info['amount']} ⭐</b>
• Активаций: <b>{check_info['current_activations']}/{check_info['max_activations']}</b>
• Статус: <b>{status}</b>
• Создал: <b>{check_info['creator_name'] or 'Неизвестно'}</b>
• Дата создания: <b>{check_info['created_at']}</b>
• Описание: <b>{check_info['description'] or 'Не указано'}</b>

🔗 <b>Ссылка для активации:</b>
'''
    try:
        bot_username = bot.get_me().username
        activation_link = f"https://t.me/{bot_username}?start=check_{check_code}"
        check_text += f"<code>{activation_link}</code>\n\n"
    except:
        check_text += f"<code>https://t.me/ваш_бот?start=check_{check_code}</code>\n\n"

    check_text += '''📝 <b>Команда для активации:</b>
<code>/activate ''' + check_code + '''</code></blockquote>'''

    bot.send_message(
        message.chat.id,
        check_text,
        parse_mode='HTML'
    )

# Команда для деактивации чека
@bot.message_handler(commands=['deactivatecheck'])
def deactivate_check_command(message):
    """Деактивация чека"""
    if message.from_user.id not in ADMIN_IDS:
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "❌ Укажите код чека: /deactivatecheck КОД")
        return

    check_code = parts[1].upper()

    # Проверяем существование чека
    check_info = get_check_info(check_code)
    if not check_info:
        bot.send_message(message.chat.id, f"❌ Чек с кодом {check_code} не найден")
        return

    if not check_info['is_active']:
        bot.send_message(message.chat.id, f"❌ Чек {check_code} уже деактивирован")
        return

    # Деактивируем чек
    deactivate_check(check_code)

    bot.send_message(
        message.chat.id,
        f"✅ <b>Чек {check_code} успешно деактивирован!</b>\n\n"
        f"Теперь его нельзя активировать.",
        parse_mode='HTML'
    )

# Команда для статистики чеков
@bot.message_handler(commands=['checkstats'])
def check_stats_command(message):
    """Статистика по чекам"""
    if message.from_user.id not in ADMIN_IDS:
        return

    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM checks")
    total_checks = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM checks WHERE is_active = 1")
    active_checks = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(amount * max_activations) FROM checks")
    total_potential = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(amount * current_activations) FROM checks")
    total_distributed = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM check_activations")
    total_activations = cursor.fetchone()[0]

    conn.close()

    stats_text = f'''
<blockquote>📊 <b>СТАТИСТИКА ПО ЧЕКАМ</b> 📊

🎫 <b>Общая статистика:</b>
• Всего чеков: <b>{total_checks}</b>
• Активных чеков: <b>{active_checks}</b>
• Всего активаций: <b>{total_activations}</b>

💰 <b>Распределение звезд:</b>
• Потенциально к выдаче: <b>{total_potential} ⭐</b>
• Уже выдано: <b>{total_distributed} ⭐</b>
• Осталось выдать: <b>{total_potential - total_distributed} ⭐</b>

📈 <b>Эффективность:</b>
• Процент активаций: <b>{round((total_distributed / total_potential * 100) if total_potential > 0 else 0, 1)}%</b>
• Средний чек: <b>{round(total_distributed / total_activations if total_activations > 0 else 0, 1)} ⭐</b></blockquote>
'''

    bot.send_message(
        message.chat.id,
        stats_text,
        parse_mode='HTML'
    )

@bot.message_handler(func=lambda message: message.text == "⬅️ Главное меню" and message.from_user.id in ADMIN_IDS)
def admin_back_to_main_menu(message):
    """Возврат в главное меню из админ панели"""
    bot.send_message(
        message.chat.id,
        "<blockquote>🏠 <b>Главное меню</b></blockquote>",
        parse_mode='HTML',
        reply_markup=create_main_menu()
    )

# ========== ФУНКЦИИ ОСНОВНОГО БОТА ==========
def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            referred_by INTEGER DEFAULT NULL,
            stars INTEGER DEFAULT 0,
            registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (referred_by) REFERENCES users(user_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            type TEXT,
            description TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawals (
            withdrawal_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            amount INTEGER,
            status TEXT DEFAULT 'pending',
            admin_message TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP DEFAULT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            channel_id INTEGER PRIMARY KEY,
            channel_username TEXT NOT NULL,
            channel_name TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            added_by INTEGER,
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()

def load_channels_from_db():
    """Загрузка каналов из базы данных при запуске"""
    global REQUIRED_CHANNELS

    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("SELECT channel_id, channel_username, channel_name FROM channels WHERE is_active = 1")
    channels = cursor.fetchall()

    REQUIRED_CHANNELS = [
        {'channel_id': ch[0], 'channel_username': ch[1], 'channel_name': ch[2]}
        for ch in channels
    ]

    conn.close()
    print(f"📺 Загружено {len(REQUIRED_CHANNELS)} каналов для подписки")

def register_user(user_id, username, full_name, referrer_id=None):
    """Регистрация пользователя с проверкой дублирования реферальных начислений"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()

    if not user:
        cursor.execute('''
            INSERT INTO users (user_id, username, full_name, referred_by, stars)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, full_name, referrer_id, 0))  # Изначально 0 звезд, бонусы будут позже
        conn.commit()

        # НЕ начисляем бонусы сразу при регистрации
        cursor.execute('''
            INSERT INTO transactions (user_id, amount, type, description)
            VALUES (?, ?, ?, ?)
        ''', (user_id, 0, 'registration', 'Регистрация в боте'))

        conn.commit()
        
        # Если есть реферер - просто сохраняем его ID, но НЕ начисляем бонусы
        if referrer_id:
            # Отправляем уведомление рефереру, что пользователь зарегистрировался
            try:
                bot.send_message(
                    referrer_id,
                    f'<blockquote>🎉 <b>Новый реферал зарегистрировался!</b>\n\n'
                    f'👤 <b>Пользователь:</b> {full_name}\n\n'
                    f'📢 <b>Бонусы будут начислены после того, как пользователь подпишется на все обязательные каналы.</b></blockquote>',
                    parse_mode='HTML'
                )
            except Exception as e:
                print(f"Не удалось отправить уведомление рефереру: {e}")

    # ФИКС: Проверяем, был ли пользователь уже зарегистрирован с другим реферером
    else:
        # Если пользователь уже существует, но у него нет реферера, а сейчас есть
        if referrer_id and not user[3]:  # user[3] - referred_by
            cursor.execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,))
            current_referrer = cursor.fetchone()[0]

            if not current_referrer:
                # Обновляем реферера
                cursor.execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer_id, user_id))
                conn.commit()

                # Отправляем уведомление рефереру
                try:
                    bot.send_message(
                        referrer_id,
                        f'<blockquote>🎉 <b>Новый реферал зарегистрировался!</b>\n\n'
                        f'👤 <b>Пользователь:</b> {full_name}\n\n'
                        f'📢 <b>Бонусы будут начислены после того, как пользователь подпишется на все обязательные каналы.</b></blockquote>',
                        parse_mode='HTML'
                    )
                except Exception as e:
                    print(f"Не удалось отправить уведомление рефереру: {e}")

    conn.close()

def get_user_info(user_id):
    """Получение информации о пользователе"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT u.user_id, u.username, u.full_name, u.referred_by, u.stars,
               u.registration_date, COUNT(r.user_id) as referrals_count
        FROM users u
        LEFT JOIN users r ON u.user_id = r.referred_by
        WHERE u.user_id = ?
        GROUP BY u.user_id, u.username, u.full_name, u.referred_by, u.stars, u.registration_date
    ''', (user_id,))

    user = cursor.fetchone()
    conn.close()

    if user:
        reg_date = user[5]
        if reg_date:
            if isinstance(reg_date, str):
                reg_date_str = reg_date[:10] if len(reg_date) >= 10 else reg_date
            else:
                reg_date_str = str(reg_date)[:10]
        else:
            reg_date_str = "Неизвестно"

        return {
            'user_id': user[0],
            'username': user[1],
            'full_name': user[2],
            'referred_by': user[3],
            'stars': user[4],
            'registration_date': reg_date_str,
            'referrals_count': user[6] if user[6] else 0
        }
    return None

def create_withdrawal(user_id, username, amount):
    """Создание заявки на вывод"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("SELECT stars FROM users WHERE user_id = ?", (user_id,))
    user_stars = cursor.fetchone()

    if not user_stars or user_stars[0] < amount:
        conn.close()
        return False, "Недостаточно звезд на балансе"

    if amount < 50:
        conn.close()
        return False, "Минимальная сумма вывода: 50⭐"

    # Вставляем заявку на вывод
    cursor.execute('''
        INSERT INTO withdrawals (user_id, username, amount, status)
        VALUES (?, ?, ?, 'pending')
    ''', (user_id, username, amount))

    withdrawal_id = cursor.lastrowid  # Получаем ID созданной заявки

    cursor.execute("UPDATE users SET stars = stars - ? WHERE user_id = ?", (amount, user_id))

    cursor.execute('''
        INSERT INTO transactions (user_id, amount, type, description)
        VALUES (?, ?, ?, ?)
    ''', (user_id, -amount, 'withdrawal', f'Заявка на вывод {amount} звезд'))

    conn.commit()

    # Получаем время создания
    cursor.execute("SELECT created_at FROM withdrawals WHERE withdrawal_id = ?", (withdrawal_id,))
    created_at = cursor.fetchone()[0]

    conn.close()

    # Отправляем уведомление в канал
    withdrawal_data = {
        'withdrawal_id': withdrawal_id,
        'user_id': user_id,
        'username': username,
        'amount': amount,
        'created_at': created_at[:19] if created_at else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    # Отправляем уведомление в канал
    message_id = withdrawal_channel.send_withdrawal_notification(withdrawal_data)

    # Сохраняем ID сообщения
    if message_id:
        withdrawal_messages[withdrawal_id] = message_id

    return True, "Заявка на вывод успешно создана"

def get_user_withdrawals(user_id, limit=10):
    """Получение истории выводов пользователя"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT withdrawal_id, amount, status, created_at, processed_at, admin_message
        FROM withdrawals
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    ''', (user_id, limit))

    withdrawals = cursor.fetchall()
    conn.close()

    result = []
    for w in withdrawals:
        result.append({
            'id': w[0],
            'amount': w[1],
            'status': w[2],
            'created_at': w[3],
            'processed_at': w[4],
            'admin_message': w[5]
        })

    return result

def generate_referral_link(user_id):
    """Генерация реферальной ссылки"""
    try:
        bot_username = bot.get_me().username
        return f"https://t.me/{bot_username}?start=ref_{user_id}"
    except:
        return f"https://t.me/ваш_бот?start=ref_{user_id}"

def get_top_referrers(limit=10):
    """Получение топ пользователей"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT u.user_id, u.username, u.full_name, u.stars, COUNT(r.user_id) as referrals_count
        FROM users u
        LEFT JOIN users r ON u.user_id = r.referred_by
        GROUP BY u.user_id, u.username, u.full_name, u.stars
        ORDER BY u.stars DESC
        LIMIT ?
    ''', (limit,))

    top_users = cursor.fetchall()
    conn.close()

    return top_users

def get_transactions(user_id, limit=10):
    """Получение истории транзакций"""
    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT amount, type, description, timestamp
        FROM transactions
        WHERE user_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
    ''', (user_id, limit))

    transactions = cursor.fetchall()
    conn.close()

    return transactions

def create_main_menu():
    """Главное меню - УПРОЩЕННАЯ ВЕРСИЯ"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "⭐ Мой профиль",
        "🔗 Пригласить друзей",
        "💰 Вывод звезд",
        "📊 Моя статистика",
        "🏆 Топ рефереров",
        "🎫 Активировать чек",
        "📋 Мои заявки"
        # Убрана кнопка "⬅️ Назад"
    ]
    keyboard.add(*buttons)
    return keyboard

def create_referral_keyboard(user_id):
    """Упрощенная клавиатура для реферальной ссылки - ТОЛЬКО КНОПКА ПОДЕЛИТЬСЯ"""
    keyboard = types.InlineKeyboardMarkup(row_width=1)

    referral_link = generate_referral_link(user_id)
    share_text = "Привет! Присоединяйся к крутому боту с реферальной системой! За каждого друга дают 5 звезд! 👇"

    import urllib.parse
    encoded_text = urllib.parse.quote(share_text)

    keyboard.add(
        types.InlineKeyboardButton(
            "📱 Поделиться ссылкой",
            url=f"https://t.me/share/url?url={referral_link}&text={encoded_text}"
        )
    )

    return keyboard

def create_withdrawal_keyboard():
    """Клавиатура для вывода средств - ИНЛАЙН КНОПКИ"""
    keyboard = types.InlineKeyboardMarkup(row_width=2)

    keyboard.add(
        types.InlineKeyboardButton("50⭐", callback_data="withdraw_50"),
        types.InlineKeyboardButton("100⭐", callback_data="withdraw_100"),
        types.InlineKeyboardButton("200⭐", callback_data="withdraw_200"),
        types.InlineKeyboardButton("500⭐", callback_data="withdraw_500"),
        types.InlineKeyboardButton("1000⭐", callback_data="withdraw_1000"),
        types.InlineKeyboardButton("Другая сумма", callback_data="withdraw_custom")
    )

    return keyboard

@bot.callback_query_handler(func=lambda call: call.data.startswith('withdraw_'))
def handle_withdrawal_callback(call):
    """Обработчик инлайн-кнопок вывода"""
    user_id = call.from_user.id
    user_info = get_user_info(user_id)

    if not user_info:
        bot.answer_callback_query(call.id, "❌ Ошибка: пользователь не найден")
        return

    action = call.data

    if action == "withdraw_custom":
        msg = bot.send_message(
            call.message.chat.id,
            "<blockquote>💎 <b>Введите сумму для вывода</b>\n\n"
            "Минимальная сумма: 50 звезд\n"
            "Введите число кратное 10:</blockquote>",
            parse_mode='HTML'
        )
        bot.register_next_step_handler(msg, process_custom_withdrawal)
        bot.answer_callback_query(call.id)
        return

    # Извлекаем сумму из callback_data
    if action.startswith("withdraw_"):
        try:
            amount_str = action.replace("withdraw_", "")
            if amount_str.isdigit():
                amount = int(amount_str)
            else:
                bot.answer_callback_query(call.id, "❌ Неверная сумма")
                return
        except:
            bot.answer_callback_query(call.id, "❌ Неверная сумма")
            return

    # Проверяем баланс
    if user_info['stars'] < amount:
        bot.answer_callback_query(
            call.id,
            f"❌ Недостаточно звезд! У вас {user_info['stars']}⭐",
            show_alert=True
        )
        return

    if amount < 50:
        bot.answer_callback_query(
            call.id,
            "❌ Минимальная сумма вывода 50 ⭐",
            show_alert=True
        )
        return

    # Запрашиваем username для вывода
    user_data = {'amount': amount, 'user_id': user_id}

    msg = bot.send_message(
        call.message.chat.id,
        f"<blockquote>📝 <b>Подтверждение вывода</b>\n\n"
        f"Сумма вывода: <b>{amount} ⭐</b>\n"
        f"Ваш баланс: <b>{user_info['stars']} ⭐</b>\n"
        f"Баланс после вывода: <b>{user_info['stars'] - amount} ⭐</b>\n\n"
        f"✍️ <b>Введите ваш @username для связи:</b></blockquote>",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_withdrawal_username, user_data)
    bot.answer_callback_query(call.id)

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name or f"User_{user_id}"

    # Проверяем, активируется ли чек
    if len(message.text.split()) > 1:
        start_param = message.text.split()[1]

        # Если это активация чека
        if start_param.startswith('check_'):
            check_code = start_param.replace('check_', '')

            # Сначала регистрируем пользователя
            register_user(user_id, username, full_name, None)
            
            # Проверяем подписку на каналы (для активации чека)
            if REQUIRED_CHANNELS:
                is_subscribed, subscription_data = check_subscription_required(user_id)
                if not is_subscribed:
                    channels_text, keyboard = subscription_data
                    bot.send_message(
                        message.chat.id,
                        channels_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                    return
                else:
                    # Если подписан - начисляем бонусы
                    check_and_award_referral_bonus(user_id)

            # Активируем чек
            success, result_message = activate_check(check_code, user_id)

            if success:
                user_info = get_user_info(user_id)
                if user_info:
                    bot.send_message(
                        message.chat.id,
                        f"<blockquote>✅ <b>Чек активирован успешно!</b> 🎉\n\n"
                        f"💰 <b>Получено:</b> {result_message.split('! Получено ')[1]}\n"
                        f"⭐ <b>Ваш баланс:</b> {user_info['stars']} звезд\n\n"
                        f"🎯 <b>Теперь вы можете выводить звезды!</b></blockquote>",
                        parse_mode='HTML'
                    )
                else:
                    bot.send_message(
                        message.chat.id,
                        f"<blockquote>✅ {result_message}</blockquote>",
                        parse_mode='HTML'
                    )
            else:
                bot.send_message(
                    message.chat.id,
                    f"<blockquote>❌ <b>Не удалось активировать чек:</b>\n\n{result_message}</blockquote>",
                    parse_mode='HTML'
                )

            # Показываем главное меню
            bot.send_message(
                message.chat.id,
                "<blockquote>🏠 <b>Главное меню</b></blockquote>",
                parse_mode='HTML',
                reply_markup=create_main_menu()
            )
            return

        # Обработка реферальной ссылки (старая логика)
        elif start_param.startswith('ref_'):
            referrer_id = None
            try:
                referrer_id = int(start_param.split('_')[1])
                if referrer_id == user_id:
                    referrer_id = None
                else:
                    conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
                    cursor = conn.cursor()
                    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (referrer_id,))
                    referrer_exists = cursor.fetchone()
                    conn.close()

                    if not referrer_exists:
                        referrer_id = None
            except ValueError:
                referrer_id = None

            register_user(user_id, username, full_name, referrer_id)
            
            # После регистрации проверяем подписку на каналы
            if REQUIRED_CHANNELS:
                is_subscribed, subscription_data = check_subscription_required(user_id)
                if not is_subscribed:
                    channels_text, keyboard = subscription_data
                    bot.send_message(
                        message.chat.id,
                        channels_text,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                    return
                else:
                    # Если уже подписан - начисляем бонусы
                    check_and_award_referral_bonus(user_id)
                    
                    # Показываем приветствие
                    welcome_text = f'''
<blockquote>✨ <b>Добро пожаловать, {full_name}!</b> ✨

🎯 <b>Добро пожаловать в нашего бота с реферальной системой!</b>

✅ <b>Вы уже подписаны на все каналы!</b>

👇 <b>Используйте кнопки ниже для навигации:</b></blockquote>
'''
                    
                    bot.send_message(
                        message.chat.id,
                        welcome_text,
                        parse_mode='HTML',
                        reply_markup=create_main_menu()
                    )
                    return

        else:
            # Просто регистрируем пользователя
            register_user(user_id, username, full_name, None)
    else:
        # Просто регистрируем пользователя
        register_user(user_id, username, full_name, None)

    # ПРОВЕРКА ПОДПИСКИ НА КАНАЛЫ ДЛЯ ВСЕХ НОВЫХ ПОЛЬЗОВАТЕЛЕЙ
    if REQUIRED_CHANNELS:
        is_subscribed, subscription_data = check_subscription_required(user_id)

        if not is_subscribed:
            channels_text, keyboard = subscription_data
            bot.send_message(
                message.chat.id,
                channels_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            return
        else:
            # Если пользователь подписан на все каналы - проверяем и начисляем реферальные бонусы
            check_and_award_referral_bonus(user_id)

    welcome_text = f'''
<blockquote>✨ <b>Добро пожаловать, {full_name}!</b> ✨

🎯 <b>Добро пожаловать в нашего бота с реферальной системой!</b>

🌟 <b>Как работает система:</b>
1️⃣ Приглашайте друзей по своей реферальной ссылке
2️⃣ За каждого приглашенного друга получайте <b>+5 звезд</b> (только после подписки реферала на все каналы)
3️⃣ Ваш друг тоже получает <b>+1 звезду</b> за регистрацию
4️⃣ Выводите звезды от <b>50</b> и более!
5️⃣ Активируйте чеки для получения бонусных звезд!

👇 <b>Используйте кнопки ниже для навигации:</b></blockquote>
'''

    bot.send_message(
        message.chat.id,
        welcome_text,
        parse_mode='HTML',
        reply_markup=create_main_menu()
    )

@bot.message_handler(func=lambda message: message.text == "⭐ Мой профиль")
def profile_command(message):
    # Проверяем подписку на каналы
    if REQUIRED_CHANNELS:
        is_subscribed, subscription_data = check_subscription_required(message.from_user.id)
        if not is_subscribed:
            channels_text, keyboard = subscription_data
            bot.send_message(
                message.chat.id,
                channels_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            return

    user_info = get_user_info(message.from_user.id)

    if user_info:
        referral_link = generate_referral_link(message.from_user.id)
        username_display = f"@{user_info['username']}" if user_info['username'] else "не указан"

        profile_text = f'''
<blockquote>👤 <b>Ваш профиль</b> 👤

📛 <b>Имя:</b> {user_info['full_name']}
📱 <b>Username:</b> {username_display}
🆔 <b>ID:</b> {user_info['user_id']}

⭐ <b>Баланс звезд:</b> <b>{user_info['stars']} ⭐</b>
👥 <b>Приглашено друзей:</b> {user_info['referrals_count']}
💰 <b>Заработано с рефералов:</b> {user_info['referrals_count'] * 5} ⭐
📅 <b>Дата регистрации:</b> {user_info['registration_date']}

🔗 <b>Ваша реферальная ссылка:</b>
<code>{referral_link}</code>

💸 <b>Доступно для вывода:</b> {user_info['stars']} ⭐
💰 <b>Минимальный вывод:</b> 50 ⭐

🎯 <b>Делитесь ссылкой и зарабатывайте звезды!</b></blockquote>
'''

        bot.send_message(
            message.chat.id,
            profile_text,
            parse_mode='HTML',
            reply_markup=create_referral_keyboard(message.from_user.id)
        )

@bot.message_handler(func=lambda message: message.text == "🔗 Пригласить друзей")
def invite_command(message):
    # Проверяем подписку на каналы
    if REQUIRED_CHANNELS:
        is_subscribed, subscription_data = check_subscription_required(message.from_user.id)
        if not is_subscribed:
            channels_text, keyboard = subscription_data
            bot.send_message(
                message.chat.id,
                channels_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            return

    user_info = get_user_info(message.from_user.id)

    if user_info:
        referral_link = generate_referral_link(message.from_user.id)

        referrals_count = user_info['referrals_count']
        if referrals_count % 5 == 0:
            next_reward = 5
        else:
            next_reward = 5 - (referrals_count % 5)

        invite_text = f'''
<blockquote>🎁 <b>Пригласите друга и получите 5 звезд!</b> 🎁

🔗 <b>Ваша уникальная реферальная ссылка:</b>
<code>{referral_link}</code>

📊 <b>Статистика приглашений:</b>
✅ <b>Приглашено:</b> {referrals_count} друзей
⭐ <b>Заработано звезд:</b> {referrals_count * 5} ⭐
🎯 <b>До следующей награды:</b> {next_reward} друзей

💰 <b>Заработано на вывод:</b> {user_info['stars']} ⭐
💸 <b>Минимальный вывод:</b> 50 ⭐

💬 <b>Сообщение для друга:</b>
"Привет! Перейди по этой ссылке и нажми START - получишь бонусную звезду, а я заработаю 5 звезд! {referral_link}"</blockquote>
'''

        bot.send_message(
            message.chat.id,
            invite_text,
            parse_mode='HTML',
            reply_markup=create_referral_keyboard(message.from_user.id)
        )

@bot.message_handler(func=lambda message: message.text == "💰 Вывод звезд")
def withdrawal_command(message):
    # Проверяем подписку на каналы
    if REQUIRED_CHANNELS:
        is_subscribed, subscription_data = check_subscription_required(message.from_user.id)
        if not is_subscribed:
            channels_text, keyboard = subscription_data
            bot.send_message(
                message.chat.id,
                channels_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            return

    user_info = get_user_info(message.from_user.id)

    if not user_info:
        bot.send_message(message.chat.id, "❌ Ошибка: пользователь не найден")
        return

    withdrawal_text = f'''
<blockquote>💰 <b>Вывод звезд</b> 💰

⭐ <b>Ваш текущий баланс:</b> {user_info['stars']} ⭐
💸 <b>Минимальная сумма вывода:</b> 50 ⭐
⏱️ <b>Время обработки:</b> до 24 часов
📋 <b>Необходимо указать:</b> Ваш username для связи

👇 <b>Выберите сумму для вывода:</b></blockquote>
'''

    bot.send_message(
        message.chat.id,
        withdrawal_text,
        parse_mode='HTML',
        reply_markup=create_withdrawal_keyboard()
    )

@bot.message_handler(func=lambda message: message.text in ["50 звезд", "100 звезд", "200 звезд", "500 звезд", "1000 звезд", "Другая сумма"])
def process_withdrawal_amount(message):
    # Этот обработчик больше не нужен, т.к. кнопки теперь инлайн
    # Но оставляем его для обратной совместимости
    
    # Проверяем подписку на каналы
    if REQUIRED_CHANNELS:
        is_subscribed, subscription_data = check_subscription_required(message.from_user.id)
        if not is_subscribed:
            channels_text, keyboard = subscription_data
            bot.send_message(
                message.chat.id,
                channels_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            return

    user_info = get_user_info(message.from_user.id)

    if not user_info:
        bot.send_message(message.chat.id, "❌ Ошибка: пользователь не найден")
        return

    if message.text == "Другая сумма":
        msg = bot.send_message(
            message.chat.id,
            "<blockquote>💎 <b>Введите сумму для вывода</b>\n\n"
            "Минимальная сумма: 50 звезд\n"
            "Введите число кратное 10:</blockquote>",
            parse_mode='HTML'
        )
        bot.register_next_step_handler(msg, process_custom_withdrawal)
        return

    amount = int(''.join(filter(str.isdigit, message.text)))

    if user_info['stars'] < amount:
        bot.send_message(
            message.chat.id,
            f"<blockquote>❌ <b>Недостаточно звезд!</b>\n\n"
            f"Вы хотите вывести: <b>{amount} ⭐</b>\n"
            f"Ваш баланс: <b>{user_info['stars']} ⭐</b>\n"
            f"Не хватает: <b>{amount - user_info['stars']} ⭐</b>\n\n"
            f"🎯 <b>Пригласите еще друзей чтобы заработать больше!</b></blockquote>",
            parse_mode='HTML',
            reply_markup=create_main_menu()
        )
        return

    if amount < 50:
        bot.send_message(
            message.chat.id,
            "<blockquote>❌ <b>Минимальная сумма вывода 50 звезд!</b></blockquote>",
            parse_mode='HTML',
            reply_markup=create_main_menu()
        )
        return

    user_data = {'amount': amount, 'user_id': message.from_user.id}

    msg = bot.send_message(
        message.chat.id,
        f"<blockquote>📝 <b>Подтверждение вывода</b>\n\n"
        f"Сумма вывода: <b>{amount} ⭐</b>\n"
        f"Ваш баланс: <b>{user_info['stars']} ⭐</b>\n"
        f"Баланс после вывода: <b>{user_info['stars'] - amount} ⭐</b>\n\n"
        f"✍️ <b>Введите ваш @username для связи:</b></blockquote>",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_withdrawal_username, user_data)

def process_custom_withdrawal(message):
    # Проверяем подписку на каналы
    if REQUIRED_CHANNELS:
        is_subscribed, subscription_data = check_subscription_required(message.from_user.id)
        if not is_subscribed:
            channels_text, keyboard = subscription_data
            bot.send_message(
                message.chat.id,
                channels_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            return
    
    try:
        amount = int(message.text)

        if amount < 50:
            bot.send_message(
                message.chat.id,
                "<blockquote>❌ <b>Минимальная сумма вывода 50 ⭐!</b></blockquote>",
                parse_mode='HTML'
            )
            return

        if amount % 10 != 0:
            bot.send_message(
                message.chat.id,
                "<blockquote>❌ <b>Сумма должна быть кратной 10!</b></blockquote>",
                parse_mode='HTML'
            )
            return

        user_info = get_user_info(message.from_user.id)

        if not user_info:
            bot.send_message(message.chat.id, "❌ Ошибка: пользователь не найден")
            return

        if user_info['stars'] < amount:
            bot.send_message(
                message.chat.id,
                f"<blockquote>❌ <b>Недостаточно звезд!</b>\n\n"
                f"Вы хотите вывести: <b>{amount} ⭐</b>\n"
                f"Ваш баланс: <b>{user_info['stars']} ⭐</b>\n"
                f"Не хватает: <b>{amount - user_info['stars']} ⭐</b></blockquote>",
                parse_mode='HTML'
            )
            return

        user_data = {'amount': amount, 'user_id': message.from_user.id}

        msg = bot.send_message(
            message.chat.id,
            f"<blockquote>📝 <b>Подтверждение вывода</b>\n\n"
            f"Сумма вывода: <b>{amount} ⭐</b>\n"
            f"Ваш баланс: <b>{user_info['stars']} ⭐</b>\n"
            f"Баланс после вывода: <b>{user_info['stars'] - amount} ⭐</b>\n\n"
            f"✍️ <b>Введите ваш @username для связи:</b></blockquote>",
            parse_mode='HTML'
        )
        bot.register_next_step_handler(msg, process_withdrawal_username, user_data)

    except ValueError:
        bot.send_message(
            message.chat.id,
            "<blockquote>❌ <b>Пожалуйста, введите число!</b></blockquote>",
            parse_mode='HTML'
        )

def process_withdrawal_username(message, user_data):
    username = message.text.strip()

    if username.startswith('@'):
        username = username[1:]

    if not username or username == '':
        bot.send_message(
            message.chat.id,
            "<blockquote>❌ <b>Пожалуйста, укажите ваш @username!</b></blockquote>",
            parse_mode='HTML'
        )
        return

    amount = user_data['amount']
    user_id = user_data['user_id']

    success, message_text = create_withdrawal(user_id, username, amount)

    if success:
        user_info = get_user_info(user_id)

        bot.send_message(
            message.chat.id,
            f"<blockquote>✅ <b>Заявка на вывод создана!</b>\n\n"
            f"📋 <b>Детали заявки:</b>\n"
            f"• Сумма: <b>{amount} ⭐</b>\n"
            f"• Username: <b>@{username}</b>\n"
            f"• Ваш баланс: <b>{user_info['stars']} ⭐</b>\n"
            f"• Статус: <b>⏳ На рассмотрении</b>\n\n"
            f"⏱️ <b>Время обработки:</b> до 24 часов\n"
            f"📞 <b>С вами свяжутся:</b> @{username}\n\n"
            f"🎯 <b>Следите за статусом заявки в разделе \"Мои заявки\"</b></blockquote>",
            parse_mode='HTML',
            reply_markup=create_main_menu()
        )
    else:
        bot.send_message(
            message.chat.id,
            f"<blockquote>❌ <b>Ошибка!</b>\n\n{message_text}</blockquote>",
            parse_mode='HTML',
            reply_markup=create_main_menu()
        )

@bot.message_handler(func=lambda message: message.text == "🎫 Активировать чек")
def activate_check_menu_command(message):
    """Активация чека из меню"""
    user_id = message.from_user.id

    # Проверка подписки на каналы
    if REQUIRED_CHANNELS:
        is_subscribed, subscription_data = check_subscription_required(user_id)
        if not is_subscribed:
            channels_text, keyboard = subscription_data
            bot.send_message(
                message.chat.id,
                channels_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            return

    msg = bot.send_message(
        message.chat.id,
        "<blockquote>🎫 <b>АКТИВАЦИЯ ЧЕКА</b>\n\n"
        "Введите код чека:\n\n"
        "<b>Пример:</b>\n"
        "<code>ABC123XY</code></blockquote>",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_activate_check_menu)

def process_activate_check_menu(message):
    """Обработка активации чека из меню"""
    user_id = message.from_user.id
    check_code = message.text.strip().upper()

    if not check_code:
        bot.send_message(
            message.chat.id,
            "<blockquote>❌ <b>Введите код чека!</b></blockquote>",
            parse_mode='HTML'
        )
        return

    # Активируем чек
    success, result_message = activate_check(check_code, user_id)

    if success:
        user_info = get_user_info(user_id)
        if user_info:
            bot.send_message(
                message.chat.id,
                f"<blockquote>✅ <b>Чек активирован успешно!</b> 🎉\n\n"
                f"💰 <b>Получено:</b> {result_message.split('! Получено ')[1]}\n"
                f"⭐ <b>Ваш новый баланс:</b> {user_info['stars']} звезд\n\n"
                f"🎯 <b>Теперь вы можете выводить звезды!</b></blockquote>",
                parse_mode='HTML',
                reply_markup=create_main_menu()
            )
        else:
            bot.send_message(
                message.chat.id,
                f"<blockquote>✅ {result_message}</blockquote>",
                parse_mode='HTML',
                reply_markup=create_main_menu()
            )
    else:
        bot.send_message(
            message.chat.id,
            f"<blockquote>❌ <b>Не удалось активировать чек:</b>\n\n{result_message}</blockquote>",
            parse_mode='HTML',
            reply_markup=create_main_menu()
        )

# Команда для активации чека
@bot.message_handler(commands=['activate'])
def activate_check_command(message):
    """Активация чека пользователем"""
    user_id = message.from_user.id

    # Проверка подписки на каналы
    if REQUIRED_CHANNELS:
        is_subscribed, subscription_data = check_subscription_required(user_id)
        if not is_subscribed:
            channels_text, keyboard = subscription_data
            bot.send_message(
                message.chat.id,
                channels_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            return

    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(
            message.chat.id,
            "<blockquote>🎫 <b>АКТИВАЦИЯ ЧЕКА</b>\n\n"
            "Использование: <code>/activate КОД_ЧЕКА</code>\n\n"
            "<b>Пример:</b>\n"
            "<code>/activate ABC123XY</code></blockquote>",
            parse_mode='HTML'
        )
        return

    check_code = parts[1].upper()

    # Активируем чек
    success, result_message = activate_check(check_code, user_id)

    if success:
        user_info = get_user_info(user_id)
        if user_info:
            bot.send_message(
                message.chat.id,
                f"<blockquote>✅ <b>Чек активирован успечно!</b> 🎉\n\n"
                f"💰 <b>Получено:</b> {result_message.split('! Получено ')[1]}\n"
                f"⭐ <b>Ваш новый баланс:</b> {user_info['stars']} звезд\n\n"
                f"🎯 <b>Теперь вы можете выводить звезды!</b></blockquote>",
                parse_mode='HTML'
            )
        else:
            bot.send_message(
                message.chat.id,
                f"<blockquote>✅ {result_message}</blockquote>",
                parse_mode='HTML'
            )
    else:
        bot.send_message(
            message.chat.id,
            f"<blockquote>❌ <b>Не удалось активировать чек:</b>\n\n{result_message}</blockquote>",
            parse_mode='HTML'
        )

@bot.message_handler(func=lambda message: message.text == "📋 Мои заявки")
def my_withdrawals_command(message):
    # Проверяем подписку на каналы
    if REQUIRED_CHANNELS:
        is_subscribed, subscription_data = check_subscription_required(message.from_user.id)
        if not is_subscribed:
            channels_text, keyboard = subscription_data
            bot.send_message(
                message.chat.id,
                channels_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            return

    user_id = message.from_user.id
    withdrawals = get_user_withdrawals(user_id, 10)

    if not withdrawals:
        withdrawals_text = '''
<blockquote>📋 <b>Мои заявки на вывод</b> 📋

У вас еще нет заявок на вывод.

💰 <b>Создайте первую заявку:</b>
1. Нажмите "💰 Вывод звезд"
2. Выберите сумму (от 50 звезд)
3. Укажите ваш @username
4. Ожидайте подтверждения от администратора</blockquote>
'''
    else:
        withdrawals_text = '<blockquote>📋 <b>Мои заявки на вывод</b> 📋\n\n'

        for i, w in enumerate(withdrawals, 1):
            status_emoji = "⏳" if w['status'] == 'pending' else "✅" if w['status'] == 'approved' else "❌"
            status_text = "На рассмотрении" if w['status'] == 'pending' else "Одобрено" if w['status'] == 'approved' else "Отклонено"

            created_date = w['created_at'][:10] if w['created_at'] and len(w['created_at']) >= 10 else "Неизвестно"

            withdrawals_text += f'{i}. <b>{w["amount"]} ⭐</b> - {status_emoji} <b>{status_text}</b>\n'
            withdrawals_text += f'   📅 {created_date} | 🆔 #{w["id"]}\n'

            if w['admin_message']:
                withdrawals_text += f'   💬 {w["admin_message"]}\n'

            withdrawals_text += '\n'

        withdrawals_text += '💡 <b>Статусы:</b>\n'
        withdrawals_text += '⏳ - На рассмотрении\n'
        withdrawals_text += '✅ - Одобрено\n'
        withdrawals_text += '❌ - Отклонено</blockquote>'

    bot.send_message(
        message.chat.id,
        withdrawals_text,
        parse_mode='HTML',
        reply_markup=create_main_menu()
    )

@bot.message_handler(func=lambda message: message.text == "📊 Моя статистика")
def stats_command(message):
    # Проверяем подписку на каналы
    if REQUIRED_CHANNELS:
        is_subscribed, subscription_data = check_subscription_required(message.from_user.id)
        if not is_subscribed:
            channels_text, keyboard = subscription_data
            bot.send_message(
                message.chat.id,
                channels_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            return

    user_info = get_user_info(message.from_user.id)
    transactions = get_transactions(message.from_user.id, 5)
    withdrawals = get_user_withdrawals(message.from_user.id, 3)

    if user_info:
        referrals_count = user_info['referrals_count']
        if referrals_count > 0:
            avg_earnings = user_info['stars'] / referrals_count
        else:
            avg_earnings = 0

        total_withdrawn = 0
        pending_withdrawals = 0
        for w in withdrawals:
            if w['status'] == 'approved':
                total_withdrawn += w['amount']
            elif w['status'] == 'pending':
                pending_withdrawals += w['amount']

        stats_text = f'''
<blockquote>📊 <b>Ваша статистика</b> 📊

⭐ <b>Всего звезд:</b> {user_info['stars']} ⭐
👥 <b>Приглашено друзей:</b> {referrals_count}
💰 <b>Заработано с рефералов:</b> {referrals_count * 5} ⭐
📈 <b>Средний заработок:</b> {avg_earnings:.1f} ⭐ за друга

💸 <b>Статистика выводов:</b>
• Выведено: {total_withdrawn} ⭐
• На рассмотрении: {pending_withdrawals} ⭐
• Доступно для вывода: {user_info['stars']} ⭐

🎯 <b>Прогресс до 50 звезд:</b>
'''

        progress = min(user_info['stars'], 50)
        bar_length = 10
        filled = int(progress / 50 * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)
        stats_text += f'{bar} {progress}/50 ⭐\n\n'

        stats_text += '🔄 <b>Последние операции:</b>\n'

        if transactions:
            for i, trans in enumerate(transactions, 1):
                amount = trans[0] if trans[0] else 0
                trans_type = trans[1] or ""
                desc = trans[2] or ""
                time_str = str(trans[3])[:16] if trans[3] else ""

                if amount > 0:
                    amount_str = f"+{amount} ⭐"
                    emoji = "🔼"
                elif amount < 0:
                    amount_str = f"{amount} ⭐"
                    emoji = "🔽"
                else:
                    amount_str = "0 ⭐"
                    emoji = "⚪"

                stats_text += f'\n{emoji} <b>{amount_str}</b> - {desc}\n   <i>{time_str}</i>\n'
        else:
            stats_text += "\nОпераций пока нет"

        stats_text += '\n\n🎯 <b>Цель: накопить 50 звезд для вывода!</b></blockquote>'

        bot.send_message(
            message.chat.id,
            stats_text,
            parse_mode='HTML'
        )

@bot.message_handler(func=lambda message: message.text == "🏆 Топ рефереров")
def top_command(message):
    # Проверяем подписку на каналы
    if REQUIRED_CHANNELS:
        is_subscribed, subscription_data = check_subscription_required(message.from_user.id)
        if not is_subscribed:
            channels_text, keyboard = subscription_data
            bot.send_message(
                message.chat.id,
                channels_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            return

    top_users = get_top_referrers(10)

    if top_users:
        top_text = '<blockquote>🏆 <b>Топ 10 рефереров</b> 🏆\n\n'

        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

        for i, user in enumerate(top_users):
            if i < len(medals):
                medal = medals[i]
            else:
                medal = f"{i+1}."

            username = f"@{user[1]}" if user[1] else (user[2] or f"User_{user[0]}")
            stars = user[3] if user[3] else 0
            referrals = user[4] if user[4] else 0

            top_text += f'{medal} <b>{username}</b>\n⭐ <b>Звезд:</b> {stars} | 👥 <b>Рефералов:</b> {referrals}\n\n'

        top_text += '</blockquote>'

        bot.send_message(
            message.chat.id,
            top_text,
            parse_mode='HTML'
        )
    else:
        bot.send_message(
            message.chat.id,
            "<blockquote>🏆 <b>Топ рефереров</b>\n\nПока никто не пригласил друзей. Будьте первым!</blockquote>",
            parse_mode='HTML'
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith("copy_link_"))
def copy_link_callback(call):
    """Обработка кнопки копирования ссылки - УПРОЩЕННЫЙ ВАРИАНТ"""
    if call.data.startswith("copy_link_"):
        user_id = call.data.replace("copy_link_", "")
        try:
            user_id = int(user_id)
            referral_link = generate_referral_link(user_id)

            bot.answer_callback_query(
                call.id,
                f"Ссылка скопирована в буфер обмена! Отправьте ее другу.",
                show_alert=False
            )

            bot.send_message(
                call.message.chat.id,
                f"<blockquote>📋 <b>Ваша ссылка для копирования:</b>\n\n<code>{referral_link}</code>\n\n💡 <b>Скопируйте и отправьте другу</b></blockquote>",
                parse_mode='HTML'
            )
        except ValueError:
            bot.answer_callback_query(call.id, "Ошибка при обработке ссылки", show_alert=True)

@bot.message_handler(commands=['invite'])
def invite_link_command(message):
    user_id = message.from_user.id
    referral_link = generate_referral_link(user_id)

    invite_text = f'''
<blockquote>🔗 <b>Ваша реферальная ссылка:</b>

<code>{referral_link}</code></blockquote>
'''

    bot.send_message(
        message.chat.id,
        invite_text,
        parse_mode='HTML',
        reply_markup=create_referral_keyboard(user_id)
    )

@bot.message_handler(commands=['withdraw'])
def withdraw_link_command(message):
    withdrawal_command(message)

@bot.message_handler(commands=['profile'])
def profile_link_command(message):
    profile_command(message)

@bot.message_handler(commands=['top'])
def top_link_command(message):
    top_command(message)

@bot.message_handler(commands=['stats'])
def stats_link_command(message):
    stats_command(message)

@bot.message_handler(commands=['mywithdrawals'])
def my_withdrawals_link_command(message):
    my_withdrawals_command(message)

def send_daily_notifications():
    """Функция для отправки уведомлений"""
    while True:
        try:
            conn = sqlite3.connect('referral_bot.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            users = cursor.fetchall()

            for user_tuple in users:
                try:
                    user_id = user_tuple[0]
                    user_info = get_user_info(user_id)
                    if user_info and user_info['stars'] >= 50:
                        bot.send_message(
                            user_id,
                            f"<blockquote>💰 <b>У вас достаточно звезд для вывода!</b>\n\n"
                            f"Ваш баланс: <b>{user_info['stars']} ⭐</b>\n"
                            f"Минимальная сумма вывода: <b>50 ⭐</b>\n\n"
                            f"🎯 <b>Вы можете вывести свои звезды!</b>\n"
                            f"Нажмите '💰 Вывод звезд' в меню</blockquote>",
                            parse_mode='HTML'
                        )
                except:
                    continue

            conn.close()
        except Exception as e:
            print(f"Ошибка в потоке уведомлений: {e}")

        time.sleep(24 * 3600)

# Главная функция
if __name__ == "__main__":
    print("=" * 50)
    print("🤖 ЗВЕЗДНЫЙ РЕФЕРАЛЬНЫЙ БОТ С ВЫВОДОМ И ЧЕКАМИ ЗАПУЩЕН")
    print("=" * 50)

    init_db()
    init_checks_db()  # Инициализируем таблицу для чеков
    load_channels_from_db()

    try:
        bot_info = bot.get_me()
        print(f"👤 Имя бота: @{bot_info.username}")
        print(f"⭐ Система: 5 звезд за каждого друга (только после подписки на каналы)")
        print(f"💰 Вывод: от 50 звезд")
        print(f"🎫 Чеки: поддерживаются")
        print(f"🔗 Формат ссылки: https://t.me/{bot_info.username}?start=ref_USER_ID")
        print(f"🎫 Формат чека: https://t.me/{bot_info.username}?start=check_КОД")
        print(f"📺 Каналов для подписки: {len(REQUIRED_CHANNELS)}")
        print(f"👑 Админов: {len(ADMIN_IDS)}")
    except:
        print("⚠️ Не удалось получить информацию о боте")

    print("=" * 50)

    # Запуск потока для уведомлений
    notification_thread = threading.Thread(target=send_daily_notifications, daemon=True)
    notification_thread.start()

    try:
        bot.infinity_polling()
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
