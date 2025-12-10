#!/usr/bin/env python3
"""
Wrapper для запуска worker с автоматической перезагрузкой при изменении файлов.
Использует watchfiles для отслеживания изменений в коде.
"""
import os
import sys
import subprocess
import signal
import time
from pathlib import Path

try:
    from watchfiles import watch
except ImportError:
    print("ERROR: watchfiles не установлен. Установите его: pip install watchfiles")
    sys.exit(1)


# Глобальная переменная для процесса
current_process = None


def signal_handler(sig, frame):
    """Обработчик сигнала для корректного завершения процесса."""
    global current_process
    if current_process and current_process.poll() is None:
        print("\n⚠️  Получен сигнал остановки, завершаем процесс...")
        current_process.terminate()
        try:
            current_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            current_process.kill()
    sys.exit(0)


def main():
    global current_process
    
    # Регистрируем обработчик сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Определяем путь к модулю для запуска
    module_name = os.getenv("RELOAD_MODULE", "app.main_worker")
    
    # Путь к директории с кодом для отслеживания
    watch_path = Path("/app/app")
    if not watch_path.exists():
        # Fallback: используем текущую директорию
        watch_path = Path(__file__).parent.parent.parent
    
    print(f"🔄 Запуск с авто-перезагрузкой: {module_name}")
    print(f"📁 Отслеживание изменений в: {watch_path}")
    print("💡 Для остановки нажмите Ctrl+C\n")
    
    # Команда для запуска
    cmd = [sys.executable, "-m", module_name]
    
    # Функция для запуска процесса
    def start_process():
        global current_process
        if current_process and current_process.poll() is None:
            print("🛑 Остановка предыдущего процесса...")
            current_process.terminate()
            try:
                current_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                current_process.kill()
            current_process.wait()
        
        print("🚀 Запуск процесса...")
        current_process = subprocess.Popen(
            cmd,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        return current_process
    
    # Запускаем процесс первый раз
    start_process()
    
    # Функция для фильтрации файлов - игнорируем служебные файлы
    def should_ignore_file(file_path: str) -> bool:
        """Проверяет, нужно ли игнорировать файл."""
        ignore_patterns = [
            '__pycache__',
            '.pyc',
            '.pyo',
            '.py~',
            '.swp',
            '.tmp',
            '.git',
            '.pytest_cache',
            '.mypy_cache',
            '.coverage',
            'htmlcov',
        ]
        file_path_str = str(file_path).lower()
        return any(pattern in file_path_str for pattern in ignore_patterns)
    
    # Отслеживаем изменения файлов
    try:
        # watch() возвращает итератор кортежей (Change, path)
        # Change - это enum: Change.added, Change.modified, Change.deleted
        for changes in watch(watch_path):
            # changes - это множество кортежей (Change, path)
            python_files = []
            for change in changes:
                try:
                    # change - это кортеж (Change, path)
                    change_type, file_path = change
                    file_path_str = str(file_path)
                    
                    # Игнорируем служебные файлы и проверяем, что это Python файл
                    if not should_ignore_file(file_path_str) and file_path_str.endswith('.py'):
                        python_files.append(file_path_str)
                except (ValueError, TypeError):
                    # Если структура данных отличается, просто пропускаем
                    continue
            
            if python_files:
                file_names = [Path(f).name for f in python_files]
                print(f"\n📝 Обнаружены изменения в файлах: {file_names}")
                print("🔄 Перезапуск процесса...\n")
                # Небольшая задержка, чтобы файл точно сохранился
                time.sleep(0.5)
                start_process()
    except KeyboardInterrupt:
        print("\n⚠️  Остановлено пользователем")
        signal_handler(None, None)
    except Exception as e:
        print(f"❌ Ошибка при отслеживании файлов: {e}")
        import traceback
        traceback.print_exc()
        signal_handler(None, None)


if __name__ == "__main__":
    main()

