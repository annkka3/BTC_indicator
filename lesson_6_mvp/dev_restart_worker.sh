#!/bin/bash
# Скрипт для автоматического перезапуска worker при изменении Python файлов
# Использование: ./dev_restart_worker.sh

echo "Запуск worker с автоматическим перезапуском при изменении файлов..."
echo "Для остановки нажмите Ctrl+C"
echo ""

# Функция для перезапуска worker
restart_worker() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Перезапуск worker..."
    docker-compose restart worker
    echo "Worker перезапущен. Ожидание изменений..."
}

# Первый запуск
restart_worker

# Отслеживание изменений в папке app
if command -v fswatch &> /dev/null; then
    # Используем fswatch (macOS/Linux)
    echo "Используется fswatch для отслеживания изменений..."
    fswatch -o app/ | while read f; do
        restart_worker
    done
elif command -v inotifywait &> /dev/null; then
    # Используем inotifywait (Linux)
    echo "Используется inotifywait для отслеживания изменений..."
    while inotifywait -r -e modify,create,delete app/; do
        restart_worker
    done
else
    echo "ВНИМАНИЕ: fswatch или inotifywait не установлены."
    echo "Установите один из них для автоматического перезапуска:"
    echo "  macOS: brew install fswatch"
    echo "  Linux: sudo apt-get install inotify-tools"
    echo ""
    echo "Или используйте ручной перезапуск: docker-compose restart worker"
    exit 1
fi

