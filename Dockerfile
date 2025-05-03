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

# Только создаем пустую директорию (без файлов)
RUN mkdir -p /app/data && \
    chmod 777 /app/data  # Даем права на запись

# Создаем файл логов
RUN touch /app/moderation.log && \
    chmod 666 /app/moderation.log

CMD ["python", "bot.py"]