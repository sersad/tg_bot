import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.dispatcher.filters import ChatTypeFilter, Command, BoundFilter
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext

from datetime import datetime, timedelta
import json
import os
from dotenv import load_dotenv

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

# Загрузка конфигурации из переменных окружения
API_TOKEN = os.getenv('BOT_TOKEN')
MAX_WARNINGS = int(os.getenv('MAX_WARNINGS', 3))
BAN_DURATION = int(os.getenv('BAN_DURATION', 15))
BANNED_PHRASES = os.getenv('BANNED_PHRASES', 'vk.com,vk.ru,vkontakte.ru').split(',')

# Проверка наличия токена
if not API_TOKEN:
    logging.error("Не указан BOT_TOKEN в переменных окружения!")
    exit(1)

logger.info(f"Загружены запрещённые фразы: {BANNED_PHRASES}")
# Инициализация хранилища состояний
storage = MemoryStorage()
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=storage)

# Файл для хранения данных
DATA_FILE = 'moderation_data.json'

class AdminFilter(BoundFilter):
    key = 'is_admin'

    async def check(self, message: types.Message):
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        return member.is_chat_admin()

# Регистрируем фильтр в диспетчере
dp.filters_factory.bind(AdminFilter)


def init_data_file():
    data_dir = '/app/data'
    data_file = os.path.join(data_dir, 'moderation_data.json')

    # Создаем директорию, если не существует
    os.makedirs(data_dir, exist_ok=True)

    # Инициализируем файл, если не существует
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


def load_data():
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

            # Восстанавливаем отсутствующие ключи
            for key in default_data:
                if key not in data:
                    data[key] = default_data[key]

            # Восстанавливаем структуру restricted_users
            if 'restricted_users' not in data:
                data['restricted_users'] = default_data['restricted_users']
            else:
                for subkey in ['no_links', 'fully_restricted']:
                    if subkey not in data['restricted_users']:
                        data['restricted_users'][subkey] = {}

            return data

    except Exception as e:
        logger.error(f"Ошибка загрузки данных, создаем новый файл: {e}")
        with open(DATA_FILE, 'w') as f:
            json.dump(default_data, f, indent=4)
        return default_data


