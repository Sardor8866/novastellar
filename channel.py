import telebot
from telebot import types
from datetime import datetime

class WithdrawalChannel:
    def __init__(self, bot_token, channel_id=None):
        self.bot = telebot.TeleBot(bot_token)
        self.channel_id = channel_id
    
    def set_channel(self, channel_id):
        """Установка канала для уведомлений"""
        self.channel_id = channel_id
        return True
    
    def send_withdrawal_notification(self, withdrawal_data):
        """
        Отправка уведомления о новом выводе в канал
        
        withdrawal_data: словарь с данными о выводе
        {
            'withdrawal_id': int,
            'user_id': int,
            'username': str,
            'amount': int,
            'created_at': str
        }
        """
        if not self.channel_id:
            print("❌ Канал для уведомлений не установлен")
            return None
        
        try:
            # Создаем сообщение для канала
            message_text = self._create_withdrawal_message(withdrawal_data)
            
            # Создаем клавиатуру с кнопками для обработки
            keyboard = self._create_withdrawal_keyboard(withdrawal_data['withdrawal_id'])
            
            # Отправляем сообщение в канал
            sent_message = self.bot.send_message(
                self.channel_id,
                message_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            
            # Сохраняем ID сообщения для будущего обновления
            return sent_message.message_id
            
        except Exception as e:
            print(f"❌ Ошибка при отправке уведомления в канал: {e}")
            return None
    
    def _create_withdrawal_message(self, data):
        """Создание текста сообщения о выводе"""
        created_time = datetime.now().strftime('%H:%M')
        
        message = f'''
<b>🆕 НОВАЯ ЗАЯВКА #{data['withdrawal_id']}</b>

👤 <b>Пользователь:</b> @{data['username']}
🆔 <b>ID:</b> <code>{data['user_id']}</code>

💰 <b>Сумма:</b> <b>{data['amount']} ⭐</b>

⏰ <b>Время:</b> {created_time}
🔄 <b>Статус:</b> ⏳ <b>ОЖИДАЕТ</b>
'''
        return message
    
    def _create_withdrawal_keyboard(self, withdrawal_id):
        """Создание клавиатуры для управления выводом"""
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        
        keyboard.add(
            types.InlineKeyboardButton(
                "✅ Одобрить",
                callback_data=f"channel_approve_{withdrawal_id}"
            ),
            types.InlineKeyboardButton(
                "❌ Отклонить",
                callback_data=f"channel_reject_{withdrawal_id}"
            )
        )
        
        return keyboard
    
    def update_withdrawal_status(self, message_id, withdrawal_data, status, admin_message=None):
        """
        Обновление сообщения в канале после обработки вывода
        
        status: 'approved' или 'rejected'
        """
        if not self.channel_id:
            return False
        
        try:
            # Создаем обновленное сообщение
            message_text = self._create_updated_message(withdrawal_data, status, admin_message)
            
            # Отправляем обновленное сообщение
            self.bot.edit_message_text(
                message_text,
                self.channel_id,
                message_id,
                parse_mode='HTML'
            )
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка при обновлении сообщения в канале: {e}")
            return False
    
    def _create_updated_message(self, data, status, admin_message=None):
        """Создание обновленного сообщения после обработки"""
        status_emoji = "✅" if status == 'approved' else "❌"
        status_text = "ОДОБРЕНО" if status == 'approved' else "ОТКЛОНЕНО"
        
        processed_time = datetime.now().strftime('%H:%M')
        
        message = f'''
<b>📋 ЗАЯВКА #{data['withdrawal_id']} ОБРАБОТАНА</b>

👤 <b>Пользователь:</b> @{data['username']}
🆔 <b>ID:</b> <code>{data['user_id']}</code>

💰 <b>Сумма:</b> <b>{data['amount']} ⭐</b>

⏰ <b>Время создания:</b> {data['created_at']}
⏱️ <b>Время обработки:</b> {processed_time}

🔄 <b>Статус:</b> {status_emoji} <b>{status_text}</b>
'''

        if admin_message:
            message += f'\n💬 <b>Сообщение:</b> {admin_message}\n'
        
        return message
