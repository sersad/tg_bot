import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ChatType, ContentType
from aiogram.filters import Command, BaseFilter

from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions,
    InputFile,
    BufferedInputFile
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

import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import io



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

# Константы
STATS_FILE = 'user_stats.json'


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

    if not os.path.exists(data_file):
        initial_data = {
            "warnings": {},
            "banned": {},
            "restricted_users": {
                "no_links": {},
                "fully_restricted": {},
                "no_forwards": {}
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


def init_stats_file():
    """Инициализация файла статистики"""
    data_dir = '/app'
    stats_file = os.path.join(data_dir, STATS_FILE)

    if not os.path.exists(stats_file):
        with open(STATS_FILE, 'w') as f:
            json.dump({}, f)
        os.chmod(STATS_FILE, 0o666)
        logger.info("Создан новый файл статистики")


def load_stats() -> dict:
    """Загрузка статистики из файла"""
    try:
        if not os.path.exists(STATS_FILE):
            init_stats_file()
            return {}

        with open(STATS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки статистики: {e}")
        return {}


def save_stats(data: dict):
    """Сохранение статистики в файл"""
    try:
        with open(STATS_FILE, 'w') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Ошибка сохранения статистики: {e}")


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


def generate_activity_plot(user_data: dict, user_name: str) -> tuple[io.BytesIO, str]:
    """Генерация графика активности с улучшенным дизайном

    Возвращает:
        BytesIO: Буфер с изображением графика
        str: Путь к сохранённому файлу
    """
    """Генерация графика активности с современным стилем"""
    try:
        # Подготовка данных
        dates = []
        counts = []

        sorted_activity = sorted(
            [(date, count) for date, count in user_data['activity'].items()],
            key=lambda x: x[0]
        )[-30:]

        for date_str, count in sorted_activity:
            dates.append(date_str)
            counts.append(count)

        # Используем современный стиль вместо 'seaborn'
        plt.style.use('seaborn-v0_8')  # Или другой доступный стиль

        fig, ax = plt.subplots(figsize=(12, 6))

        # Основной график
        bars = ax.bar(
            dates, counts,
            color='#4CAF50',
            edgecolor='darkgreen',
            linewidth=0.7,
            alpha=0.8
        )

        # Линия тренда
        if len(counts) > 1:
            z = np.polyfit(range(len(counts)), counts, 1)
            p = np.poly1d(z)
            ax.plot(
                dates, p(range(len(counts))),
                color='#FF5722',
                linestyle='--',
                linewidth=2,
                label='Тренд'
            )

        # Настройки графика
        ax.set_title(
            f'Активность пользователя {user_name}\nза последние {len(dates)} дней',
            fontsize=14,
            pad=20
        )
        ax.set_xlabel('Дата', fontsize=12)
        ax.set_ylabel('Количество сообщений', fontsize=12)
        ax.grid(axis='y', linestyle='--', alpha=0.7)

        # Поворот дат на 45 градусов
        plt.xticks(rotation=45, ha='right')

        # Добавляем значения над столбцами
        for bar in bars:
            height = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2., height,
                f'{int(height)}',
                ha='center', va='bottom',
                fontsize=9
            )

        # Легенда если есть тренд
        if len(counts) > 1:
            ax.legend()

        plt.tight_layout()

        # Сохраняем в буфер
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)

        # Дополнительно сохраняем в файл
        plot_filename = f"user_activity_{user_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        plot_path = os.path.join('tmp', plot_filename)

        os.makedirs('tmp', exist_ok=True)
        plt.savefig(plot_path, format='png', dpi=100, bbox_inches='tight')

        plt.close()

        return buf, plot_path

    except Exception as e:
        logger.error(f"Ошибка генерации графика: {e}", exc_info=True)
        raise


async def track_new_messages(message: types.Message):
    """Трекинг новых сообщений в реальном времени"""
    try:
        user_id = str(message.from_user.id)
        msg_date = message.date.date()
        date_str = msg_date.strftime('%Y-%m-%d')

        stats_data = load_stats()

        # Инициализируем структуру при необходимости
        if user_id not in stats_data:
            stats_data[user_id] = {
                'total_messages': 0,
                'activity': {},
                'username': message.from_user.username,
                'full_name': message.from_user.full_name,
                'first_seen': date_str,
                'last_active': date_str
            }

        # Обновляем статистику
        stats_data[user_id]['total_messages'] += 1
        stats_data[user_id]['activity'][date_str] = stats_data[user_id]['activity'].get(date_str, 0) + 1
        stats_data[user_id]['last_active'] = date_str

        save_stats(stats_data)

    except Exception as e:
        logger.error(f"Ошибка трекинга сообщения: {e}")


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


@dp.message(Command("userstats"), AdminFilter())
async def show_user_stats(message: Message):
    """Показать статистику пользователя с графиком активности"""
    try:
        if not message.reply_to_message:
            msg = await message.reply("ℹ️ Ответьте на сообщение пользователя")
            await asyncio.sleep(10)
            await msg.delete()
            return

        target_user = message.reply_to_message.from_user
        user_id = str(target_user.id)
        stats_data = load_stats()
        mod_data = load_data()
        user_stats = stats_data.get(user_id, {})

        # Формируем текстовую часть
        stats_text = (
            f"📊 <b>Статистика пользователя</b> {target_user.mention_html()}:\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"👤 Имя: {target_user.full_name}\n"
            f"✉️ Всего сообщений: <b>{user_stats.get('total_messages', 0)}</b>\n"
            f"⚠️ Предупреждений: <b>{mod_data['warnings'].get(user_id, 0)}/{MAX_WARNINGS}</b>\n"
        )

        # Отправляем текстовую часть
        reply_msg = await message.reply(stats_text, parse_mode="HTML")

        # Генерируем и отправляем график если есть данные
        if user_stats.get('activity'):
            try:
                # Подготовка данных
                dates = []
                counts = []
                # Подготовка данных с правильным парсингом дат
                sorted_activity = sorted(
                    [(datetime.strptime(date, '%Y-%m-%d'), count)
                     for date, count in user_stats['activity'].items()],
                    key=lambda x: x[0]
                )[-30:]

                # Преобразуем даты обратно в строки для отображения
                dates = [date.strftime('%Y-%m-%d') for date, _ in sorted_activity]
                counts = [count for _, count in sorted_activity]

                # Создаем график
                plt.style.use('seaborn-v0_8')
                fig, ax = plt.subplots(figsize=(12, 6))

                # Основной график
                bars = ax.bar(dates, counts, color='#4CAF50', alpha=0.8)

                # Настройки графика
                ax.set_title(f'Активность {target_user.full_name}')
                ax.set_xlabel('Дата')
                ax.set_ylabel('Сообщений')
                plt.xticks(rotation=45)
                plt.tight_layout()

                # Сохраняем в буфер
                buf = io.BytesIO()
                plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
                plt.close()

                # Правильное создание InputFile
                buf.seek(0)
                input_file = types.BufferedInputFile(buf.read(), filename='activity.png')

                # Отправляем фото
                reply_photo = await message.answer_photo(
                    input_file,
                    caption=f"📈 Активность за {len(dates)} дней"
                )
                await asyncio.sleep(AUTO_REMOVE * 3)
                await reply_photo.delete()
            except Exception as e:
                logger.error(f"Ошибка генерации графика: {e}", exc_info=True)
            finally:
                buf.close()

        # Удаляем текстовое сообщение через 300 сек
        await asyncio.sleep(AUTO_REMOVE * 3)
        await reply_msg.delete()

    except Exception as e:
        logger.error(f"Ошибка в команде userstats: {e}", exc_info=True)
        error_msg = await message.reply("❌ Ошибка при получении статистики")
        await asyncio.sleep(10)
        await error_msg.delete()


async def delete_later(filepath: str, delay: int = 300):
    """Удаление файла с задержкой"""
    await asyncio.sleep(delay)
    try:
        os.remove(filepath)
    except Exception as e:
        logger.error(f"Ошибка удаления файла {filepath}: {e}")


# ======================
# ОБРАБОТКА СООБЩЕНИЙ
# ======================


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


# обработчик пересланных сообщений
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
        current_date = message.date.strftime('%Y-%m-%d')

        # Загружаем текущую статистику
        stats = load_stats()

        # Инициализируем структуру для нового пользователя
        if user_id not in stats:
            stats[user_id] = {
                'total_messages': 0,
                'activity': {},
                'username': message.from_user.username,
                'full_name': message.from_user.full_name,
                'first_seen': current_date
            }

        # Обновляем статистику
        stats[user_id]['total_messages'] += 1
        stats[user_id]['activity'][current_date] = stats[user_id]['activity'].get(current_date, 0) + 1
        stats[user_id]['last_active'] = current_date

        # Сохраняем обновлённые данные
        save_stats(stats)

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
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")


