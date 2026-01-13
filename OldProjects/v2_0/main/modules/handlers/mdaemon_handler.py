# main/modules/handlers/mdaemon_handler.py

"""
Модуль для работы с Active Directory - получение данных пользователей (email, ФИО).
"""

import logging
import aiohttp
import asyncio
from typing import Optional, List, Dict
from dataclasses import dataclass
from pathlib import Path
import sys

# Добавляем корень проекта в путь для импорта
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from assets.config import get_env_str

logger = logging.getLogger(__name__)


@dataclass
class MDaemonUser:
    """Пользователь из MDaemon."""
    email: str
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: bool = True
    mailbox_size: Optional[int] = None


class MDaemonClient:
    """Клиент для работы с Active Directory."""
    
    def __init__(self):
        # Настройки подключения к Active Directory
        self.ldap_server = get_env_str("DOMAIN_SERVER", "")
        self.ldap_port = int(get_env_str("DOMAIN_PORT", "389"))
        self.ldap_base_dn = get_env_str("DOMAIN_BASE_DN", "")
        self.ldap_bind_dn = get_env_str("DOMAIN_BIND_DN", "")
        self.ldap_bind_password = get_env_str("DOMAIN_BIND_PASSWORD", "")
        
        # Base DN будет определен при первом использовании через _auto_discover_base_dn()
    
    async def _auto_discover_base_dn(self) -> str:
        """Автоматически определяет Base DN домена Active Directory."""
        if not self.ldap_server:
            return ""
        
        try:
            from ldap3 import Server, Connection, ALL, BASE
            import asyncio
            
            server = Server(self.ldap_server, port=self.ldap_port, get_info=ALL)
            
            def discover():
                try:
                    # Пробуем подключиться (можно анонимно или с учетными данными)
                    if self.ldap_bind_dn and self.ldap_bind_password:
                        conn = Connection(server, self.ldap_bind_dn, self.ldap_bind_password, auto_bind=True)
                    else:
                        # Анонимное подключение
                        conn = Connection(server, auto_bind=True)
                    
                    # Получаем информацию о сервере (rootDSE) - это стандартный способ для AD
                    conn.search('', '(objectClass=*)', BASE, attributes=['defaultNamingContext', 'namingContexts'])
                    
                    if conn.entries:
                        entry = conn.entries[0]
                        # Пробуем получить defaultNamingContext (самый надежный способ для AD)
                        if entry.get('defaultNamingContext'):
                            base_dn = str(entry.get('defaultNamingContext', [''])[0])
                            if base_dn:
                                logger.info(f"✅ Автоопределен Base DN: {base_dn}")
                                return base_dn
                        
                        # Если нет defaultNamingContext, пробуем namingContexts
                        if entry.get('namingContexts'):
                            contexts = entry.get('namingContexts', [])
                            if contexts:
                                # Берем первый контекст (обычно это корневой домен)
                                base_dn = str(contexts[0])
                                logger.info(f"✅ Автоопределен Base DN из namingContexts: {base_dn}")
                                return base_dn
                    
                    # Альтернативный способ: определяем из имени сервера
                    if '.' in self.ldap_server:
                        # Если сервер типа DC01.meb52.local, извлекаем домен
                        parts = self.ldap_server.split('.')
                        if len(parts) >= 2:
                            # Пропускаем первую часть (DC01) и берем остальное (meb52.local)
                            domain_parts = parts[1:]
                            base_dn = ','.join([f"dc={part}" for part in domain_parts])
                            logger.info(f"✅ Автоопределен Base DN из имени сервера: {base_dn}")
                            return base_dn
                    
                except Exception as e:
                    logger.debug(f"Ошибка автопоиска Base DN: {e}")
                
                return ""
            
            # Выполняем синхронно в executor
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, discover)
            
        except ImportError:
            logger.error("Библиотека подключения не установлена. Установите: pip install ldap3")
            return ""
        except Exception as e:
            logger.debug(f"Ошибка автопоиска Base DN: {e}")
            return ""
    
    async def get_user_by_email(self, email: str) -> Optional[MDaemonUser]:
        """Получает пользователя по email из Active Directory."""
        return await self._get_user_ldap(email)
    
    async def get_all_users(self) -> List[MDaemonUser]:
        """Получает всех пользователей из Active Directory."""
        return await self._get_all_users_ldap()
    
    # Удалён - используем только LDAP для домена
    # async def _get_user_webadmin(self, email: str) -> Optional[MDaemonUser]:
        """Получает пользователя через WebAdmin API."""
        if not self.base_url or not self.username or not self.password:
            logger.debug("MDaemon WebAdmin credentials not configured")
            return None
        
        # Определяем, нужно ли использовать SSL (HTTPS)
        use_ssl = self.base_url.startswith('https://')
        
        try:
            # Создаём connector с правильными настройками SSL
            # Для самоподписанных сертификатов отключаем проверку
            import ssl
            ssl_context = None
            if use_ssl:
                # Создаём контекст SSL, который не проверяет сертификат (для самоподписанных)
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            
            connector = aiohttp.TCPConnector(ssl=ssl_context if use_ssl else False)
            
            async with aiohttp.ClientSession(connector=connector) as session:
                # Сначала авторизуемся (MDaemon WebAdmin использует cookie-based auth)
                # MDaemon может использовать /login.wdm/ или /cgi-bin/ в зависимости от версии
                base_path = ""
                if "/login.wdm" in self.base_url or "/cgi-bin" in self.base_url:
                    # URL уже содержит путь
                    login_url = f"{self.base_url.rstrip('/')}/cgi-bin/login.cgi"
                else:
                    # Пробуем стандартный путь
                    login_url = f"{self.base_url.rstrip('/')}/cgi-bin/login.cgi"
                login_data = {
                    'username': self.username,
                    'password': self.password,
                    'action': 'login'
                }
                
                logger.debug(f"MDaemon: Attempting login to {login_url}")
                
                async with session.post(login_url, data=login_data, allow_redirects=True) as resp:
                    login_response_url = str(resp.url) if hasattr(resp, 'url') else None
                    logger.debug(f"MDaemon login response: HTTP {resp.status}, URL: {login_response_url}")
                    
                    if resp.status not in (200, 302):
                        logger.debug(f"MDaemon login failed: HTTP {resp.status}")
                        text = await resp.text()
                        logger.debug(f"MDaemon login response body: {text[:200]}")
                        return None
                    
                    # Получаем информацию об аккаунте
                    # Пробуем экспорт через POST запрос (как в JavaScript коде MDaemon)
                    # Экспорт работает через POST с Action=export на URL страницы со списком
                    # Из JavaScript: document.waForm.action = url; document.waForm.Action.value = "export"
                    
                    # Получаем URL страницы со списком пользователей
                    from urllib.parse import urlparse, urlunparse
                    parsed_login = urlparse(login_response_url) if login_response_url else None
                    
                    export_urls = []
                    
                    if parsed_login:
                        # Используем тот же путь что и после логина, но меняем на страницу со списком
                        base_path = f"{parsed_login.scheme}://{parsed_login.netloc}"
                        # MDaemon может использовать main.wdm или userlist.wdm
                        # Извлекаем sid из URL после логина
                        sid = ""
                        if '?' in login_response_url:
                            from urllib.parse import parse_qs
                            query = parse_qs(login_response_url.split('?')[1])
                            sid = query.get('sid', [''])[0]
                        
                        if '/login.wdm' in parsed_login.path or '/main.wdm' in parsed_login.path:
                            # Используем путь /login.wdm/main.wdm
                            export_urls.append(f"{base_path}/login.wdm/main.wdm?sid={sid}" if sid else f"{base_path}/login.wdm/main.wdm")
                            export_urls.append(f"{base_path}/login.wdm/userlist.wdm?sid={sid}" if sid else f"{base_path}/login.wdm/userlist.wdm")
                        
                        # Также пробуем без /login.wdm
                        export_urls.append(f"{base_path}/main.wdm?sid={sid}" if sid else f"{base_path}/main.wdm")
                        export_urls.append(f"{base_path}/userlist.wdm?sid={sid}" if sid else f"{base_path}/userlist.wdm")
                    
                    # Добавляем стандартные варианты
                    export_urls.extend([
                        f"{self.base_url.rstrip('/')}/login.wdm/cgi-bin/userlist.wdm",
                        f"{self.base_url.rstrip('/')}/cgi-bin/userlist.wdm",
                        f"{self.base_url.rstrip('/')}/login.wdm/cgi-bin/listaccounts.cgi",
                        f"{self.base_url.rstrip('/')}/cgi-bin/listaccounts.cgi",
                    ])
                    
                    for export_url in export_urls:
                        try:
                            logger.debug(f"MDaemon: Trying POST export to: {export_url}")
                            
                            # POST запрос с Action=export (как в JavaScript Export())
                            export_data = {
                                'Action': 'export'
                            }
                            
                            async with session.post(export_url, data=export_data, allow_redirects=True) as resp_export:
                                if resp_export.status == 200:
                                    content_type = resp_export.headers.get('Content-Type', '').lower()
                                    text = await resp_export.text()
                                    
                                    logger.debug(f"MDaemon: Export response: Content-Type={content_type}, length={len(text)} chars")
                                    
                                    # Проверяем Content-Type и содержимое
                                    if ('text/csv' in content_type or 'application/csv' in content_type or
                                        (',' in text and '\n' in text and '<html' not in text.lower() and len(text) > 100)):
                                        logger.debug(f"MDaemon: Got CSV export ({len(text)} chars)")
                                        users = await self._parse_csv_export(text)
                                        email_lower = email.lower()
                                        for user in users:
                                            if user.email.lower() == email_lower:
                                                logger.debug(f"MDaemon: Found user {email} with full_name={user.full_name}")
                                                return user
                                    elif ('application/json' in content_type or
                                          (text.strip().startswith('{') or text.strip().startswith('[')) and '<html' not in text.lower()):
                                        logger.debug(f"MDaemon: Got JSON export ({len(text)} chars)")
                                        users = await self._parse_json_export(text)
                                        email_lower = email.lower()
                                        for user in users:
                                            if user.email.lower() == email_lower:
                                                logger.debug(f"MDaemon: Found user {email} with full_name={user.full_name}")
                                                return user
                                    elif ('text/tab-separated' in content_type or
                                          ('\t' in text and '\n' in text and '<html' not in text.lower())):
                                        logger.debug(f"MDaemon: Got TSV export ({len(text)} chars)")
                                        users = await self._parse_tsv_export(text)
                                        email_lower = email.lower()
                                        for user in users:
                                            if user.email.lower() == email_lower:
                                                logger.debug(f"MDaemon: Found user {email} with full_name={user.full_name}")
                                                return user
                        except Exception as e:
                            logger.debug(f"MDaemon: POST export to {export_url} failed: {e}")
                            continue
                    
                    # Также пробуем получить информацию о конкретном пользователе через useredit_account.wdm
                    # Это может быть быстрее, чем экспорт всего списка
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(login_response_url) if login_response_url else None
                        if parsed:
                            base_path = f"{parsed.scheme}://{parsed.netloc}"
                            edit_urls = [
                                f"{base_path}/login.wdm/cgi-bin/useredit_account.wdm?user={email}",
                                f"{base_path}/cgi-bin/useredit_account.wdm?user={email}",
                            ]
                            
                            for edit_url in edit_urls:
                                logger.debug(f"MDaemon: Trying to get user info from: {edit_url}")
                                async with session.get(edit_url, allow_redirects=True) as resp_edit:
                                    if resp_edit.status == 200:
                                        text = await resp_edit.text()
                                        user = await self._parse_html_account(text, email)
                                        if user and user.full_name:
                                            logger.debug(f"MDaemon: Found user {email} with full_name={user.full_name} via edit page")
                                            return user
                    except Exception as e:
                        logger.debug(f"MDaemon: Getting user info via edit page failed: {e}")
                    
                    # Если экспорт не сработал, пробуем получить HTML страницу со списком и парсить её
                    logger.debug(f"MDaemon: Export failed, trying HTML parsing for {email}")
                    
                    # Используем тот же URL что и для экспорта, но GET запрос
                    list_urls = []
                    if parsed_login:
                        base_path = f"{parsed_login.scheme}://{parsed_login.netloc}"
                        sid = ""
                        if '?' in login_response_url:
                            from urllib.parse import parse_qs
                            query = parse_qs(login_response_url.split('?')[1])
                            sid = query.get('sid', [''])[0]
                        
                        # Страница со списком пользователей (data-page="V_USERLIST")
                        sid_param = f"?sid={sid}" if sid else ""
                        list_urls.extend([
                            f"{base_path}/login.wdm/main.wdm{sid_param}",
                            f"{base_path}/login.wdm/cgi-bin/main.wdm{sid_param}",
                        ])
                    
                    list_urls.extend([
                        f"{self.base_url.rstrip('/')}/cgi-bin/listaccounts.cgi",
                        f"{self.base_url.rstrip('/')}/login.wdm/cgi-bin/userlist.wdm",
                        f"{self.base_url.rstrip('/')}/cgi-bin/userlist.wdm",
                    ])
                    
                    for list_url in list_urls:
                        try:
                            logger.debug(f"MDaemon: Trying to get accounts list from: {list_url}")
                            async with session.get(list_url, allow_redirects=True) as resp:
                                if resp.status == 200:
                                    text = await resp.text()
                                    logger.debug(f"MDaemon accounts list response length: {len(text)} chars")
                                    
                                    # Парсим список аккаунтов
                                    all_users = await self._parse_html_accounts_list(text)
                                    
                                    if all_users:
                                        # Ищем нужный email (без учёта регистра)
                                        email_lower = email.lower()
                                        for user in all_users:
                                            if user.email.lower() == email_lower:
                                                logger.debug(f"MDaemon: Found user {email} with full_name={user.full_name}")
                                                return user
                                        
                                        logger.debug(f"MDaemon: User {email} not found in accounts list ({len(all_users)} users parsed)")
                                        break  # Если получили список, но не нашли - пробовать другие URL не нужно
                        except Exception as e:
                            logger.debug(f"MDaemon: Failed to get list from {list_url}: {e}")
                            continue
                    
                    # Если не нашли в списке, пробуем прямые эндпоинты для конкретного аккаунта
                    account_urls = [
                        f"{self.base_url.rstrip('/')}/cgi-bin/accountinfo.cgi",
                        f"{self.base_url.rstrip('/')}/cgi-bin/accountedit.cgi",
                        f"{self.base_url.rstrip('/')}/cgi-bin/accountdetails.cgi"
                    ]
                    
                    for account_url in account_urls:
                        params = {'email': email}
                        
                        logger.debug(f"MDaemon: Trying account URL: {account_url}")
                        
                        async with session.get(account_url, params=params, allow_redirects=True) as resp:
                            if resp.status == 200:
                                text = await resp.text()
                                logger.debug(f"MDaemon account response length: {len(text)} chars")
                                
                                # Парсим HTML ответ (MDaemon WebAdmin возвращает HTML)
                                # Или JSON, если API поддерживает
                                try:
                                    import json
                                    data = json.loads(text)
                                    logger.debug(f"MDaemon: Parsed JSON response for {email}")
                                    return MDaemonUser(
                                        email=email,
                                        full_name=data.get('full_name') or data.get('display_name'),
                                        first_name=data.get('first_name'),
                                        last_name=data.get('last_name'),
                                        is_active=data.get('active', True)
                                    )
                                except:
                                    # Парсим HTML
                                    logger.debug(f"MDaemon: Parsing HTML response for {email}")
                                    user = await self._parse_html_account(text, email)
                                    if user and user.full_name:
                                        return user
                        
        except Exception as e:
            # Не логируем как ошибку, так как MDaemon может быть недоступен - это не критично
            logger.debug(f"MDaemon WebAdmin connection error (non-critical): {e}", exc_info=True)
            return None
    
    async def _parse_html_account(self, html: str, email: str) -> Optional[MDaemonUser]:
        """Парсит HTML ответ от MDaemon WebAdmin."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            
            # Ищем поля с именем (зависит от структуры MDaemon WebAdmin)
            full_name = None
            first_name = None
            last_name = None
            
            # Попытка 1: Ищем input поля с именем
            name_inputs = soup.find_all('input', {
                'name': lambda x: x and any(keyword in x.lower() for keyword in ['name', 'full', 'display', 'fname', 'lname'])
            })
            for inp in name_inputs:
                value = inp.get('value', '').strip()
                name_attr = inp.get('name', '').lower()
                if value:
                    if 'full' in name_attr or 'display' in name_attr:
                        full_name = value
                    elif 'first' in name_attr or 'fname' in name_attr:
                        first_name = value
                    elif 'last' in name_attr or 'lname' in name_attr:
                        last_name = value
            
            # Попытка 2: Ищем в таблицах (MDaemon часто использует таблицы)
            if not full_name:
                rows = soup.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        label_text = cells[0].get_text(strip=True).lower()
                        value_text = cells[1].get_text(strip=True)
                        
                        # Ищем различные варианты названий для ФИО
                        if any(keyword in label_text for keyword in [
                            'full name', 'display name', 'real name', 'name',
                            'имя', 'реальное имя', 'полное имя', 'отображаемое имя',
                            'fname', 'fullname', 'displayname'
                        ]):
                            if value_text and '@' not in value_text and len(value_text) > 1:
                                full_name = value_text
                                break
                        elif any(keyword in label_text for keyword in ['first', 'имя', 'firstname', 'given']):
                            if value_text and '@' not in value_text:
                                first_name = value_text
                        elif any(keyword in label_text for keyword in ['last', 'фамилия', 'lastname', 'surname', 'family']):
                            if value_text and '@' not in value_text:
                                last_name = value_text
            
            # Попытка 3: Ищем в div/span с классами
            if not full_name:
                name_divs = soup.find_all(['div', 'span'], {
                    'class': lambda x: x and any(keyword in str(x).lower() for keyword in ['name', 'full', 'display'])
                })
                for div in name_divs:
                    text = div.get_text(strip=True)
                    if text and '@' not in text and len(text) > 2:
                        full_name = text
                        break
            
            # Если нашли first_name и last_name, но не full_name - объединяем
            if not full_name and (first_name or last_name):
                full_name = ' '.join(filter(None, [first_name, last_name])).strip()
            
            logger.debug(f"MDaemon parsed for {email}: full_name={full_name}, first={first_name}, last={last_name}")
            
            return MDaemonUser(
                email=email,
                full_name=full_name,
                first_name=first_name,
                last_name=last_name
            )
        except Exception as e:
            logger.debug(f"HTML parsing error for {email}: {e}", exc_info=True)
            return MDaemonUser(email=email)
    
    async def _get_all_users_webadmin(self) -> List[MDaemonUser]:
        """Получает всех пользователей через WebAdmin API."""
        if not self.base_url or not self.username or not self.password:
            logger.warning("MDaemon WebAdmin credentials not configured")
            return []
        
        # Определяем, нужно ли использовать SSL (HTTPS)
        use_ssl = self.base_url.startswith('https://')
        
        try:
            # Создаём connector с правильными настройками SSL
            # Для самоподписанных сертификатов отключаем проверку
            import ssl
            ssl_context = None
            if use_ssl:
                # Создаём контекст SSL, который не проверяет сертификат (для самоподписанных)
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            
            connector = aiohttp.TCPConnector(ssl=ssl_context if use_ssl else False)
            
            async with aiohttp.ClientSession(connector=connector) as session:
                # Авторизация
                login_url = f"{self.base_url.rstrip('/')}/cgi-bin/login.cgi"
                login_data = {
                    'username': self.username,
                    'password': self.password,
                    'action': 'login'
                }
                
                logger.debug(f"MDaemon: Attempting login to {login_url} for user list")
                
                async with session.post(login_url, data=login_data, allow_redirects=True) as resp:
                    if resp.status not in (200, 302):
                        logger.debug(f"MDaemon login failed: HTTP {resp.status}")
                        return []
                    
                    # Получаем список аккаунтов через POST экспорт (как в JavaScript Export())
                    export_urls = [
                        f"{self.base_url.rstrip('/')}/cgi-bin/listaccounts.cgi",
                        f"{self.base_url.rstrip('/')}/cgi-bin/userlist.wdm",
                        f"{self.base_url.rstrip('/')}/login.wdm/cgi-bin/listaccounts.cgi",
                        f"{self.base_url.rstrip('/')}/login.wdm/cgi-bin/userlist.wdm",
                    ]
                    
                    # Используем URL после редиректа, если доступен
                    if resp.status in (200, 302) and hasattr(resp, 'url'):
                        from urllib.parse import urlparse
                        parsed = urlparse(str(resp.url))
                        base_path = f"{parsed.scheme}://{parsed.netloc}"
                        if '/login.wdm' in parsed.path:
                            base_path_with_login = f"{base_path}/login.wdm"
                            export_urls.insert(0, f"{base_path_with_login}/cgi-bin/listaccounts.cgi")
                            export_urls.insert(0, f"{base_path_with_login}/cgi-bin/userlist.wdm")
                    
                    for export_url in export_urls:
                        try:
                            logger.debug(f"MDaemon: Trying POST export for all users to: {export_url}")
                            
                            # POST запрос с Action=export
                            export_data = {
                                'Action': 'export'
                            }
                            
                            async with session.post(export_url, data=export_data, allow_redirects=True) as resp_export:
                                if resp_export.status == 200:
                                    content_type = resp_export.headers.get('Content-Type', '').lower()
                                    text = await resp_export.text()
                                    
                                    logger.debug(f"MDaemon: Export response: Content-Type={content_type}, length={len(text)} chars")
                                    
                                    # Проверяем Content-Type и содержимое
                                    if ('text/csv' in content_type or 'application/csv' in content_type or
                                        (',' in text and '\n' in text and '<html' not in text.lower() and len(text) > 100)):
                                        logger.debug(f"MDaemon: Got CSV export ({len(text)} chars)")
                                        users = await self._parse_csv_export(text)
                                        if users:
                                            logger.debug(f"MDaemon: Parsed {len(users)} users from CSV export")
                                            return users
                                    elif ('application/json' in content_type or
                                          (text.strip().startswith('{') or text.strip().startswith('[')) and '<html' not in text.lower()):
                                        logger.debug(f"MDaemon: Got JSON export ({len(text)} chars)")
                                        users = await self._parse_json_export(text)
                                        if users:
                                            logger.debug(f"MDaemon: Parsed {len(users)} users from JSON export")
                                            return users
                                    elif ('text/tab-separated' in content_type or
                                          ('\t' in text and '\n' in text and '<html' not in text.lower())):
                                        logger.debug(f"MDaemon: Got TSV export ({len(text)} chars)")
                                        users = await self._parse_tsv_export(text)
                                        if users:
                                            logger.debug(f"MDaemon: Parsed {len(users)} users from TSV export")
                                            return users
                        except Exception as e:
                            logger.debug(f"MDaemon: POST export to {export_url} failed: {e}")
                            continue
                    
                    # Если экспорт не сработал, используем HTML парсинг как fallback
                    logger.debug(f"MDaemon: Export failed, trying HTML parsing")
                    
                    # Получаем URL страницы со списком пользователей
                    list_urls = []
                    if parsed_login:
                        base_path = f"{parsed_login.scheme}://{parsed_login.netloc}"
                        sid = ""
                        if '?' in login_response_url:
                            from urllib.parse import parse_qs
                            query = parse_qs(login_response_url.split('?')[1])
                            sid = query.get('sid', [''])[0]
                        
                        sid_param = f"?sid={sid}" if sid else ""
                        list_urls.extend([
                            f"{base_path}/login.wdm/main.wdm{sid_param}",
                            f"{base_path}/login.wdm/cgi-bin/main.wdm{sid_param}",
                        ])
                    
                    list_urls.extend([
                        f"{self.base_url.rstrip('/')}/cgi-bin/listaccounts.cgi",
                        f"{self.base_url.rstrip('/')}/login.wdm/cgi-bin/userlist.wdm",
                        f"{self.base_url.rstrip('/')}/cgi-bin/userlist.wdm",
                    ])
                    
                    for list_url in list_urls:
                        try:
                            async with session.get(list_url, allow_redirects=True) as resp:
                                if resp.status == 200:
                                    text = await resp.text()
                                    logger.debug(f"MDaemon: Received accounts list from {list_url}, length: {len(text)} chars")
                                    users = await self._parse_html_accounts_list(text)
                                    if users:
                                        logger.debug(f"MDaemon: Parsed {len(users)} users from HTML list")
                                        return users
                        except Exception as e:
                            logger.debug(f"MDaemon: Failed to get list from {list_url}: {e}")
                            continue
                        
        except Exception as e:
            logger.debug(f"MDaemon WebAdmin list error (non-critical): {e}", exc_info=True)
            return []
    
    async def _parse_csv_export(self, csv_text: str) -> List[MDaemonUser]:
        """Парсит CSV экспорт пользователей из MDaemon."""
        import csv
        from io import StringIO
        users = []
        
        try:
            # Пробуем разные разделители
            for delimiter in [',', ';', '\t']:
                try:
                    reader = csv.DictReader(StringIO(csv_text), delimiter=delimiter)
                    for row in reader:
                        # Ищем email в разных возможных колонках
                        email = None
                        full_name = None
                        
                        for key, value in row.items():
                            key_lower = key.lower()
                            if not value:
                                continue
                                
                            if '@' in str(value) and '.' in str(value):
                                # Это похоже на email
                                email = str(value).strip()
                            elif any(kw in key_lower for kw in ['name', 'full', 'display', 'real', 'имя', 'фіо']):
                                full_name = str(value).strip()
                        
                        if email and '@' in email:
                            users.append(MDaemonUser(
                                email=email,
                                full_name=full_name
                            ))
                    
                    if users:
                        logger.debug(f"MDaemon: Parsed {len(users)} users from CSV")
                        return users
                except Exception as e:
                    logger.debug(f"MDaemon: CSV parsing with delimiter '{delimiter}' failed: {e}")
                    continue
                    
        except Exception as e:
            logger.debug(f"MDaemon: CSV export parsing error: {e}")
        
        return users
    
    async def _parse_json_export(self, json_text: str) -> List[MDaemonUser]:
        """Парсит JSON экспорт пользователей из MDaemon."""
        import json
        users = []
        
        try:
            data = json.loads(json_text)
            
            # MDaemon может вернуть данные в разных форматах
            # Попробуем разные структуры
            accounts = []
            if isinstance(data, list):
                accounts = data
            elif isinstance(data, dict):
                if 'accounts' in data:
                    accounts = data['accounts']
                elif 'users' in data:
                    accounts = data['users']
                else:
                    accounts = [data]
            
            for account in accounts:
                if not isinstance(account, dict):
                    continue
                
                # Ищем email
                email = None
                for key in ['email', 'mail', 'mailbox', 'account', 'user']:
                    if key in account and account[key]:
                        email = str(account[key]).strip()
                        break
                
                # Ищем ФИО
                full_name = None
                for key in ['full_name', 'fullName', 'display_name', 'displayName', 
                           'real_name', 'realName', 'name', 'fio', 'фіо']:
                    if key in account and account[key]:
                        full_name = str(account[key]).strip()
                        break
                
                if email and '@' in email:
                    users.append(MDaemonUser(
                        email=email,
                        full_name=full_name
                    ))
            
            logger.debug(f"MDaemon: Parsed {len(users)} users from JSON")
        except Exception as e:
            logger.debug(f"MDaemon: JSON export parsing error: {e}")
        
        return users
    
    async def _parse_tsv_export(self, tsv_text: str) -> List[MDaemonUser]:
        """Парсит TSV/TXT экспорт пользователей из MDaemon."""
        import csv
        from io import StringIO
        users = []
        
        try:
            reader = csv.DictReader(StringIO(tsv_text), delimiter='\t')
            for row in reader:
                email = None
                full_name = None
                
                for key, value in row.items():
                    if not value:
                        continue
                    
                    key_lower = key.lower()
                    if '@' in str(value) and '.' in str(value):
                        email = str(value).strip()
                    elif any(kw in key_lower for kw in ['name', 'full', 'display', 'real', 'имя', 'фіо']):
                        full_name = str(value).strip()
                
                if email and '@' in email:
                    users.append(MDaemonUser(
                        email=email,
                        full_name=full_name
                    ))
            
            logger.debug(f"MDaemon: Parsed {len(users)} users from TSV")
        except Exception as e:
            logger.debug(f"MDaemon: TSV export parsing error: {e}")
        
        return users
    
    async def _parse_html_accounts_list(self, html: str) -> List[MDaemonUser]:
        """Парсит HTML список аккаунтов из таблицы MDaemon WebAdmin."""
        users = []
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            
            # Ищем таблицу с аккаунтами
            # MDaemon использует атрибут glc_form_waform_selectid с email в tr элементе
            # Например: <tr glc_form_waform_selectid="admin@meb52.com">
            rows = soup.find_all('tr', attrs={'glc_form_waform_selectid': True})
            
            if not rows:
                # Альтернативный способ - ищем по классу list-mailbox (ячейка с почтовым ящиком)
                rows = soup.find_all('tr')
                rows = [r for r in rows if r.find('td', class_=lambda x: x and 'list-mailbox' in str(x))]  # Только строки с классом list-mailbox
            
            logger.debug(f"MDaemon: Found {len(rows)} rows to parse")
            
            # Если не нашли строки, логируем фрагмент HTML для отладки
            if not rows:
                # Ищем любые tr элементы
                all_tr = soup.find_all('tr')
                logger.debug(f"MDaemon: Total <tr> elements found: {len(all_tr)}")
                
                # Показываем первые 1000 символов HTML для отладки
                html_preview = html[:1000] if len(html) > 1000 else html
                logger.debug(f"MDaemon: HTML preview (first 1000 chars): {html_preview}")
                
                # Ищем таблицы с id
                tables = soup.find_all('table')
                logger.debug(f"MDaemon: Found {len(tables)} tables")
                for i, table in enumerate(tables[:3]):  # Первые 3 таблицы
                    table_id = table.get('id', 'no-id')
                    logger.debug(f"MDaemon: Table {i+1} id='{table_id}', rows={len(table.find_all('tr'))}")
            
            for row in rows:
                try:
                    # Способ 1: Извлекаем email из атрибута glc_form_waform_selectid
                    email = row.get('glc_form_waform_selectid', '')
                    
                    if not email or '@' not in email:
                        # Способ 2: Собираем email из ячеек таблицы
                        cells = row.find_all('td', class_=['list-mailbox', 'list-domain'])
                        if len(cells) >= 2:
                            mailbox = cells[0].get_text(strip=True) if cells[0].has_attr('class') and 'list-mailbox' in cells[0].get('class', []) else ""
                            domain = cells[1].get_text(strip=True) if cells[1].has_attr('class') and 'list-domain' in cells[1].get('class', []) else ""
                            if mailbox and domain:
                                email = f"{mailbox}@{domain}"
                    
                    if not email or '@' not in email:
                        # Способ 3: Ищем любые td с классом list-mailbox и list-domain
                        mailbox_cells = row.find_all('td', class_=lambda x: x and 'list-mailbox' in x)
                        domain_cells = row.find_all('td', class_=lambda x: x and 'list-domain' in x)
                        if mailbox_cells and domain_cells:
                            mailbox = mailbox_cells[0].get_text(strip=True)
                            domain = domain_cells[0].get_text(strip=True)
                            if mailbox and domain:
                                email = f"{mailbox}@{domain}"
                    
                    if not email or '@' not in email:
                        continue  # Пропускаем строки без email
                    
                    # Извлекаем ФИО (Реальное имя) из ячейки с классом list-real-name
                    real_name_cells = row.find_all('td', class_=lambda x: x and 'list-real-name' in x)
                    real_name = real_name_cells[0].get_text(strip=True) if real_name_cells else None
                    
                    # Если не нашли через класс, пробуем по индексу (cells[3])
                    if not real_name:
                        all_cells = row.find_all('td')
                        if len(all_cells) >= 4:
                            # Пробуем найти по индексу (cells[3] обычно Реальное имя)
                            real_name = all_cells[3].get_text(strip=True) if len(all_cells) > 3 else None
                    
                    # Добавляем пользователя
                    if email and '@' in email:
                        users.append(MDaemonUser(
                            email=email,
                            full_name=real_name if real_name else None
                        ))
                        logger.debug(f"Parsed user: {email} -> {real_name}")
                        
                except Exception as e:
                    logger.debug(f"Error parsing row: {e}")
                    continue
                        
        except Exception as e:
            logger.debug(f"HTML accounts list parsing error: {e}", exc_info=True)
        
        logger.debug(f"Total parsed users: {len(users)}")
        return users
    
    async def _get_user_ldap(self, email: str) -> Optional[MDaemonUser]:
        """Получает пользователя из Active Directory."""
        if not self.ldap_server:
            logger.debug("Сервер Active Directory не настроен")
            return None
        
        # Автопоиск Base DN, если не указан
        if not self.ldap_base_dn:
            logger.debug("Base DN не указан, выполняю автопоиск...")
            self.ldap_base_dn = await self._auto_discover_base_dn()
            if not self.ldap_base_dn:
                logger.warning("Не удалось определить Base DN. Укажите DOMAIN_BASE_DN в .env")
                return None
        
        try:
            from ldap3 import Server, Connection, ALL, SUBTREE
            import asyncio
            
            server = Server(self.ldap_server, port=self.ldap_port, get_info=ALL)
            
            # Выполняем синхронно в executor (ldap3 не поддерживает async)
            loop = asyncio.get_event_loop()
            
            def ldap_search():
                with Connection(server, self.ldap_bind_dn, self.ldap_bind_password, auto_bind=True) as conn:
                    # Пробуем разные фильтры для Active Directory и MDaemon
                    # Active Directory обычно использует: mail, userPrincipalName, proxyAddresses
                    # MDaemon может использовать: mail, emailAddress
                    search_filters = [
                        # Active Directory фильтры (приоритет)
                        f"(&(mail={email})(objectClass=user))",
                        f"(&(userPrincipalName={email})(objectClass=user))",
                        f"(&(|(mail={email})(userPrincipalName={email}))(objectClass=user))",
                        # Общие фильтры
                        f"(&(mail={email})(objectClass=*))",
                        f"(mail={email})",
                        # MDaemon фильтры
                        f"(&(emailAddress={email})(objectClass=*))",
                        f"(emailAddress={email})",
                    ]
                    
                    for search_filter in search_filters:
                        try:
                            conn.search(
                                search_base=self.ldap_base_dn,
                                search_filter=search_filter,
                                search_scope=SUBTREE,
                                attributes=['mail', 'cn', 'givenName', 'sn', 'displayName', 'emailAddress', 'name', 'fullName']
                            )
                            
                            if conn.entries:
                                entry = conn.entries[0]
                                # Извлекаем email из разных атрибутов (Active Directory и MDaemon)
                                user_email = None
                                
                                # Пробуем разные атрибуты
                                for attr in ['mail', 'userPrincipalName', 'emailAddress']:
                                    attr_value = entry.get(attr)
                                    if attr_value:
                                        if isinstance(attr_value, list) and len(attr_value) > 0:
                                            user_email = str(attr_value[0])
                                        elif attr_value:
                                            user_email = str(attr_value)
                                        if user_email and '@' in user_email:
                                            break
                                
                                # Если не нашли, используем исходный email
                                if not user_email:
                                    user_email = email
                                
                                # Извлекаем ФИО из разных атрибутов
                                full_name = None
                                if entry.get('cn'):
                                    full_name = str(entry.get('cn', [''])[0] if hasattr(entry.get('cn', []), '__len__') else entry.get('cn', ''))
                                if not full_name and entry.get('displayName'):
                                    full_name = str(entry.get('displayName', [''])[0] if hasattr(entry.get('displayName', []), '__len__') else entry.get('displayName', ''))
                                if not full_name and entry.get('fullName'):
                                    full_name = str(entry.get('fullName', [''])[0] if hasattr(entry.get('fullName', []), '__len__') else entry.get('fullName', ''))
                                if not full_name and entry.get('name'):
                                    full_name = str(entry.get('name', [''])[0] if hasattr(entry.get('name', []), '__len__') else entry.get('name', ''))
                                
                                return MDaemonUser(
                                    email=user_email,
                                    full_name=full_name,
                                    first_name=str(entry.get('givenName', [''])[0]) if entry.get('givenName') else None,
                                    last_name=str(entry.get('sn', [''])[0]) if entry.get('sn') else None
                                )
                        except Exception as e:
                            logger.debug(f"Поиск пользователя по фильтру {search_filter} не удался: {e}")
                            continue
                return None
            
            return await loop.run_in_executor(None, ldap_search)
            
        except ImportError:
            logger.error("Библиотека подключения не установлена. Установите: pip install ldap3")
            return None
        except Exception as e:
            logger.error(f"Ошибка подключения к Active Directory: {e}", exc_info=True)
            return None
    
    async def _get_all_users_ldap(self) -> List[MDaemonUser]:
        """Получает всех пользователей из Active Directory."""
        if not self.ldap_server:
            logger.debug("Сервер Active Directory не настроен")
            return []
        
        # Автопоиск Base DN, если не указан
        if not self.ldap_base_dn:
            logger.debug("Base DN не указан, выполняю автопоиск...")
            self.ldap_base_dn = await self._auto_discover_base_dn()
            if not self.ldap_base_dn:
                logger.warning("Не удалось определить Base DN. Укажите DOMAIN_BASE_DN в .env")
                return []
        
        try:
            from ldap3 import Server, Connection, ALL, SUBTREE
            import asyncio
            
            server = Server(self.ldap_server, port=self.ldap_port, get_info=ALL)
            loop = asyncio.get_event_loop()
            
            def ldap_search():
                users = []
                with Connection(server, self.ldap_bind_dn, self.ldap_bind_password, auto_bind=True) as conn:
                    # Фильтр для Active Directory и MDaemon
                    # Active Directory: objectClass=user, MDaemon: может быть любой objectClass
                    search_filters = [
                        "(&(mail=*)(objectClass=user))",  # AD: только пользователи с email
                        "(&(|(mail=*)(userPrincipalName=*))(objectClass=user))",  # AD: с mail или UPN
                        "(&(mail=*)(objectClass=*))",  # Общий фильтр
                    ]
                    
                    for search_filter in search_filters:
                        try:
                            conn.search(
                                search_base=self.ldap_base_dn,
                                search_filter=search_filter,
                                search_scope=SUBTREE,
                                attributes=['mail', 'userPrincipalName', 'emailAddress', 'cn', 'givenName', 'sn', 'displayName', 'name']
                            )
                            
                            if conn.entries:
                                break  # Нашли результаты, выходим
                        except Exception as e:
                            logger.debug(f"Поиск пользователя по фильтру {search_filter} не удался: {e}")
                            continue
                    
                    for entry in conn.entries:
                        # Извлекаем email из разных атрибутов
                        email = None
                        for attr in ['mail', 'userPrincipalName', 'emailAddress']:
                            attr_value = entry.get(attr)
                            if attr_value:
                                if isinstance(attr_value, list) and len(attr_value) > 0:
                                    email = str(attr_value[0])
                                elif attr_value:
                                    email = str(attr_value)
                                if email and '@' in email:
                                    break
                        
                        if email and '@' in email:
                            # Извлекаем ФИО
                            full_name = None
                            for attr in ['cn', 'displayName', 'name']:
                                attr_value = entry.get(attr)
                                if attr_value:
                                    if isinstance(attr_value, list) and len(attr_value) > 0:
                                        full_name = str(attr_value[0])
                                    elif attr_value:
                                        full_name = str(attr_value)
                                    if full_name:
                                        break
                            
                            users.append(MDaemonUser(
                                email=email,
                                full_name=full_name if full_name else None,
                                first_name=str(entry.get('givenName', [''])[0]) if entry.get('givenName') else None,
                                last_name=str(entry.get('sn', [''])[0]) if entry.get('sn') else None
                            ))
                
                return users
            
            return await loop.run_in_executor(None, ldap_search)
            
        except ImportError:
            logger.error("Библиотека подключения не установлена. Установите: pip install ldap3")
            return []
        except Exception as e:
            logger.error(f"Ошибка получения списка пользователей из Active Directory: {e}", exc_info=True)
            return []
    
    # Методы ODBC удалены - используем только LDAP для домена


# Глобальный экземпляр клиента
_mdaemon_client: Optional[MDaemonClient] = None


def get_mdaemon_client() -> Optional[MDaemonClient]:
    """Возвращает глобальный экземпляр MDaemon клиента."""
    global _mdaemon_client
    if _mdaemon_client is None:
        _mdaemon_client = MDaemonClient()
    return _mdaemon_client


async def sync_mdaemon_users_to_db():
    """Синхронизирует пользователей из Active Directory в БД бота."""
    from modules.handlers.monitor_db import get_db
    from assets.config import now_msk
    
    client = get_mdaemon_client()
    if not client:
        logger.warning("Active Directory client not configured")
        return {"total": 0, "added": 0, "updated": 0, "errors": 0}
    
    db = get_db()
    
    # Инициализируем таблицу ad_users, если её нет
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ad_users (
                email TEXT PRIMARY KEY,
                full_name TEXT,
                first_name TEXT,
                last_name TEXT,
                synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    
    try:
        users = await client.get_all_users()
        logger.info(f"Получено {len(users)} пользователей из Active Directory")
        
        added = 0
        updated = 0
        errors = 0
        
        for user in users:
            try:
                if not user.email:
                    continue
                
                # Проверяем, существует ли пользователь
                existing = db.execute_query(
                    "SELECT email FROM ad_users WHERE email = ?",
                    (user.email,)
                )
                
                if existing:
                    # Обновляем существующего пользователя
                    with db._get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE ad_users 
                            SET full_name = ?, 
                                first_name = ?, 
                                last_name = ?,
                                updated_at = ?
                            WHERE email = ?
                        """, (
                            user.full_name,
                            user.first_name,
                            user.last_name,
                            now_msk(),
                            user.email
                        ))
                        conn.commit()
                    updated += 1
                else:
                    # Добавляем нового пользователя
                    with db._get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO ad_users (email, full_name, first_name, last_name, synced_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            user.email,
                            user.full_name,
                            user.first_name,
                            user.last_name,
                            now_msk(),
                            now_msk()
                        ))
                        conn.commit()
                    added += 1
                    
            except Exception as e:
                logger.error(f"Ошибка при синхронизации пользователя {user.email}: {e}")
                errors += 1
        
        # Также обновляем full_name в otrs_users для авторизованных пользователей
        otrs_users = db.execute_query("SELECT otrs_email FROM otrs_users WHERE otrs_email IS NOT NULL")
        for otrs_user in otrs_users:
            email = otrs_user['otrs_email']
            ad_user = db.execute_query("SELECT full_name FROM ad_users WHERE email = ?", (email,))
            if ad_user and ad_user[0].get('full_name'):
                with db._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE otrs_users SET full_name = ? WHERE otrs_email = ?
                    """, (ad_user[0]['full_name'], email))
                    conn.commit()
        
        result = {
            "total": len(users),
            "added": added,
            "updated": updated,
            "errors": errors
        }
        
        logger.info(f"Синхронизация завершена: всего={result['total']}, добавлено={added}, обновлено={updated}, ошибок={errors}")
        return result
        
    except Exception as e:
        logger.error(f"Ошибка синхронизации пользователей из Active Directory: {e}", exc_info=True)
        return {"total": 0, "added": 0, "updated": 0, "errors": 1}