# Сохранение данных
def save_data(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Ошибка при сохранении данных: {e}")


# Логирование удалённых сообщений
def log_deleted_message(user_id, user_name, message_text, reason):
    log_entry = {
        'timestamp': str(datetime.now()),
        'user_id': user_id,
        'user_name': user_name,
        'message': message_text,
        'reason': reason
    }
    logger.info(f"Deleted message: {log_entry}")


# Проверка на админа
async def is_admin(chat_id: int, user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором чата"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.is_chat_admin()
    except Exception as e:
        logger.error(f"Ошибка проверки администратора: {e}")
        return False


# Клавиатура для разбана
def get_unban_keyboard(user_id):
    return InlineKeyboardMarkup().add(
        InlineKeyboardButton("Разбанить", callback_data=f"unban_{user_id}")
    )


# Команда для полного ограничения пользователя
@dp.message_handler(Command("restrict"), AdminFilter())
async def restrict_user(message: types.Message):
    try:
        if not message.reply_to_message:
            await message.reply("ℹ️ Ответьте на сообщение пользователя, которого хотите ограничить")
            return

        target_user = message.reply_to_message.from_user
        data = load_data()

        # Добавляем полное ограничение
        data['restricted_users']['fully_restricted'][str(target_user.id)] = {
            'name': target_user.full_name,
            'restricted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        save_data(data)

        await message.reply(
            f"✅ Пользователь {target_user.get_mention()} теперь полностью ограничен",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Ошибка при ограничении пользователя: {e}")
        await message.reply("❌ Произошла ошибка при ограничении пользователя")


# Команда для снятия всех ограничений
@dp.message_handler(Command("unrestrict"), AdminFilter())
async def unrestrict_user(message: types.Message):
    try:
        if not message.reply_to_message:
            await message.reply("ℹ️ Ответьте на сообщение пользователя, которого хотите разограничить")
            return

        target_user = message.reply_to_message.from_user
        user_id = str(target_user.id)
        data = load_data()
        restricted_users = data['restricted_users']
        unrestricted = False

        # Удаляем из всех категорий ограничений
        for restriction_type in ['fully_restricted', 'no_links']:
            if user_id in restricted_users[restriction_type]:
                del restricted_users[restriction_type][user_id]
                unrestricted = True

        if unrestricted:
            save_data(data)
            await message.reply(
                f"✅ Пользователь {target_user.get_mention()} больше не ограничен",
                parse_mode='HTML'
            )
        else:
            await message.reply("ℹ️ Этот пользователь не был ограничен")
    except Exception as e:
        logger.error(f"Ошибка при снятии ограничений: {e}")
        await message.reply("❌ Произошла ошибка при снятии ограничений")


@dp.message_handler(Command("restricted_list"), AdminFilter())
async def list_restricted_users(message: types.Message):
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


@dp.message_handler(Command("ban_links"), AdminFilter())
async def ban_links_for_user(message: types.Message):
    """Запретить пользователю отправлять ссылки"""
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
        f"🔗 Пользователю {user.get_mention()} запрещено отправлять ссылки",
        parse_mode='HTML'
    )


@dp.message_handler(Command("allow_links"), AdminFilter())
async def allow_links_for_user(message: types.Message):
    """Разрешить пользователю отправлять ссылки"""
    if not message.reply_to_message:
        await message.reply("ℹ️ Ответьте на сообщение пользователя")
        return

    user = message.reply_to_message.from_user
    data = load_data()

    if str(user.id) in data['restricted_users']['no_links']:
        del data['restricted_users']['no_links'][str(user.id)]
        save_data(data)
        await message.reply(
            f"🆗 Пользователю {user.get_mention()} разрешено отправлять ссылки",
            parse_mode='HTML'
        )
    else:
        await message.reply("ℹ️ Этому пользователю не был запрещён отправка ссылок")


@dp.message_handler(Command("link_restrictions"), AdminFilter())
async def show_link_restrictions(message: types.Message):
    """Показать пользователей с запретом ссылок"""
    data = load_data()
    restricted = data['restricted_users']['no_links']

    if not restricted:
        await message.reply("ℹ️ Нет пользователей с запретом на ссылки")
        return

    users_list = [f"• {info['name']} (ID: {uid}) - с {info['banned_at']}"
                  for uid, info in restricted.items()]

    await message.reply(
        "📋 Пользователи с запретом на ссылки:\n\n" + "\n".join(users_list)
    )


@dp.message_handler(Command("help"))
async def handle_help(message: types.Message):
    logger.info(f"Получено сообщение /help от {message.from_user.username}")
    if await AdminFilter().check(message):
        await show_admin_help(message)
    else:
        await show_user_help(message)


async def show_admin_help(message: types.Message):
    """Справка для администраторов"""
    help_text = """
<b>📚 Справка по командам бота-модератора</b>

<u>Для всех пользователей:</u>
/help - Показать эту справку

<u>Для администраторов:</u>
<code>/restrict</code> - Ограничить пользователя (ответьте на сообщение)
<code>/unrestrict</code> - Снять ограничения (ответьте на сообщение)
<code>/restricted_list</code> - Список ограниченных пользователей

<code>/ban_links</code> - Запретить ссылки пользователю (ответьте на сообщение)
<code>/allow_links</code> - Разрешить ссылки пользователю (ответьте на сообщение)
<code>/link_restrictions</code> - Список пользователей с запретом ссылок

<u>Автоматические ограничения:</u>
• Удаление ссылок на VK
• Удаление голосовых сообщений
• Удаление видеосообщений (кружочков)
• Система предупреждений (3 предупреждения = бан на 15 минут)
"""
    await message.reply(help_text, parse_mode="HTML")

    examples_text = """
<b>Примеры использования:</b>
1. Чтобы запретить пользователю отправлять ссылки:
   - Ответьте на его сообщение: <code>/ban_links</code>

2. Чтобы снять ограничения:
   - Ответьте на его сообщение: <code>/allow_links</code>

3. Просмотр всех ограниченных:
   - Отправьте: <code>/link_restrictions</code>
"""
    await message.answer(examples_text, parse_mode="HTML")


async def show_user_help(message: types.Message):
    """Справка для обычных пользователей"""
    help_text = """
<b>📚 Справка по командам бота-модератора</b>

<u>Доступные команды:</u>
/help - Показать эту справку

<u>Автоматические ограничения:</u>
• Удаление ссылок на VK
• Удаление голосовых сообщений
• Удаление видеосообщений (кружочков)
• Система предупреждений (3 предупреждения = бан на 15 минут)

Если у вас есть вопросы, обратитесь к администраторам чата.
"""
    await message.reply(help_text, parse_mode="HTML")




def contains_links(message: types.Message) -> bool:
    """Проверяет, содержит ли сообщение ссылки"""
    # Проверка текста
    if message.text or message.caption:
        text = (message.text or message.caption).lower()
        if any(proto in text for proto in ['http://', 'https://', 'www.', 't.me/', 'vk.com']):
            return True

    # Проверка entities (формальные ссылки)
    entities = message.entities or message.caption_entities or []
    for entity in entities:
        if entity.type in ["url", "text_link"]:
            return True

    # Проверка кнопок с ссылками
    if message.reply_markup:
        for row in message.reply_markup.inline_keyboard:
            for button in row:
                if button.url:
                    return True

    return False


@dp.message_handler(chat_type=[types.ChatType.SUPERGROUP, types.ChatType.GROUP])
async def check_message(message: types.Message):
    data = load_data()
    user_id = str(message.from_user.id)
    chat_id = message.chat.id

    # Логирование входящего сообщения
    logger.info(f"Новое сообщение от {user_id} в чате {chat_id}")
    logger.info(f"Тип сообщения: {message.content_type}")
    logger.info(f"Переслано: {'Да' if message.forward_date else 'Нет'}")

    # 1. Проверка ограничений пользователя
    if user_id in data.get('restricted_users', {}).get('fully_restricted', {}):
        try:
            await message.delete()
            await message.answer(
                f"⛔ {message.from_user.get_mention()}, ваши сообщения ограничены",
                parse_mode='HTML'
            )
            return
        except Exception as e:
            logger.error(f"Ошибка при ограничении пользователя: {e}")
            return

    # 2. Проверка запрета ссылок
    if user_id in data.get('restricted_users', {}).get('no_links', {}) and contains_links(message):
        try:
            await message.delete()
            await message.answer(
                f"⛔ {message.from_user.get_mention()}, вам запрещены ссылки",
                parse_mode='HTML'
            )
            return
        except Exception as e:
            logger.error(f"Ошибка при удалении ссылки: {e}")
            return

    # 3. Проверка голосовых сообщений (рабочая версия)
    if message.voice is not None:  # Явная проверка на None
        await handle_rule_break(message, "голосовые сообщения запрещены", data, user_id, chat_id)
        return

    # 4. Проверка видеосообщений (кружочков)
    if message.video_note is not None:  # Явная проверка на None
        await handle_rule_break(message, "видеосообщения запрещены", data, user_id, chat_id)
        return

    # 5. Проверка пересланных сообщений (полностью рабочая версия)
    if hasattr(message, 'forward_from') or hasattr(message, 'forward_from_chat'):
        try:
            # Получаем текст из всех возможных источников
            text = ""
            if message.text:
                text = message.text
            elif message.caption:
                text = message.caption

            # Проверка на запрещенные фразы
            if text and any(phrase in text.lower() for phrase in BANNED_PHRASES):
                await handle_rule_break(message, "пересылка запрещённого контента", data, user_id, chat_id)
                return
        except Exception as e:
            logger.error(f"Ошибка проверки пересланного сообщения: {e}")
            return

    # 6. Проверка обычных сообщений
    text_to_check = message.text or message.caption or ""
    if text_to_check and any(phrase in text_to_check.lower() for phrase in BANNED_PHRASES):
        await handle_rule_break(message, "запрещённые ссылки", data, user_id, chat_id)
        return

    # 7. Проверка URL в entities
    for entity in (message.entities or []) + (message.caption_entities or []):
        if entity.type in ["url", "text_link"]:
            url = ""
            if entity.type == "url":
                url = (message.text or message.caption or "")[entity.offset:entity.offset + entity.length]
            elif entity.type == "text_link":
                url = entity.url

            if url and any(phrase in url.lower() for phrase in BANNED_PHRASES):
                await handle_rule_break(message, "запрещённые ссылки", data, user_id, chat_id)
                return





@dp.message_handler(chat_type=[types.ChatType.SUPERGROUP, types.ChatType.GROUP], content_types=types.ContentType.VOICE)
async def handle_voice_message(message: types.Message):
    try:
        logger.info(f"Обнаружено голосовое сообщение от {message.from_user.id}")
        logger.info(f"Длительность: {message.voice.duration} сек")
        logger.info(f"Размер: {message.voice.file_size} байт")

        data = load_data()
        user_id = str(message.from_user.id)
        chat_id = message.chat.id

        await handle_rule_break(message, "голосовые сообщения запрещены", data, user_id, chat_id)
        logger.warning(f"Голосовое сообщение от {user_id} удалено")

    except Exception as e:
        logger.error(f"Ошибка при обработке голосового сообщения: {str(e)}", exc_info=True)
        await message.reply("⚠️ Произошла ошибка при обработке голосового сообщения")





@dp.message_handler(chat_type=[types.ChatType.SUPERGROUP, types.ChatType.GROUP],
                    content_types=types.ContentType.VIDEO_NOTE)
async def handle_video_note(message: types.Message):
    try:
        logger.info(f"Обнаружено видеосообщение от {message.from_user.id}")
        logger.info(f"Длительность: {message.video_note.duration} сек | Размер: {message.video_note.file_size} байт")

        data = load_data()
        user_id = str(message.from_user.id)
        chat_id = message.chat.id

        # Удаляем сообщение
        await message.delete()
        logger.warning(f"Видеосообщение от {user_id} удалено")

        # Уведомляем пользователя
        warning_msg = await message.answer(
            f"⛔ {message.from_user.get_mention()}, видеосообщения запрещены",
            parse_mode='HTML'
        )

        # Удаляем уведомление через 10 секунд
        await asyncio.sleep(10)
        await warning_msg.delete()

        # Добавляем предупреждение
        if user_id not in data['warnings']:
            data['warnings'][user_id] = 0
        data['warnings'][user_id] += 1

        # Проверяем на бан (3 предупреждения)
        if data['warnings'][user_id] >= 3:
            ban_until = datetime.now() + timedelta(minutes=BAN_DURATION)
            data['banned'][user_id] = ban_until.strftime('%Y-%m-%d %H:%M:%S')

            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                until_date=ban_until,
                permissions=types.ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False
                )
            )
            logger.warning(f"Пользователь {user_id} забанен за 3 нарушения")

        save_data(data)

    except Exception as e:
        logger.error(f"Ошибка при обработке видеосообщения: {str(e)}", exc_info=True)
        try:
            await message.reply("⚠️ Ошибка при обработке видеосообщения")
        except:
            pass


@dp.message_handler(
    chat_type=[types.ChatType.SUPERGROUP, types.ChatType.GROUP],
    content_types=[
        types.ContentType.TEXT,
        types.ContentType.PHOTO,
        types.ContentType.VIDEO,
        types.ContentType.DOCUMENT,
        types.ContentType.AUDIO,
        types.ContentType.VOICE,
        types.ContentType.VIDEO_NOTE
    ],
    is_forwarded=True
)
async def handle_all_forwarded_media(message: types.Message):
    try:
        # 1. Проверяем, что переслано именно с канала
        if not message.forward_from_chat or message.forward_from_chat.type != "channel":
            return

        channel = message.forward_from_chat
        logger.info(f"Переслано медиа с канала: {channel.title} [ID:{channel.id}]")
        logger.info(f"Тип контента: {message.content_type}")

        # 2. Получаем текст/подпись/название файла
        text = ""
        if message.text:
            text = message.text
        elif message.caption:
            text = message.caption
        elif message.document:
            text = message.document.file_name or ""

        # 3. Проверяем на запрещённый контент
        if text and any(phrase in text.lower() for phrase in BANNED_PHRASES):
            await process_forwarded_violation(message, channel)

    except Exception as e:
        logger.error(f"Ошибка обработки пересланного медиа: {str(e)}", exc_info=True)


async def process_forwarded_violation(message: types.Message, channel: types.Chat):
    """Обработка нарушения при пересылке"""
    try:
        data = load_data()
        user_id = str(message.from_user.id)

        # 1. Удаляем сообщение
        await message.delete()
        logger.warning(f"Удалено пересланное медиа из {channel.title}")

        # 2. Уведомляем пользователя
        warning = await message.answer(
            f"⛔ {message.from_user.get_mention()}, пересылка контента из каналов запрещена\n"
            f"Источник: {channel.title}",
            parse_mode='HTML'
        )

        # 3. Добавляем предупреждение
        data['warnings'][user_id] = data.get('warnings', {}).get(user_id, 0) + 1
        save_data(data)

        # 4. Проверяем на бан
        if data['warnings'].get(user_id, 0) >= 3:
            await ban_user(message.chat.id, user_id)
            logger.warning(f"Пользователь {user_id} забанен за пересылку")

        # Удаляем уведомление через 15 сек
        await asyncio.sleep(15)
        await warning.delete()

    except Exception as e:
        logger.error(f"Ошибка обработки нарушения: {str(e)}")











async def handle_rule_break(message: types.Message, reason: str, data, user_id, chat_id):
    # Логирование
    log_text = message.text or message.caption or "[медиа-сообщение]"
    log_deleted_message(user_id, message.from_user.full_name, log_text, reason)

    # Удаление сообщения
    try:
        await message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")

    # Обновление предупреждений
    if user_id not in data['warnings']:
        data['warnings'][user_id] = 0

    data['warnings'][user_id] += 1
    warnings = data['warnings'][user_id]

    # Сохранение данных
    save_data(data)

    # Формирование ответа
    if warnings >= MAX_WARNINGS:
        # Бан пользователя
        ban_until = datetime.now() + timedelta(minutes=BAN_DURATION)
        data['banned'][user_id] = ban_until.strftime('%Y-%m-%d %H:%M:%S')
        save_data(data)

        try:
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                until_date=ban_until,
                permissions=types.ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False
                )
            )

            # Уведомление с кнопкой разбана
            admins_text = "\n".join([f"@{admin.user.username}" for admin in await bot.get_chat_administrators(chat_id)])
            warning_msg = await message.answer(
                f"⚠️ Пользователь {message.from_user.get_mention()} получил бан на {BAN_DURATION} минут "
                f"за нарушение правил ({reason}).\n\n"
                f"Админы могут разбанить:",
                reply_markup=get_unban_keyboard(user_id),
                parse_mode='HTML'
            )

            # Удаление уведомления через 1 минуту
            await asyncio.sleep(60)
            await warning_msg.delete()

        except Exception as e:
            logger.error(f"Ошибка при бане пользователя: {e}")
    else:
        # Обычное предупреждение
        warning_msg = await message.answer(
            f"⚠️ {message.from_user.get_mention()}, ваше сообщение удалено. Причина: {reason}.\n"
            f"Предупреждение {warnings}/{MAX_WARNINGS}. После {MAX_WARNINGS} предупреждений последует бан.",
            parse_mode='HTML'
        )

        # Удаление уведомления через 10 секунд
        await asyncio.sleep(10)
        await warning_msg.delete()


