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

from matplotlib import pyplot as plt
import io
import asyncio
from collections import defaultdict

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
BAN_DURATION = int(os.getenv('BAN_DURATION', 3))
AUTO_REMOVE = int(os.getenv('AUTO_REMOVE', 30))
BANNED_PHRASES = os.getenv('BANNED_PHRASES', 'vk.com,vk.ru,vkontakte.ru').split(',')
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID', 0))
CHAT_IDS = os.getenv('CHAT_IDS', '6585252422,5653011096').split(',')

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

# Глобальная переменная для хранения состояния парсинга
parsing_state = {
    'last_parsed_date': None,
    'is_parsing': False
}

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
    data_dir = '/app'
    data_file = os.path.join(data_dir, DATA_FILE)

    os.makedirs(data_dir, exist_ok=True)

    if not os.path.exists(data_file):
        initial_data = {
            "warnings": {},
            "banned": {},
            "restricted_users": {
                "no_links": {},
                "fully_restricted": {},
                "no_forwards": {}
            },
            "user_stats": {},  # Новая секция для хранения статистики пользователей
            "parsing_state": {  # Состояние парсинга чата
                "last_parsed_date": None,
                "last_parsed_id": None
            }
        }
        with open(data_file, 'w') as f:
            json.dump(initial_data, f, indent=4)
        os.chmod(data_file, 0o666)
        logger.info("Создан новый файл данных с полной структурой")


def load_data() -> dict:
    """Загрузка данных из файла с гарантированным созданием всех ключей"""
    default_data = {
        "warnings": {},
        "banned": {},
        "restricted_users": {
            "no_links": {},
            "fully_restricted": {},
            "no_forwards": {}
        },
        "user_stats": {},
        "parsing_state": {
            "last_parsed_date": None,
            "last_parsed_id": None
        }
    }

    try:
        if not os.path.exists(DATA_FILE):
            init_data_file()
            return default_data

        with open(DATA_FILE, 'r') as f:
            data = json.load(f)

            # Гарантируем наличие всех ключей первого уровня
            for key in default_data:
                if key not in data:
                    data[key] = default_data[key]

            # Гарантируем структуру restricted_users
            for subkey in default_data["restricted_users"]:
                if subkey not in data["restricted_users"]:
                    data["restricted_users"][subkey] = {}

            # Гарантируем структуру user_stats
            if not isinstance(data.get("user_stats"), dict):
                data["user_stats"] = default_data["user_stats"]

            # Гарантируем структуру parsing_state
            if not isinstance(data.get("parsing_state"), dict):
                data["parsing_state"] = default_data["parsing_state"]
            for subkey in default_data["parsing_state"]:
                if subkey not in data["parsing_state"]:
                    data["parsing_state"][subkey] = None

            return data

    except Exception as e:
        logger.error(f"Ошибка загрузки данных: {e}", exc_info=True)
        init_data_file()
        return default_data


def save_data(data: dict):
    """Сохранение данных в файл"""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
            # logger.info(f"Данные сохранены {data}")
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


async def incremental_chat_parse(chat_id: int):
    """Инкрементальный парсинг чата с сохранением прогресса"""
    if parsing_state['is_parsing']:
        return False

    parsing_state['is_parsing'] = True
    data = load_data()

    try:
        # Настройки парсинга
        limit = 1000  # Лимит сообщений за один проход
        offset_date = parsing_state.get('last_parsed_date')

        # Собираем статистику
        user_stats = defaultdict(lambda: {
            'count': 0,
            'daily_activity': defaultdict(int),
            'last_message': None
        })

        async for msg in bot.get_chat_history(chat_id, limit=limit, offset_date=offset_date):
            if not msg.from_user:
                continue

            user_id = str(msg.from_user.id)
            msg_date = msg.date.date()

            user_stats[user_id]['count'] += 1
            user_stats[user_id]['daily_activity'][msg_date] += 1
            user_stats[user_id]['last_message'] = msg.date

            # Обновляем последнюю дату парсинга
            if not offset_date or msg.date < offset_date:
                offset_date = msg.date

        # Сохраняем результаты
        for user_id, stats in user_stats.items():
            if user_id not in data['user_stats']:
                data['user_stats'][user_id] = {
                    'total_messages': 0,
                    'activity': {}
                }

            data['user_stats'][user_id]['total_messages'] += stats['count']

            for date, count in stats['daily_activity'].items():
                date_str = date.strftime('%Y-%m-%d')
                data['user_stats'][user_id]['activity'][date_str] = \
                    data['user_stats'][user_id]['activity'].get(date_str, 0) + count

        parsing_state['last_parsed_date'] = offset_date
        save_data(data)
        return True

    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        return False
    finally:
        parsing_state['is_parsing'] = False


