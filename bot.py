import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ChatType, ContentType
from aiogram.filters import Command, BaseFilter
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions
)
from aiogram.fsm.storage.memory import MemoryStorage
from datetime import datetime, timedelta
import json
import os
import asyncio
from dotenv import load_dotenv

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application


# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('moderation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Конфигурация бота
API_TOKEN = os.getenv('BOT_TOKEN')
MAX_WARNINGS = int(os.getenv('MAX_WARNINGS', 3))
BAN_DURATION = int(os.getenv('BAN_DURATION', 15))
BANNED_PHRASES = os.getenv('BANNED_PHRASES', 'vk.com,vk.ru,vkontakte.ru').split(',')
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID', 0))

# Проверка конфигурации
if not API_TOKEN:
    logger.error("Не указан BOT_TOKEN в переменных окружения!")
    exit(1)

logger.info(f"Загружены запрещённые фразы: {BANNED_PHRASES}")

# Инициализация бота
storage = MemoryStorage()
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=storage)

# Файл для хранения данных
DATA_FILE = 'moderation_data.json'


class AdminFilter(BaseFilter):
    """Фильтр для проверки администратора в aiogram v3.x"""

    async def __call__(self, message: Message, bot: Bot) -> bool:
        try:
            return await is_admin(message.chat.id, message.from_user.id, bot)
        except Exception as e:
            logger.error(f"Ошибка проверки администратора: {e}")
            return False


def init_data_file():
    """Инициализация файла данных"""
    data_dir = '/app/data'
    data_file = os.path.join(data_dir, 'moderation_data.json')

    os.makedirs(data_dir, exist_ok=True)

    if not os.path.exists(data_file):
        initial_data = {
            "warnings": {},
            "banned": {},
            "restricted_users": {
                "no_links": {},
                "fully_restricted": {}
            }
        }
        with open(data_file, 'w') as f:
            json.dump(initial_data, f, indent=4)
        os.chmod(data_file, 0o666)
        logger.info("Создан новый файл данных")


def load_data() -> dict:
    """Загрузка данных из файла"""
    default_data = {
        "warnings": {},
        "banned": {},
        "restricted_users": {
            "no_links": {},
            "fully_restricted": {}
        }
    }

    try:
        if not os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'w') as f:
                json.dump(default_data, f, indent=4)
            return default_data

        with open(DATA_FILE, 'r') as f:
            data = json.load(f)

            # Восстановление структуры данных
            for key in default_data:
                if key not in data:
                    data[key] = default_data[key]

            if 'restricted_users' not in data:
                data['restricted_users'] = default_data['restricted_users']
            else:
                for subkey in ['no_links', 'fully_restricted']:
                    if subkey not in data['restricted_users']:
                        data['restricted_users'][subkey] = {}

            return data

    except Exception as e:
        logger.error(f"Ошибка загрузки данных: {e}")
        with open(DATA_FILE, 'w') as f:
            json.dump(default_data, f, indent=4)
        return default_data


def save_data(data: dict):
    """Сохранение данных в файл"""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения данных: {e}")



def log_deleted_message(user_id: str, user_name: str, message_text: str, reason: str):
    """Логирование удаленных сообщений"""
    log_entry = {
        'timestamp': str(datetime.now()),
        'user_id': user_id,
        'user_name': user_name,
        'message': message_text,
        'reason': reason
    }
    logger.info(f"Удалено сообщение: {log_entry}")


async def is_admin(chat_id: int, user_id: int, bot: Bot) -> bool:
    """Проверка, является ли пользователь администратором"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка проверки администратора: {e}")
        return False



def get_unban_keyboard(user_id: str) -> InlineKeyboardMarkup:
    """Создание клавиатуры для разбана"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Разбанить", callback_data=f"unban_{user_id}")]
        ]
    )


# ======================
# КОМАНДЫ АДМИНИСТРАТОРА
# ======================

