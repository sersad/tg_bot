# tg_bot

add .env file
```
# Токен вашего бота
BOT_TOKEN=

# Дополнительные настройки (опционально)
MAX_WARNINGS=3
BAN_DURATION=3

# Автоудаление сообщений
AUTO_REMOVE=30

# Через запятую без пробелов велоканаш и 3д молели
CHAT_IDS=

# Через запятую без пробелов
BANNED_PHRASES=vk.com/clip,vk.com/video,@trendach,@techmedia,@trends,@banki_oil
```


Перед первым запуском выполните:

```bash
chmod +x init_files.sh
./init_files.sh
```
Затем запускайте как обычно:

```bash
docker-compose up --build
```
