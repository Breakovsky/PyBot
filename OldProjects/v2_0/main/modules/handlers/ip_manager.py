# main/modules/handlers/ip_manager.py

"""
Модуль для управления IP-адресами в базе данных.
"""

from typing import List, Dict, Optional, Tuple
import logging

from modules.handlers.monitor_db import get_db

logger = logging.getLogger(__name__)


def load_ip_groups() -> List[Dict]:
    """
    Загружает группы IP-адресов из базы данных.
    Возвращает список групп с устройствами.
    """
    try:
        db = get_db()
        groups = db.get_all_servers_list()
        logger.debug(f"Loaded {len(groups)} IP groups from database")
        return groups
    except Exception as e:
        logger.error(f"Error loading IP groups from database: {e}")
        return []


def save_ip_groups(groups: List[Dict]) -> Tuple[bool, str]:
    """
    Сохраняет группы IP-адресов в базу данных.
    Возвращает (success, error_message).
    Note: Эта функция синхронизирует данные из веб-интерфейса с БД.
    """
    try:
        db = get_db()
        
        # Получаем текущие группы из БД
        current_groups = db.get_all_servers_grouped()
        current_group_names = set(current_groups.keys())
        new_group_names = {g["name"] for g in groups}
        
        # Удаляем группы, которых нет в новых данных
        for group_name in current_group_names - new_group_names:
            success, error = db.delete_server_group(group_name)
            if not success:
                logger.warning(f"Failed to delete group {group_name}: {error}")
        
        # Обновляем/добавляем группы и устройства
        for group_data in groups:
            group_name = group_data.get("name", "")
            devices = group_data.get("devices", [])
            
            # Получаем текущие устройства в группе
            current_devices = current_groups.get(group_name, [])
            current_device_names = {d["name"] for d in current_devices}
            new_device_names = {d["name"] for d in devices}
            
            # Удаляем устройства, которых нет в новых данных
            for device in current_devices:
                if device["name"] not in new_device_names:
                    success, error = db.delete_server_device(group_name, device["name"])
                    if not success:
                        logger.warning(f"Failed to delete device {device['name']}: {error}")
            
            # Добавляем/обновляем устройства
            for device in devices:
                device_name = device.get("name", "")
                device_ip = device.get("ip", "")
                
                # Проверяем, существует ли устройство
                device_exists = any(d["name"] == device_name for d in current_devices)
                
                if device_exists:
                    # Обновляем существующее устройство
                    current_device = next(d for d in current_devices if d["name"] == device_name)
                    if current_device["ip"] != device_ip:
                        success, error = db.update_server_device(group_name, device_name, device_name, device_ip)
                        if not success:
                            logger.warning(f"Failed to update device {device_name}: {error}")
                else:
                    # Добавляем новое устройство
                    success, error = db.add_server_device(group_name, device_name, device_ip)
                    if not success:
                        logger.warning(f"Failed to add device {device_name}: {error}")
        
        logger.info(f"IP groups saved to database: {len(groups)} groups")
        return True, ""
    
    except Exception as e:
        error_msg = f"Error saving IP groups to database: {e}"
        logger.error(error_msg)
        return False, error_msg


def validate_ip(ip: str) -> bool:
    """Проверяет валидность IP-адреса."""
    import re
    pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(pattern, ip):
        return False
    
    parts = ip.split('.')
    return all(0 <= int(part) <= 255 for part in parts)


def add_group(group_name: str) -> Tuple[bool, str]:
    """Добавляет новую группу."""
    try:
        db = get_db()
        return db.add_server_group(group_name)
    except Exception as e:
        logger.error(f"Error adding group: {e}")
        return False, f"Ошибка при добавлении группы: {e}"


def delete_group(group_name: str) -> Tuple[bool, str]:
    """Удаляет группу."""
    try:
        db = get_db()
        return db.delete_server_group(group_name)
    except Exception as e:
        logger.error(f"Error deleting group: {e}")
        return False, f"Ошибка при удалении группы: {e}"


def update_group_name(old_name: str, new_name: str) -> Tuple[bool, str]:
    """Изменяет имя группы."""
    try:
        db = get_db()
        return db.update_server_group_name(old_name, new_name)
    except Exception as e:
        logger.error(f"Error updating group name: {e}")
        return False, f"Ошибка при изменении имени группы: {e}"


def add_device(group_name: str, device_name: str, device_ip: str) -> Tuple[bool, str]:
    """Добавляет устройство в группу."""
    try:
        db = get_db()
        return db.add_server_device(group_name, device_name, device_ip)
    except Exception as e:
        logger.error(f"Error adding device: {e}")
        return False, f"Ошибка при добавлении устройства: {e}"


def update_device(group_name: str, old_name: str, new_name: str, new_ip: str) -> Tuple[bool, str]:
    """Обновляет устройство."""
    try:
        db = get_db()
        return db.update_server_device(group_name, old_name, new_name, new_ip)
    except Exception as e:
        logger.error(f"Error updating device: {e}")
        return False, f"Ошибка при обновлении устройства: {e}"


def delete_device(group_name: str, device_name: str) -> Tuple[bool, str]:
    """Удаляет устройство из группы."""
    try:
        db = get_db()
        return db.delete_server_device(group_name, device_name)
    except Exception as e:
        logger.error(f"Error deleting device: {e}")
        return False, f"Ошибка при удалении устройства: {e}"

