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

# Устанавливаем зависимости Python
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

# Создаем директорию для временных файлов
RUN mkdir -p /app/tmp && chmod 777 /app/tmp

CMD ["python", "bot.py"]