def generate_activity_plot(user_data: dict):
    """Генерация графика активности"""
    dates = []
    counts = []

    # Сортируем данные по дате
    sorted_dates = sorted(user_data['activity'].items(), key=lambda x: x[0])

    for date_str, count in sorted_dates[-30:]:  # Последние 30 дней
        dates.append(date_str)
        counts.append(count)

    # Создаем график
    plt.figure(figsize=(10, 5))
    plt.bar(dates, counts, color='skyblue')
    plt.title('Активность за последние 30 дней')
    plt.xlabel('Дата')
    plt.ylabel('Сообщений')
    plt.xticks(rotation=45)
    plt.tight_layout()

    # Конвертируем в изображение
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()

    return buf

# ======================
# КОМАНДЫ АДМИНИСТРАТОРА
# ======================

@dp.message(Command("restrict"), AdminFilter())
async def restrict_user(message: Message):
    """Полное ограничение пользователя"""
    try:
        if not message.reply_to_message:
            reply_msg = await message.reply("ℹ️ Ответьте на сообщение пользователя, которого хотите ограничить")
            await asyncio.sleep(AUTO_REMOVE)
            await reply_msg.delete()
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
        error_msg = await message.reply("❌ Произошла ошибка при ограничении пользователя")
        await asyncio.sleep(AUTO_REMOVE)
        await error_msg.delete()


@dp.message(Command("unrestrict"), AdminFilter())
async def unrestrict_user(message: Message):
    """Снятие ограничений с пользователя"""
    try:
        if not message.reply_to_message:
            reply_msg = await message.reply("ℹ️ Ответьте на сообщение пользователя, которого хотите разограничить")
            await asyncio.sleep(AUTO_REMOVE)
            await reply_msg.delete()
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
            reply_msg = await message.reply("ℹ️ Этот пользователь не был ограничен")
            await asyncio.sleep(AUTO_REMOVE)
            await reply_msg.delete()
    except Exception as e:
        logger.error(f"Ошибка при снятии ограничений: {e}")
        error_msg = await message.reply("❌ Произошла ошибка при снятии ограничений")
        await asyncio.sleep(AUTO_REMOVE)
        await error_msg.delete()


@dp.message(Command("restricted_list"), AdminFilter())
async def list_restricted_users(message: Message):
    """Список ограниченных пользователей"""
    data = load_data()
    restricted_users = data.get('restricted_users', {}).get('fully_restricted', {})

    if not restricted_users:
        reply_msg = await message.reply("ℹ️ Нет ограниченных пользователей")
        await asyncio.sleep(AUTO_REMOVE)
        await reply_msg.delete()
        return

    users_list = []
    for user_id, user_data in restricted_users.items():
        name = user_data.get('name', 'Неизвестный')
        restricted_at = user_data.get('restricted_at', 'неизвестное время')
        users_list.append(f"👤 {name} (ID: {user_id}) - ограничен {restricted_at}")

    reply_msg = await message.reply("📋 Ограниченные пользователи:\n\n" + "\n".join(users_list))
    await asyncio.sleep(AUTO_REMOVE)
    await reply_msg.delete()


@dp.message(Command("ban_links"), AdminFilter())
async def ban_links_for_user(message: Message):
    """Запрет отправки ссылок для пользователя"""
    try:
        if not message.reply_to_message:
            reply_msg = await message.reply("ℹ️ Ответьте на сообщение пользователя")
            await asyncio.sleep(AUTO_REMOVE)
            await reply_msg.delete()
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
        error_msg = await message.reply("❌ Произошла ошибка при запрете ссылок")
        await asyncio.sleep(AUTO_REMOVE)
        await error_msg.delete()


