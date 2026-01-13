# main/modules/web_admin.py

"""
Веб-панель администрирования бота.
- Авторизация по email + код на почту
- Настройки бота
- Только для агентов OTRS
"""

import asyncio
import logging
import os
import secrets
import threading
import bcrypt
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, Dict, Any

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_cors import CORS

from assets.config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, 
    SMTP_FROM_NAME, now_msk, MSK_TIMEZONE,
    PING_TOPIC_ID, BOT_TOPIC_ID, METRICS_TOPIC_ID, TASKS_TOPIC_ID
)
from modules.handlers.monitor_db import get_db
from modules.handlers.otrs_auth import (
    generate_code, is_valid_email, is_allowed_domain,
    send_verification_email, ALLOWED_EMAIL_DOMAINS
)
from modules.handlers.ip_manager import (
    load_ip_groups, save_ip_groups,
    add_group, delete_group, update_group_name,
    add_device, update_device, delete_device,
    validate_ip
)

logger = logging.getLogger(__name__)

# Создаём Flask app
app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), '..', 'templates'),
    static_folder=os.path.join(os.path.dirname(__file__), '..', 'static')
)
app.secret_key = secrets.token_hex(32)
# Бесконечная сессия (100 лет) - пользователь не будет разлогиниваться
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=36500)  # ~100 лет

CORS(app)

# Хранилище временных кодов для веб-авторизации
web_verification_codes: Dict[str, Dict[str, Any]] = {}

# Порт веб-сервера
WEB_ADMIN_PORT = 555


def login_required(f):
    """Декоратор для защиты маршрутов."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            return redirect(url_for('login'))
        # Обновляем сессию при каждом запросе - делаем её постоянной
        session.permanent = True
        return f(*args, **kwargs)
    return decorated_function


def check_agent_access(email: str) -> bool:
    """
    Проверяет, что пользователь является агентом OTRS.
    Для простоты считаем агентом любого с разрешённым доменом.
    В будущем можно добавить проверку через OTRS API.
    """
    if not is_allowed_domain(email):
        return False
    
    # Разрешаем доступ всем с правильным доменом
    # (в будущем можно добавить проверку через OTRS API)
    return True


# ============== ROUTES ==============

@app.route('/')
def index():
    """Главная страница - редирект на дашборд или логин."""
    if 'user_email' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Страница авторизации."""
    db = get_db()
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        login_method = request.form.get('login_method', 'password')  # 'password' или 'code'
        
        if not email:
            flash('Введите email', 'error')
            return render_template('login.html', has_password=False)
        
        if not is_valid_email(email):
            flash('Неверный формат email', 'error')
            return render_template('login.html', has_password=db.has_password(email), email=email)
        
        if not is_allowed_domain(email):
            allowed = ", ".join([f"@{d}" for d in ALLOWED_EMAIL_DOMAINS])
            flash(f'Разрешены только домены: {allowed}', 'error')
            return render_template('login.html', has_password=db.has_password(email), email=email)
        
        if not check_agent_access(email):
            flash('У вас нет доступа к панели управления', 'error')
            return render_template('login.html', has_password=db.has_password(email), email=email)
        
        # Проверяем, есть ли пароль
        has_password = db.has_password(email)
        web_user = db.get_web_user(email)
        
        # Если пароль установлен, по умолчанию используем вход по паролю
        # Если login_method='code', то пользователь явно выбрал код - продолжаем
        if has_password:
            # Если явно не выбран код, или метод не указан - используем пароль
            if login_method != 'code':
                # Вход по паролю
                if not password:
                    flash('Введите пароль', 'error')
                    return render_template('login.html', has_password=True, email=email)
                
                # Проверяем пароль
                if bcrypt.checkpw(password.encode('utf-8'), web_user['password_hash'].encode('utf-8')):
                    # Успешный вход по паролю
                    db.update_last_login(email)
                    session['user_email'] = email
                    session.permanent = True
                    logger.info(f"Web admin: user {email} logged in via password")
                    flash('Вы успешно авторизовались!', 'success')
                    return redirect(url_for('dashboard'))
                else:
                    flash('Неверный пароль', 'error')
                    return render_template('login.html', has_password=True, email=email)
            # else: login_method == 'code' - пользователь явно выбрал код, продолжаем
        
        # Вход по коду (если явно выбран или пароль не установлен)
        # Генерируем код
        code = generate_code()
        expires = datetime.now(MSK_TIMEZONE) + timedelta(minutes=10)
        
        web_verification_codes[email] = {
            'code': code,
            'expires': expires
        }
        
        # Отправляем код на почту
        asyncio.run(_send_code_async(email, code))
        
        session['pending_email'] = email
        return redirect(url_for('verify'))
    
    # GET запрос - показываем форму входа
    email_prefill = request.args.get('email', '').strip().lower()
    has_password = db.has_password(email_prefill) if email_prefill else False
    return render_template('login.html', has_password=has_password, email=email_prefill)


