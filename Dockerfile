# Используем официальный образ Python
FROM python:3.12-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

# Создаем файл данных с начальной структурой (с правильным экранированием)
RUN printf '{\n\
        "warnings": {},\n\
        "banned": {},\n\
        "restricted_users": {\n\
            "no_links": {},\n\
            "fully_restricted": {},\n\
            "no_forwards": {}\n\
        }\n\
    }' > /app/moderation_data.json && \
    chmod 666 /app/moderation_data.json

# Создаем файл логов
RUN touch /app/moderation.log && \
    chmod 666 /app/moderation.log

# Запускаем бота
CMD ["python", "bot.py"]