@dp.message(Command("allow_links"), AdminFilter())
async def allow_links_for_user(message: Message):
    """Разрешение отправки ссылок для пользователя"""
    try:
        if not message.reply_to_message:
            reply_msg = await message.reply("ℹ️ Ответьте на сообщение пользователя")
            await asyncio.sleep(AUTO_REMOVE)
            await reply_msg.delete()
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
            reply_msg = await message.reply("ℹ️ Этому пользователю не был запрещён отправка ссылок")
            await asyncio.sleep(AUTO_REMOVE)
            await reply_msg.delete()
    except Exception as e:
        logger.error(f"Ошибка при разрешении ссылок: {e}")
        error_msg = await message.reply("❌ Произошла ошибка при разрешении ссылок")
        await asyncio.sleep(AUTO_REMOVE)
        await error_msg.delete()


@dp.message(Command("link_restrictions"), AdminFilter())
async def show_link_restrictions(message: Message):
    """Показать пользователей с запретом ссылок"""
    try:
        data = load_data()
        restricted = data['restricted_users']['no_links']

        if not restricted:
            reply_msg = await message.reply("ℹ️ Нет пользователей с запретом на ссылки")
            await asyncio.sleep(AUTO_REMOVE)
            await reply_msg.delete()
            return

        users_list = [
            f"• {info['name']} (ID: {uid}) - с {info['banned_at']}"
            for uid, info in restricted.items()
        ]

        reply_msg = await message.reply(
            "📋 Пользователи с запретом на ссылки:\n\n" + "\n".join(users_list)
        )
        await asyncio.sleep(AUTO_REMOVE)
        await reply_msg.delete()
    except Exception as e:
        logger.error(f"Ошибка при показе ограничений: {e}")
        error_msg = await message.reply("❌ Произошла ошибка при получении списка ограничений")
        await asyncio.sleep(AUTO_REMOVE)
        await error_msg.delete()