async def _send_code_async(email: str, code: str):
    """Асинхронная отправка кода."""
    try:
        await send_verification_email(email, code)
        logger.info(f"Web admin: verification code sent to {email}")
    except Exception as e:
        logger.error(f"Web admin: failed to send code to {email}: {e}")


@app.route('/verify', methods=['GET', 'POST'])
def verify():
    """Страница ввода кода верификации."""
    pending_email = session.get('pending_email')
    
    if not pending_email:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        
        if not code:
            flash('Введите код', 'error')
            return render_template('verify.html', email=pending_email)
        
        stored = web_verification_codes.get(pending_email)
        
        if not stored:
            flash('Код истёк. Запросите новый.', 'error')
            session.pop('pending_email', None)
            return redirect(url_for('login'))
        
        if datetime.now(MSK_TIMEZONE) > stored['expires']:
            flash('Код истёк. Запросите новый.', 'error')
            web_verification_codes.pop(pending_email, None)
            session.pop('pending_email', None)
            return redirect(url_for('login'))
        
        if code != stored['code']:
            flash('Неверный код', 'error')
            return render_template('verify.html', email=pending_email)
        
        # Успешная авторизация!
        web_verification_codes.pop(pending_email, None)
        session.pop('pending_email', None)
        session['user_email'] = pending_email
        session.permanent = True
        
        db = get_db()
        db.update_last_login(pending_email)
        
        # Создаём пользователя если его нет
        if not db.get_web_user(pending_email):
            db.create_web_user(pending_email)
        
        logger.info(f"Web admin: user {pending_email} logged in via code")
        
        # Проверяем, установлен ли пароль
        has_password = db.has_password(pending_email)
        
        if not has_password:
            # Предлагаем установить пароль
            flash('Вы успешно авторизовались! Установите пароль для более быстрого входа.', 'success')
            return redirect(url_for('set_password'))
        
        flash('Вы успешно авторизовались!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('verify.html', email=pending_email)


@app.route('/set-password', methods=['GET', 'POST'])
@login_required
def set_password():
    """Страница установки пароля."""
    db = get_db()
    email = session.get('user_email')
    
    if not email:
        return redirect(url_for('login'))
    
    # Проверяем, не установлен ли уже пароль
    if db.has_password(email):
        flash('Пароль уже установлен', 'info')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        password_confirm = request.form.get('password_confirm', '').strip()
        
        if not password:
            flash('Введите пароль', 'error')
            return render_template('set_password.html')
        
        if len(password) < 8:
            flash('Пароль должен быть не менее 8 символов', 'error')
            return render_template('set_password.html')
        
        if password != password_confirm:
            flash('Пароли не совпадают', 'error')
            return render_template('set_password.html')
        
        # Хэшируем пароль
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Сохраняем пароль
        db.set_web_password(email, password_hash)
        
        logger.info(f"Web admin: password set for {email}")
        flash('Пароль успешно установлен! Теперь вы можете входить по паролю.', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('set_password.html')


@app.route('/api/check-password', methods=['GET'])
def api_check_password():
    """API для проверки наличия пароля у пользователя."""
    email = request.args.get('email', '').strip().lower()
    
    if not email:
        return jsonify({'has_password': False}), 400
    
    db = get_db()
    has_password = db.has_password(email)
    
    return jsonify({'has_password': has_password})


@app.route('/resend-code', methods=['POST'])
def resend_code():
    """Повторная отправка кода."""
    pending_email = session.get('pending_email')
    
    if not pending_email:
        return jsonify({'success': False, 'message': 'Сессия истекла'}), 400
    
    code = generate_code()
    expires = datetime.now(MSK_TIMEZONE) + timedelta(minutes=10)
    
    web_verification_codes[pending_email] = {
        'code': code,
        'expires': expires
    }
    
    asyncio.run(_send_code_async(pending_email, code))
    
    return jsonify({'success': True, 'message': 'Код отправлен повторно'})


@app.route('/logout')
def logout():
    """Выход из системы."""
    email = session.get('user_email')
    session.clear()
    
    if email:
        logger.info(f"Web admin: user {email} logged out")
    
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    """Главная страница дашборда."""
    db = get_db()
    
    # Получаем статистику
    stats = {
        'total_users': 0,
        'total_tickets_today': 0,
        'total_tickets_week': 0,
        'servers_count': 0,
        'servers_online': 0,
        'servers_offline': 0,
    }
    
    # Пользователи OTRS
    try:
        users = db.execute_query("SELECT COUNT(*) as cnt FROM otrs_users")
        if users:
            stats['total_users'] = users[0]['cnt']
    except:
        pass
    
    # Заявки за сегодня
    try:
        today = now_msk().strftime('%Y-%m-%d')
        tickets_today = db.execute_query(
            "SELECT COUNT(*) as cnt FROM otrs_metrics WHERE date(action_time) = ?",
            (today,)
        )
        if tickets_today:
            stats['total_tickets_today'] = tickets_today[0]['cnt']
    except:
        pass
    
    # Заявки за неделю
    try:
        week_ago = (now_msk() - timedelta(days=7)).strftime('%Y-%m-%d')
        tickets_week = db.execute_query(
            "SELECT COUNT(*) as cnt FROM otrs_metrics WHERE date(action_time) >= ?",
            (week_ago,)
        )
        if tickets_week:
            stats['total_tickets_week'] = tickets_week[0]['cnt']
    except:
        pass
    
    # Серверы
    try:
        servers = db.execute_query("SELECT status FROM servers")
        if servers:
            stats['servers_count'] = len(servers)
            stats['servers_online'] = sum(1 for s in servers if s['status'] == 'online')
            stats['servers_offline'] = sum(1 for s in servers if s['status'] == 'offline')
    except:
        pass
    
    return render_template('dashboard.html', 
                          user_email=session['user_email'],
                          stats=stats)


@app.route('/settings')
@login_required
def settings():
    """Страница настроек бота."""
    # Текущие настройки
    current_settings = {
        'ping_topic_id': PING_TOPIC_ID,
        'bot_topic_id': BOT_TOPIC_ID,
        'metrics_topic_id': METRICS_TOPIC_ID,
        'tasks_topic_id': TASKS_TOPIC_ID,
        'smtp_host': SMTP_HOST,
        'smtp_port': SMTP_PORT,
        'smtp_user': SMTP_USER,
        'smtp_from_name': SMTP_FROM_NAME,
    }
    
    return render_template('settings.html',
                          user_email=session['user_email'],
                          settings=current_settings)


@app.route('/settings/save', methods=['POST'])
@login_required
def save_settings():
    """Сохранение настроек (пока заглушка)."""
    # TODO: Реализовать сохранение настроек в .env или БД
    flash('Настройки сохранены (требуется перезапуск бота)', 'success')
    logger.info(f"Web admin: settings updated by {session['user_email']}")
    return redirect(url_for('settings'))


@app.route('/users')
@login_required
def users():
    """Страница пользователей OTRS."""
    db = get_db()
    
    try:
        otrs_users = db.execute_query(
            "SELECT * FROM otrs_users ORDER BY verified_at DESC"
        )
    except:
        otrs_users = []
    
    return render_template('users.html',
                          user_email=session['user_email'],
                          users=otrs_users or [])


@app.route('/metrics')
@login_required
def metrics():
    """Страница метрик OTRS."""
    db = get_db()
    
    # Получаем метрики за последние 30 дней
    try:
        month_ago = (now_msk() - timedelta(days=30)).strftime('%Y-%m-%d')
        recent_metrics = db.execute_query(
            """SELECT * FROM otrs_metrics 
               WHERE date(action_time) >= ? 
               ORDER BY action_time DESC 
               LIMIT 100""",
            (month_ago,)
        )
    except:
        recent_metrics = []
    
    # Статистика по пользователям
    try:
        user_stats = db.execute_query(
            """SELECT user_id, user_name, action_type, COUNT(*) as cnt 
               FROM otrs_metrics 
               GROUP BY user_id, action_type 
               ORDER BY cnt DESC"""
        )
    except:
        user_stats = []
    
    return render_template('metrics.html',
                          user_email=session['user_email'],
                          recent_metrics=recent_metrics or [],
                          user_stats=user_stats or [])


@app.route('/servers')
@login_required
def servers():
    """Страница мониторинга серверов."""
    db = get_db()
    
    try:
        # Получаем серверы с их статусами из таблицы metrics
        # Если запись в metrics отсутствует - создаём её
        all_servers_raw = db.execute_query("""
            SELECT s.id, s.name, s.ip, s.server_group, m.server_id as metrics_exists
            FROM servers s
            LEFT JOIN metrics m ON s.id = m.server_id
        """)
        
        # Создаём записи в metrics для серверов без них
        for server_row in all_servers_raw:
            if not server_row.get('metrics_exists'):
                try:
                    db.execute_query(
                        "INSERT INTO metrics (server_id) VALUES (?)",
                        (server_row['id'],)
                    )
                except Exception as e:
                    logger.debug(f"Could not create metrics for server {server_row['id']}: {e}")
        
        # Теперь получаем все серверы со статусами
        all_servers = db.execute_query("""
            SELECT 
                s.id,
                s.name,
                s.ip,
                s.server_group as group_name,
                CASE 
                    WHEN m.last_status = 'UP' THEN 'online'
                    WHEN m.last_status = 'DOWN' THEN 'offline'
                    ELSE 'unknown'
                END as status,
                s.last_seen as last_check
            FROM servers s
            LEFT JOIN metrics m ON s.id = m.server_id
            ORDER BY 
                CASE 
                    WHEN m.last_status = 'UP' THEN 1
                    WHEN m.last_status = 'DOWN' THEN 2
                    ELSE 3
                END,
                s.server_group ASC,
                s.name ASC
        """)
        
        # Форматируем last_check для отображения
        for server in all_servers:
            if server.get('last_check'):
                try:
                    from datetime import datetime
                    from assets.config import MSK_TIMEZONE
                    if isinstance(server['last_check'], str):
                        dt = datetime.fromisoformat(server['last_check'])
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=MSK_TIMEZONE)
                        server['last_check'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    pass
    except Exception as e:
        logger.error(f"Error loading servers: {e}")
        all_servers = []
    
    return render_template('servers.html',
                          user_email=session['user_email'],
                          servers=all_servers or [])


@app.route('/api/stats')
@login_required
def api_stats():
    """API для получения статистики (для обновления в реальном времени)."""
    db = get_db()
    
    stats = {
        'servers_online': 0,
        'servers_offline': 0,
        'tickets_today': 0,
        'active_users': 0,
    }
    
    try:
        # Получаем статусы из metrics
        servers = db.execute_query("""
            SELECT 
                CASE 
                    WHEN m.last_status = 'UP' THEN 'online'
                    WHEN m.last_status = 'DOWN' THEN 'offline'
                    ELSE 'unknown'
                END as status
            FROM servers s
            LEFT JOIN metrics m ON s.id = m.server_id
        """)
        if servers:
            stats['servers_online'] = sum(1 for s in servers if s.get('status') == 'online')
            stats['servers_offline'] = sum(1 for s in servers if s.get('status') == 'offline')
        
        today = now_msk().strftime('%Y-%m-%d')
        tickets = db.execute_query(
            "SELECT COUNT(*) as cnt FROM otrs_metrics WHERE date(action_time) = ?",
            (today,)
        )
        if tickets:
            stats['tickets_today'] = tickets[0]['cnt']
        
        users = db.execute_query("SELECT COUNT(*) as cnt FROM otrs_users")
        if users:
            stats['active_users'] = users[0]['cnt']
    except:
        pass
    
    return jsonify(stats)


@app.route('/ip-addresses')
@login_required
def ip_addresses():
    """Страница управления IP-адресами."""
    groups = load_ip_groups()
    return render_template('ip_addresses.html',
                          user_email=session['user_email'],
                          groups=groups)


@app.route('/api/ip-groups', methods=['GET'])
@login_required
def api_get_ip_groups():
    """API: Получить все группы IP-адресов."""
    try:
        groups = load_ip_groups()
        return jsonify({'success': True, 'groups': groups})
    except Exception as e:
        logger.error(f"Error loading IP groups: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ip-groups/add', methods=['POST'])
@login_required
def api_add_group():
    """API: Добавить новую группу."""
    data = request.get_json()
    group_name = data.get('name', '').strip()
    
    if not group_name:
        return jsonify({'success': False, 'error': 'Имя группы обязательно'}), 400
    
    success, error = add_group(group_name)
    
    if success:
        logger.info(f"IP group '{group_name}' added by {session['user_email']}")
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': error}), 400


@app.route('/api/ip-groups/update', methods=['POST'])
@login_required
def api_update_group():
    """API: Обновить имя группы."""
    data = request.get_json()
    old_name = data.get('old_name', '').strip()
    new_name = data.get('new_name', '').strip()
    
    if not old_name or not new_name:
        return jsonify({'success': False, 'error': 'Имена группы обязательны'}), 400
    
    success, error = update_group_name(old_name, new_name)
    
    if success:
        logger.info(f"IP group '{old_name}' renamed to '{new_name}' by {session['user_email']}")
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': error}), 400


@app.route('/api/ip-groups/delete', methods=['POST'])
@login_required
def api_delete_group():
    """API: Удалить группу."""
    data = request.get_json()
    group_name = data.get('name', '').strip()
    
    if not group_name:
        return jsonify({'success': False, 'error': 'Имя группы обязательно'}), 400
    
    success, error = delete_group(group_name)
    
    if success:
        logger.info(f"IP group '{group_name}' deleted by {session['user_email']}")
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': error}), 400


@app.route('/api/ip-devices/add', methods=['POST'])
@login_required
def api_add_device():
    """API: Добавить устройство в группу."""
    data = request.get_json()
    group_name = data.get('group_name', '').strip()
    device_name = data.get('name', '').strip()
    device_ip = data.get('ip', '').strip()
    
    if not group_name or not device_name or not device_ip:
        return jsonify({'success': False, 'error': 'Все поля обязательны'}), 400
    
    success, error = add_device(group_name, device_name, device_ip)
    
    if success:
        logger.info(f"Device '{device_name}' ({device_ip}) added to group '{group_name}' by {session['user_email']}")
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': error}), 400


@app.route('/api/ip-devices/update', methods=['POST'])
@login_required
def api_update_device():
    """API: Обновить устройство."""
    data = request.get_json()
    group_name = data.get('group_name', '').strip()
    old_name = data.get('old_name', '').strip()
    new_name = data.get('new_name', '').strip()
    new_ip = data.get('ip', '').strip()
    
    if not group_name or not old_name or not new_name or not new_ip:
        return jsonify({'success': False, 'error': 'Все поля обязательны'}), 400
    
    success, error = update_device(group_name, old_name, new_name, new_ip)
    
    if success:
        logger.info(f"Device '{old_name}' updated to '{new_name}' ({new_ip}) in group '{group_name}' by {session['user_email']}")
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': error}), 400


@app.route('/api/ip-devices/delete', methods=['POST'])
@login_required
def api_delete_device():
    """API: Удалить устройство."""
    data = request.get_json()
    group_name = data.get('group_name', '').strip()
    device_name = data.get('name', '').strip()
    
    if not group_name or not device_name:
        return jsonify({'success': False, 'error': 'Имя группы и устройства обязательны'}), 400
    
    success, error = delete_device(group_name, device_name)
    
    if success:
        logger.info(f"Device '{device_name}' deleted from group '{group_name}' by {session['user_email']}")
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': error}), 400


# ============== ЗАПУСК ==============

def run_web_admin():
    """Запускает веб-сервер в отдельном потоке."""
    # Отключаем логи werkzeug (Flask) для чистоты консоли
    werkzeug_log = logging.getLogger('werkzeug')
    werkzeug_log.setLevel(logging.WARNING)
    
    logger.info(f"Starting web admin panel on http://localhost:{WEB_ADMIN_PORT}")
    
    app.run(
        host='0.0.0.0',
        port=WEB_ADMIN_PORT,
        debug=False,
        use_reloader=False,
        threaded=True
    )


def start_web_admin_thread():
    """Запускает веб-сервер в фоновом потоке."""
    web_thread = threading.Thread(target=run_web_admin, daemon=True)
    web_thread.start()
    logger.info(f"Web admin panel started in background thread")
    return web_thread