@dp.callback_query_handler(lambda c: c.data.startswith('unban_'))
async def process_unban(callback_query: types.CallbackQuery):
    try:
        user_id = callback_query.data.split('_')[1]
        chat_id = callback_query.message.chat.id

        # Проверка прав администратора
        if not await is_admin(chat_id, callback_query.from_user.id):
            await callback_query.answer("Только администраторы могут разбанивать пользователей.", show_alert=True)
            return

        # Разбан пользователя
        data = load_data()

        if user_id not in data.get('banned', {}):
            await callback_query.answer("Пользователь не забанен.", show_alert=True)
            return

        # Снимаем ограничения
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=types.ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )

        # Обновляем данные
        data['banned'].pop(user_id, None)
        data['warnings'][user_id] = 0  # Сброс предупреждений
        save_data(data)

        await callback_query.answer("Пользователь разбанен.", show_alert=True)
        await callback_query.message.edit_text(
            f"✅ Пользователь разбанен администратором @{callback_query.from_user.username}."
        )

    except Exception as e:
        logger.error(f"Ошибка при разбане: {e}", exc_info=True)
        await callback_query.answer("Произошла ошибка при разбане.", show_alert=True)



async def on_startup(dp):
    await bot.send_message(
        chat_id=ADMIN_CHAT_ID,  # Замените на ID админской группы
        text="🟢 Бот-модератор запущен\n"
             "Используйте /help для просмотра команд"
    )


if __name__ == '__main__':
    # Проверка переменных окружения
    if not API_TOKEN:
        logger.error("ОШИБКА: Не указан BOT_TOKEN в переменных окружения!")
        exit(1)

    if not BANNED_PHRASES:
        logger.error("ОШИБКА: Не указаны BANNED_PHRASES в переменных окружения!")
        exit(1)

    logger.info("Все обязательные переменные окружения загружены корректно")

    import asyncio

    # Вызываем при старте бота
    init_data_file()

    # Запуск бота
    executor.start_polling(dp, skip_updates=True)

    # from aiogram import executor
    # executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