@dp.message(Command("ban_forwards"), AdminFilter())
async def ban_forwards_for_user(message: Message):
    """Запрет пересылки сообщений для пользователя"""
    try:
        if not message.reply_to_message:
            reply_msg = await message.reply("ℹ️ Ответьте на сообщение пользователя")
            await asyncio.sleep(AUTO_REMOVE)
            await reply_msg.delete()
            return

        user = message.reply_to_message.from_user
        data = load_data()

        data['restricted_users']['no_forwards'][str(user.id)] = {
            'name': user.full_name,
            'banned_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        save_data(data)
        logger.info(f"User {user.id} banned for forwards")

        await message.reply(
            f"🚫 Пользователю {user.mention_html()} запрещена пересылка сообщений",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Ошибка при запрете пересылки: {e}")
        error_msg = await message.reply("❌ Произошла ошибка при запрете пересылки")
        await asyncio.sleep(AUTO_REMOVE)
        await error_msg.delete()


@dp.message(Command("allow_forwards"), AdminFilter())
async def allow_forwards_for_user(message: Message):
    """Разрешение пересылки сообщений для пользователя"""
    try:
        if not message.reply_to_message:
            reply_msg = await message.reply("ℹ️ Ответьте на сообщение пользователя")
            await asyncio.sleep(AUTO_REMOVE)
            await reply_msg.delete()
            return

        user = message.reply_to_message.from_user
        user_id = str(user.id)
        data = load_data()

        if user_id in data['restricted_users']['no_forwards']:
            del data['restricted_users']['no_forwards'][user_id]
            save_data(data)
            await message.reply(
                f"🆗 Пользователю {user.mention_html()} разрешена пересылка сообщений",
                parse_mode='HTML'
            )
        else:
            reply_msg = await message.reply("ℹ️ Этому пользователю не был запрещена пересылка")
            await asyncio.sleep(AUTO_REMOVE)
            await reply_msg.delete()
    except Exception as e:
        logger.error(f"Ошибка при разрешении пересылки: {e}")
        error_msg = await message.reply("❌ Произошла ошибка при разрешении пересылки")
        await asyncio.sleep(AUTO_REMOVE)
        await error_msg.delete()



@dp.message(Command("forward_restrictions"), AdminFilter())
async def show_forward_restrictions(message: Message):
    """Показать пользователей с запретом пересылки с автоматическим удалением"""
    try:
        data = load_data()
        restricted = data['restricted_users']['no_forwards']

        if not restricted:
            reply_msg = await message.reply("ℹ️ Нет пользователей с запретом на пересылку")

            await asyncio.sleep(AUTO_REMOVE)
            await reply_msg.delete()
            return

        users_list = [
            f"• {info['name']} (ID: {uid}) - с {info['banned_at']}"
            for uid, info in restricted.items()
        ]

        reply_msg = await message.reply(
            "📋 Пользователи с запретом на пересылку:\n\n" + "\n".join(users_list)
        )
        # Удаляем сообщение
        await asyncio.sleep(AUTO_REMOVE)
        await reply_msg.delete()

    except Exception as e:
        logger.error(f"Ошибка при показе ограничений: {e}", exc_info=True)
        error_msg = await message.reply("❌ Произошла ошибка при получении списка ограничений")
        await asyncio.sleep(AUTO_REMOVE)
        await error_msg.delete()


@dp.message(Command("fullstats"), AdminFilter())
async def show_full_user_stats(message: Message):
    """Полная статистика с графиком активности"""
    try:
        if not message.reply_to_message:
            await message.reply("ℹ️ Ответьте на сообщение пользователя")
            return

        # Запускаем фоновый парсинг
        asyncio.create_task(incremental_chat_parse(message.chat.id))

        target_user = message.reply_to_message.from_user
        user_id = str(target_user.id)
        data = load_data()

        # Получаем статистику
        user_stats = data['user_stats'].get(user_id, {})
        warnings = data['warnings'].get(user_id, 0)

        # Формируем текстовую часть
        stats_text = (
            f"📊 <b>Полная статистика</b> {target_user.mention_html()}:\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"👤 Имя: {target_user.full_name}\n"
            f"✉️ Всего сообщений: <b>{user_stats.get('total_messages', 0)}</b>\n"
            f"⚠️ Предупреждений: <b>{warnings}/{MAX_WARNINGS}</b>\n\n"
            f"📈 <i>График активности ниже...</i>"
        )

        # Отправляем текстовую часть
        await message.reply(stats_text, parse_mode="HTML")

        # Генерируем и отправляем график если есть данные
        if user_stats.get('activity'):
            plot_buf = generate_activity_plot(user_stats)
            await message.answer_photo(plot_buf, caption="📊 Активность за последние 30 дней")

    except Exception as e:
        logger.error(f"Ошибка статистики: {e}", exc_info=True)
        await message.reply("❌ Ошибка формирования статистики")


# Фоновая задача для периодического парсинга
async def scheduled_parsing(CHAT_ID):
    while True:
        await asyncio.sleep(3600)  # Каждый час
        await incremental_chat_parse(CHAT_ID)  # Укажите ID вашего чата


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
        error_msg = await message.reply("⚠️ Произошла ошибка при обработке команды")
        await asyncio.sleep(AUTO_REMOVE)
        await error_msg.delete()

async def show_admin_help(message: Message):
    """Справка для администраторов"""
    help_text = f"""
<b>📚 Команды модератора:</b>

<code>/restrict</code> - Полное ограничение пользователя (ответьте на сообщение)
<code>/unrestrict</code> - Снять ограничения (ответьте на сообщение)
<code>/ban_links</code> - Запретить ссылки (ответьте на сообщение)
<code>/allow_links</code> - Разрешить ссылки (ответьте на сообщение)
<code>/ban_forwards</code> - Запретить пересылку (ответьте на сообщение)
<code>/allow_forwards</code> - Разрешить пересылку (ответьте на сообщение)
<code>/restricted_list</code> - Список ограниченных
<code>/link_restrictions</code> - Кто не может отправлять ссылки
<code>/forward_restrictions</code> - Кто не может пересылать сообщения с каналов

<b>Автоматические ограничения:</b>
• Удаление ссылок на <code>{BANNED_PHRASES}</code>
• Блокировка голосовых
• Блокировка видеосообщений от всех кроме администраторов и Герцога)))
• Система предупреждений (3 = бан) на {BAN_DURATION} минуты
"""
    reply_msg = await message.answer(help_text, parse_mode="HTML")
    await asyncio.sleep(AUTO_REMOVE)
    await reply_msg.delete()


async def show_user_help(message: Message):
    """Справка для пользователей"""
    help_text = f"""
<b>📚 Основные правила:</b>
🌈 ТОЛЬКО ПОПРОШУ БЕЗ УБИЙСТВ И ПОЛИТИКИ 🌈
• Нельзя отправлять ссылки на <code>{BANNED_PHRASES}</code>
• Запрещены голосовые сообщения
• Запрещены видеосообщения (кружочки) от всех кроме администраторов и Герцога)))

/help - показать эту справку
"""
    reply_msg = await message.answer(help_text, parse_mode="HTML")
    await asyncio.sleep(AUTO_REMOVE)
    await reply_msg.delete()


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
        error_msg = await message.reply("⚠️ Ошибка обработки голосового сообщения")
        await asyncio.sleep(AUTO_REMOVE)
        await error_msg.delete()


@dp.message(
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    F.content_type == ContentType.VIDEO_NOTE
)
async def handle_video_note(message: Message):
    """Обработка видеосообщений (кружочков) с проверкой админ-прав"""
    try:
        # Проверяем, является ли отправитель администратором
        if await is_admin(message.chat.id, message.from_user.id, message.bot):
            return  # Админам разрешаем отправлять видеосообщения

        logger.info(f"Обнаружено видеосообщение от {message.from_user.id}")
        await handle_rule_break(
            message=message,
            reason="видеосообщения запрещены",
            data=load_data(),
            user_id=str(message.from_user.id),
            chat_id=message.chat.id
        )

    except Exception as e:
        logger.error(f"Ошибка обработки видеосообщения: {e}", exc_info=True)
        try:
            error_msg = await message.reply("⚠️ Ошибка обработки видеосообщения")
            await asyncio.sleep(AUTO_REMOVE)
            await error_msg.delete()
        except Exception as delete_error:
            logger.error(f"Ошибка при удалении сообщения: {delete_error}")


# Модифицируем обработчик пересланных сообщений
@dp.message(
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    F.forward_from_chat,
    F.forward_from_chat.type == "channel"
)
async def handle_channel_forward(message: Message):
    """Обработка пересланных сообщений из каналов"""
    try:
        user_id = str(message.from_user.id)
        data = load_data()

        # Проверка, запрещена ли пересылка для этого пользователя
        if user_id in data['restricted_users']['no_forwards']:
            await message.delete()
            reply_msg = await message.answer(
                f"⛔ {message.from_user.mention_html()}, вам запрещена пересылка сообщений",
                parse_mode='HTML'
            )
            await asyncio.sleep(AUTO_REMOVE)
            await reply_msg.delete()
            return

        # Остальная логика обработки пересылок (если нужно)
        channel = message.forward_from_chat
        logger.info(f"Переслано из канала: {channel.title} [ID:{channel.id}]")

        text = message.text or message.caption or (message.document.file_name if message.document else "")

        if text and any(phrase in text.lower() for phrase in BANNED_PHRASES):
            await handle_rule_break(
                message=message,
                reason=f"пересылка из канала {channel.title}",
                data=data,
                user_id=user_id,
                chat_id=message.chat.id
            )
    except Exception as e:
        logger.error(f"Ошибка обработки пересланного сообщения: {e}")
        error_msg = await message.reply("⚠️ Ошибка обработки пересланного сообщения")
        await asyncio.sleep(AUTO_REMOVE)
        await error_msg.delete()


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
            reply_msg = await message.answer(
                f"⛔ {message.from_user.mention_html()}, ваши сообщения ограничены",
                parse_mode='HTML'
            )
            await asyncio.sleep(AUTO_REMOVE)
            await reply_msg.delete()
            return

        # Проверка запрета ссылок
        if user_id in data.get('restricted_users', {}).get('no_links', {}):
            if contains_links(message):
                await message.delete()
                reply_msg = await message.answer(
                    f"⛔ {message.from_user.mention_html()}, вам запрещены ссылки",
                    parse_mode='HTML'
                )
                await asyncio.sleep(AUTO_REMOVE)
                await reply_msg.delete()
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

            # Удаление уведомления через BAN_DURATION
            await asyncio.sleep(int(BAN_DURATION) * 60)
            await warning_msg.delete()
        else:
            # Обычное предупреждение
            warning_msg = await message.answer(
                f"⚠️ {message.from_user.mention_html()}, ваше сообщение удалено. Причина: {reason}.\n"
                f"Предупреждение {warnings}/{MAX_WARNINGS}. После {MAX_WARNINGS} предупреждений последует бан на {BAN_DURATION} минут.",
                parse_mode='HTML'
            )

            # Удаление уведомления через 10 секунд
            await asyncio.sleep(int(BAN_DURATION) * 60)
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
    for chat_id in CHAT_IDS:
        asyncio.create_task(scheduled_parsing(chat_id))
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")


