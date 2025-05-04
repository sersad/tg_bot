# Используем официальный образ Python
FROM python:3.12-slim

# Устанавливаем зависимости для matplotlib
RUN apt-get update && apt-get install -y \
    libfreetype6 \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

# Создаем файл данных с полной структурой
RUN printf '{\n\
        "warnings": {},\n\
        "banned": {},\n\
        "restricted_users": {\n\
            "no_links": {},\n\
            "fully_restricted": {},\n\
            "no_forwards": {}\n\
        },\n\
        "user_stats": {},\n\
        "parsing_state": {\n\
            "last_parsed_date": null,\n\
            "last_parsed_id": null\n\
        }\n\
    }' > /app/moderation_data.json && \
    chmod 666 /app/moderation_data.json

# Создаем файл логов
RUN touch /app/moderation.log && \
    chmod 666 /app/moderation.log

# Создаем директорию для временных файлов графиков
RUN mkdir -p /app/tmp && \
    chmod 777 /app/tmp

# Запускаем бота
CMD ["python", "bot.py"]