@dp.message(Command("restrict"), AdminFilter())
async def restrict_user(message: Message):
    """Полное ограничение пользователя"""
    try:
        if not message.reply_to_message:
            await message.reply("ℹ️ Ответьте на сообщение пользователя, которого хотите ограничить")
            return

        target_user = message.reply_to_message.from_user
        data = load_data()

        data['restricted_users']['fully_restricted'][str(target_user.id)] = {
            'name': target_user.full_name,
            'restricted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        save_data(data)

        await message.reply(
            f"✅ Пользователь {target_user.mention_html()} теперь полностью ограничен",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Ошибка при ограничении пользователя: {e}")
        await message.reply("❌ Произошла ошибка при ограничении пользователя")


@dp.message(Command("unrestrict"), AdminFilter())
async def unrestrict_user(message: Message):
    """Снятие ограничений с пользователя"""
    try:
        if not message.reply_to_message:
            await message.reply("ℹ️ Ответьте на сообщение пользователя, которого хотите разограничить")
            return

        target_user = message.reply_to_message.from_user
        user_id = str(target_user.id)
        data = load_data()
        unrestricted = False

        for restriction_type in ['fully_restricted', 'no_links']:
            if user_id in data['restricted_users'][restriction_type]:
                del data['restricted_users'][restriction_type][user_id]
                unrestricted = True

        if unrestricted:
            save_data(data)
            await message.reply(
                f"✅ Пользователь {target_user.mention_html()} больше не ограничен",
                parse_mode='HTML'
            )
        else:
            await message.reply("ℹ️ Этот пользователь не был ограничен")
    except Exception as e:
        logger.error(f"Ошибка при снятии ограничений: {e}")
        await message.reply("❌ Произошла ошибка при снятии ограничений")


@dp.message(Command("restricted_list"), AdminFilter())
async def list_restricted_users(message: Message):
    """Список ограниченных пользователей"""
    data = load_data()
    restricted_users = data.get('restricted_users', {}).get('fully_restricted', {})

    if not restricted_users:
        await message.reply("ℹ️ Нет ограниченных пользователей")
        return

    users_list = []
    for user_id, user_data in restricted_users.items():
        name = user_data.get('name', 'Неизвестный')
        restricted_at = user_data.get('restricted_at', 'неизвестное время')
        users_list.append(f"👤 {name} (ID: {user_id}) - ограничен {restricted_at}")

    await message.reply("📋 Ограниченные пользователи:\n\n" + "\n".join(users_list))


@dp.message(Command("ban_links"), AdminFilter())
async def ban_links_for_user(message: Message):
    """Запрет отправки ссылок для пользователя"""
    try:
        if not message.reply_to_message:
            await message.reply("ℹ️ Ответьте на сообщение пользователя")
            return

        user = message.reply_to_message.from_user
        data = load_data()

        data['restricted_users']['no_links'][str(user.id)] = {
            'name': user.full_name,
            'banned_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        save_data(data)

        await message.reply(
            f"🔗 Пользователю {user.mention_html()} запрещено отправлять ссылки",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Ошибка при запрете ссылок: {e}")
        await message.reply("❌ Произошла ошибка при запрете ссылок")


@dp.message(Command("allow_links"), AdminFilter())
async def allow_links_for_user(message: Message):
    """Разрешение отправки ссылок для пользователя"""
    try:
        if not message.reply_to_message:
            await message.reply("ℹ️ Ответьте на сообщение пользователя")
            return

        user = message.reply_to_message.from_user
        user_id = str(user.id)
        data = load_data()

        if user_id in data['restricted_users']['no_links']:
            del data['restricted_users']['no_links'][user_id]
            save_data(data)
            await message.reply(
                f"🆗 Пользователю {user.mention_html()} разрешено отправлять ссылки",
                parse_mode='HTML'
            )
        else:
            await message.reply("ℹ️ Этому пользователю не был запрещён отправка ссылок")
    except Exception as e:
        logger.error(f"Ошибка при разрешении ссылок: {e}")
        await message.reply("❌ Произошла ошибка при разрешении ссылок")


@dp.message(Command("link_restrictions"), AdminFilter())
async def show_link_restrictions(message: Message):
    """Показать пользователей с запретом ссылок"""
    try:
        data = load_data()
        restricted = data['restricted_users']['no_links']

        if not restricted:
            await message.reply("ℹ️ Нет пользователей с запретом на ссылки")
            return

        users_list = [
            f"• {info['name']} (ID: {uid}) - с {info['banned_at']}"
            for uid, info in restricted.items()
        ]

        await message.reply(
            "📋 Пользователи с запретом на ссылки:\n\n" + "\n".join(users_list)
        )
    except Exception as e:
        logger.error(f"Ошибка при показе ограничений: {e}")
        await message.reply("❌ Произошла ошибка при получении списка ограничений")


# ======================
# ОБРАБОТКА СООБЩЕНИЙ
# ======================

@dp.message(Command("help"))
async def handle_help(message: Message):
    """Обработчик команды /help"""
    try:
        if await is_admin(message.chat.id, message.from_user.id, bot):
            await show_admin_help(message)
        else:
            await show_user_help(message)
    except Exception as e:
        logger.error(f"Ошибка в обработчике help: {e}")
        await message.reply("⚠️ Произошла ошибка при обработке команды")


async def show_admin_help(message: Message):
    """Справка для администраторов"""
    help_text = """
<b>📚 Команды модератора:</b>

<code>/restrict</code> - Полное ограничение пользователя (ответьте на сообщение)
<code>/unrestrict</code> - Снять ограничения (ответьте на сообщение)
<code>/ban_links</code> - Запретить ссылки (ответьте на сообщение)
<code>/allow_links</code> - Разрешить ссылки (ответьте на сообщение)
<code>/restricted_list</code> - Список ограниченных
<code>/link_restrictions</code> - Кто не может отправлять ссылки

<b>Автоматические ограничения:</b>
• Удаление ссылок на vk.com/clip vk.com/video
• Блокировка голосовых/видеосообщений
• Система предупреждений (3 = бан) на 3 минуты
"""
    await message.answer(help_text, parse_mode="HTML")


async def show_user_help(message: Message):
    """Справка для пользователей"""
    help_text = """
<b>📚 Основные правила:</b>

• Нельзя отправлять ссылки на vk.com/clip vk.com/video
• Запрещены голосовые сообщения
• Запрещены видеосообщения (кружочки)

/help - показать эту справку
"""
    await message.answer(help_text, parse_mode="HTML")


@dp.message(
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    F.content_type == ContentType.VOICE
)
async def handle_voice_message(message: Message):
    """Обработка голосовых сообщений"""
    try:
        logger.info(f"Обнаружено голосовое сообщение от {message.from_user.id}")
        await handle_rule_break(
            message=message,
            reason="голосовые сообщения запрещены",
            data=load_data(),
            user_id=str(message.from_user.id),
            chat_id=message.chat.id
        )
    except Exception as e:
        logger.error(f"Ошибка обработки голосового: {e}")
        await message.reply("⚠️ Ошибка обработки голосового сообщения")


@dp.message(
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    F.content_type == ContentType.VIDEO_NOTE
)
async def handle_video_note(message: Message):
    """Обработка видеосообщений (кружочков)"""
    try:
        logger.info(f"Обнаружено видеосообщение от {message.from_user.id}")
        await handle_rule_break(
            message=message,
            reason="видеосообщения запрещены",
            data=load_data(),
            user_id=str(message.from_user.id),
            chat_id=message.chat.id
        )
    except Exception as e:
        logger.error(f"Ошибка обработки видеосообщения: {e}")
        await message.reply("⚠️ Ошибка обработки видеосообщения")


@dp.message(
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    F.forward_from_chat,
    F.forward_from_chat.type == "channel"
)
async def handle_channel_forward(message: Message):
    """Обработка пересланных сообщений из каналов"""
    try:
        channel = message.forward_from_chat
        logger.info(f"Переслано из канала: {channel.title} [ID:{channel.id}]")

        text = message.text or message.caption or (message.document.file_name if message.document else "")

        if text and any(phrase in text.lower() for phrase in BANNED_PHRASES):
            await handle_rule_break(
                message=message,
                reason=f"пересылка из канала {channel.title}",
                data=load_data(),
                user_id=str(message.from_user.id),
                chat_id=message.chat.id
            )
    except Exception as e:
        logger.error(f"Ошибка обработки пересланного сообщения: {e}")
        await message.reply("⚠️ Ошибка обработки пересланного сообщения")


@dp.message(
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    F.content_type.in_({
        ContentType.TEXT,
        ContentType.PHOTO,
        ContentType.VIDEO,
        ContentType.DOCUMENT
    })
)
async def check_regular_message(message: Message):
    """Проверка обычных сообщений"""
    try:
        data = load_data()
        user_id = str(message.from_user.id)
        chat_id = message.chat.id

        # Проверка ограниченных пользователей
        if user_id in data.get('restricted_users', {}).get('fully_restricted', {}):
            await message.delete()
            await message.answer(
                f"⛔ {message.from_user.mention_html()}, ваши сообщения ограничены",
                parse_mode='HTML'
            )
            return

        # Проверка запрета ссылок
        if user_id in data.get('restricted_users', {}).get('no_links', {}):
            if contains_links(message):
                await message.delete()
                await message.answer(
                    f"⛔ {message.from_user.mention_html()}, вам запрещены ссылки",
                    parse_mode='HTML'
                )
                return

        # Проверка текста на запрещенные фразы
        text = message.text or message.caption or ""
        if text and any(phrase in text.lower() for phrase in BANNED_PHRASES):
            await handle_rule_break(
                message=message,
                reason="запрещённые ссылки",
                data=data,
                user_id=user_id,
                chat_id=chat_id
            )
            return

        # Проверка URL в entities
        for entity in (message.entities or []) + (message.caption_entities or []):
            if entity.type in ["url", "text_link"]:
                url = ""
                if entity.type == "url":
                    url = text[entity.offset:entity.offset + entity.length]
                elif entity.type == "text_link":
                    url = entity.url

                if url and any(phrase in url.lower() for phrase in BANNED_PHRASES):
                    await handle_rule_break(
                        message=message,
                        reason="запрещённые ссылки",
                        data=data,
                        user_id=user_id,
                        chat_id=chat_id
                    )
                    return

    except Exception as e:
        logger.error(f"Ошибка проверки сообщения: {e}")


def contains_links(message: Message) -> bool:
    """Проверка наличия ссылок в сообщении"""
    # Проверка текста
    if message.text or message.caption:
        text = (message.text or message.caption).lower()
        if any(proto in text for proto in ['http://', 'https://', 'www.', 't.me/', 'vk.com']):
            return True

    # Проверка entities
    entities = message.entities or message.caption_entities or []
    for entity in entities:
        if entity.type in ["url", "text_link"]:
            return True

    # Проверка кнопок
    if message.reply_markup:
        for row in message.reply_markup.inline_keyboard:
            for button in row:
                if button.url:
                    return True

    return False


async def handle_rule_break(message: Message, reason: str, data: dict, user_id: str, chat_id: int):
    """Обработка нарушений правил"""
    try:
        # Логирование
        log_text = message.text or message.caption or "[медиа-сообщение]"
        log_deleted_message(user_id, message.from_user.full_name, log_text, reason)

        # Удаление сообщения
        await message.delete()

        # Добавление предупреждения
        data['warnings'][user_id] = data.get('warnings', {}).get(user_id, 0) + 1
        warnings = data['warnings'][user_id]
        save_data(data)

        # Уведомление пользователя
        if warnings >= MAX_WARNINGS:
            # Бан пользователя
            ban_until = datetime.now() + timedelta(minutes=BAN_DURATION)
            data['banned'][user_id] = ban_until.strftime('%Y-%m-%d %H:%M:%S')
            save_data(data)

            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                until_date=ban_until,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False
                )
            )

            # Уведомление для администраторов
            admins = await bot.get_chat_administrators(chat_id)
            admins_mentions = "\n".join([f"@{admin.user.username}" for admin in admins if admin.user.username])

            warning_msg = await message.answer(
                f"⚠️ Пользователь {message.from_user.mention_html()} получил бан на {BAN_DURATION} минут "
                f"за нарушение правил ({reason}).\n\n"
                f"Админы могут разбанить:",
                reply_markup=get_unban_keyboard(user_id),
                parse_mode='HTML'
            )

            # Удаление уведомления через 1 минуту
            await asyncio.sleep(180)
            await warning_msg.delete()
        else:
            # Обычное предупреждение
            warning_msg = await message.answer(
                f"⚠️ {message.from_user.mention_html()}, ваше сообщение удалено. Причина: {reason}.\n"
                f"Предупреждение {warnings}/{MAX_WARNINGS}. После {MAX_WARNINGS} предупреждений последует бан.",
                parse_mode='HTML'
            )

            # Удаление уведомления через 10 секунд
            await asyncio.sleep(180)
            await warning_msg.delete()

    except Exception as e:
        logger.error(f"Ошибка обработки нарушения: {e}")


# ======================
# CALLBACK ОБРАБОТЧИКИ
# ======================

@dp.callback_query(F.data.startswith("unban_"))
async def unban_callback_handler(callback: CallbackQuery):
    """Обработка callback'ов для разбана"""
    try:
        user_id = callback.data.split("_")[1]
        chat_id = callback.message.chat.id

        # Проверка прав администратора
        if not await is_admin(chat_id, callback.from_user.id, bot):
            await callback.answer("Только администраторы могут разбанивать", show_alert=True)
            return

        data = load_data()

        if user_id not in data['banned']:
            await callback.answer("Пользователь не забанен", show_alert=True)
            return

        # Снятие ограничений
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )

        # Обновление данных
        data['banned'].pop(user_id)
        data['warnings'][user_id] = 0
        save_data(data)

        await callback.answer("Пользователь разбанен", show_alert=True)
        await callback.message.edit_text(
            f"✅ Пользователь разбанен администратором @{callback.from_user.username}"
        )

    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# ======================
# ЗАПУСК БОТА
# ======================

async def on_startup():
    """Действия при запуске бота"""
    init_data_file()
    try:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text="🟢 Бот-модератор запущен\nИспользуйте /help для списка команд"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления о запуске: {e}")




async def main():
    dp.startup.register(on_startup)
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")


