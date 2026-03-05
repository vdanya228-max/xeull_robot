# Используем официальный образ Python
FROM python:3.10-slim

# Установка рабочей директории
WORKDIR /app

# Копируем файлы зависимостей
COPY requirements.txt .

# Установка зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код бота
COPY bot.py .

# Запуск бота
EXPOSE 7860
CMD ["python", "bot.py"]
