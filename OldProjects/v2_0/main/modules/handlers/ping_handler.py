import asyncio
import logging
import subprocess
import os
import socket
from datetime import datetime
from assets.config import now_msk


def resolve_ip_or_name(target: str) -> str:
    """
    Resolves an IP or hostname to an IP address. Returns the original string if resolution fails.
    """
    try:
        resolved_ip = socket.gethostbyname(target)
        logging.info(f"Успешно разрешено: {target} -> {resolved_ip}")
        return resolved_ip
    except socket.gaierror as e:
        logging.error(f"Не удалось разрешить имя или IP {target}: {e}")
        return target


def is_ip_alive(ip: str) -> bool:
    """
    Checks if an IP address is alive by pinging it.
    """
    param = "-n" if os.name == "nt" else "-c"
    command = ["ping", param, "1", ip]
    try:
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        if result.returncode == 0 and ("TTL=" in result.stdout or "ttl=" in result.stdout):
            logging.info(f"IP {ip} доступен.")
            return True
        logging.warning(f"IP {ip} не отвечает.")
    except Exception as e:
        logging.error(f"Ошибка при пинге {ip}: {e}")
    return False


def load_ip_addresses() -> dict:
    """
    Loads IP addresses from the database.
    """
    try:
        from modules.handlers.monitor_db import get_db
        db = get_db()
        ip_groups = db.get_all_servers_grouped()
        logging.info(f"Загружено {len(ip_groups)} групп IP-адресов из базы данных.")
        return ip_groups
    except Exception as e:
        logging.error(f"Ошибка при загрузке IP-адресов из базы данных: {e}")
        return {}


async def check_ips_and_notify(bot, chat_id, PING_TOPIC_ID, interval=60):
    """
    Periodically checks IPs and notifies the chat if their status changes.
    """
    ip_states = {}

    try:
        await bot.send_message(
            chat_id=chat_id,
            text="Тестовое сообщение: бот запущен и готов проверять IP-адреса.",
            parse_mode="HTML",
            message_thread_id=PING_TOPIC_ID
        )
        logging.info(f"Тестовое сообщение отправлено в тему ID={PING_TOPIC_ID}.")
    except Exception as e:
        logging.error(f"Ошибка при отправке тестового сообщения: {e}")

    while True:
        logging.info("Начало новой итерации проверки IP-адресов.")
        try:
            ip_groups = load_ip_addresses()
            if not ip_groups:
                logging.warning("Список IP пуст или не удалось загрузить XML.")
                await asyncio.sleep(interval)
                continue

            logging.info(f"Загружено {len(ip_groups)} групп IP-адресов.")
            for group_name, devices in ip_groups.items():
                for device in devices:
                    ip = resolve_ip_or_name(device["ip"])
                    name = device["name"]
                    alive = is_ip_alive(ip)
                    previous_status = ip_states.get(ip, "unknown")
                    current_status = "up" if alive else "down"

                    if previous_status == "up" and current_status == "down":
                        message = (
                            f"<b>{name}</b> ({ip}) перестал отвечать на ping.\n"
                            f"Время: {now_msk().strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                        try:
                            logging.info(f"Попытка отправить сообщение в тему ID={PING_TOPIC_ID}: {message}")
                            await bot.send_message(
                                chat_id=chat_id,
                                text=message,
                                parse_mode="HTML",
                                message_thread_id=PING_TOPIC_ID
                            )
                            logging.info(f"Сообщение успешно отправлено в тему ID={PING_TOPIC_ID}")
                        except Exception as e:
                            logging.error(f"Ошибка при отправке сообщения в тему ID={PING_TOPIC_ID}: {e}")

                    if previous_status == "down" and current_status == "up":
                        message = (
                            f"<b>{name}</b> ({ip}) снова доступен!\n"
                            f"Время: {now_msk().strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                        try:
                            logging.info(f"Попытка отправить сообщение в тему ID={PING_TOPIC_ID}: {message}")
                            await bot.send_message(
                                chat_id=chat_id,
                                text=message,
                                parse_mode="HTML",
                                message_thread_id=PING_TOPIC_ID
                            )
                            logging.info(f"Сообщение успешно отправлено в тему ID={PING_TOPIC_ID}")
                        except Exception as e:
                            logging.error(f"Ошибка при отправке сообщения в тему ID={PING_TOPIC_ID}: {e}")

                    ip_states[ip] = current_status

            await asyncio.sleep(interval)

        except Exception as e:
            logging.error(f"Неожиданная ошибка в check_ips_and_notify: {e}")
            await asyncio.sleep(interval)