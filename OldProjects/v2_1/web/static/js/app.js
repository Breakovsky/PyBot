// TBot v2.1 Admin Panel - JavaScript

const API_BASE = '/api/v1';
let currentUser = null;
let authToken = null;

// Инициализация
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
    setupEventListeners();
});

// Проверка авторизации
function checkAuth() {
    const token = localStorage.getItem('auth_token');
    if (token) {
        authToken = token;
        fetchCurrentUser();
    } else {
        showLoginPage();
    }
}

// Получение текущего пользователя
async function fetchCurrentUser() {
    try {
        const response = await fetch(`${API_BASE}/auth/me`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            currentUser = await response.json();
            showMainInterface();
            loadDashboard();
        } else {
            localStorage.removeItem('auth_token');
            authToken = null;
            showLoginPage();
        }
    } catch (error) {
        console.error('Error fetching user:', error);
        showLoginPage();
    }
}

// Показ страницы входа
function showLoginPage() {
    document.getElementById('loginPage').classList.remove('hidden');
    document.getElementById('dashboardPage').classList.add('hidden');
    document.getElementById('employeesPage').classList.add('hidden');
    document.getElementById('settingsPage').classList.add('hidden');
}

// Показ основного интерфейса
function showMainInterface() {
    document.getElementById('loginPage').classList.add('hidden');
    document.getElementById('dashboardPage').classList.remove('hidden');
}

// Настройка обработчиков событий
function setupEventListeners() {
    // Форма входа
    document.getElementById('loginForm').addEventListener('submit', handleLogin);

    // Навигация
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const target = e.target.getAttribute('href');
            if (target === '#logout') {
                handleLogout();
            } else {
                navigateTo(target.substring(1));
            }
        });
    });

    // Кнопка добавления сотрудника
    document.getElementById('addEmployeeBtn')?.addEventListener('click', () => {
        addNewEmployeeRow();
    });
    
    // Кнопка создания бэкапа
    document.getElementById('backupBtn')?.addEventListener('click', async () => {
        await createBackup('manual');
        alert('Бэкап создан успешно!');
    });
    
    // Кнопка восстановления из бэкапа
    document.getElementById('restoreBtn')?.addEventListener('click', () => {
        showRestoreModal();
    });

    // Кнопка истории версий
    document.getElementById('versionHistoryBtn')?.addEventListener('click', () => {
        showVersionHistory();
    });
    
    // Закрытие модального окна истории версий
    document.getElementById('closeVersionHistory')?.addEventListener('click', () => {
        document.getElementById('versionHistoryModal').classList.add('hidden');
    });
    
    // Закрытие модального окна сравнения версий
    document.getElementById('closeVersionCompare')?.addEventListener('click', () => {
        document.getElementById('versionCompareModal').classList.add('hidden');
    });

    // Поиск сотрудников
    document.getElementById('searchBtn')?.addEventListener('click', searchEmployees);
    document.getElementById('refreshBtn')?.addEventListener('click', () => {
        document.getElementById('employeeSearch').value = '';
        loadEmployees();
    });
    document.getElementById('employeeSearch')?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            searchEmployees();
        }
    });

    // Модальное окно
    document.querySelector('.close')?.addEventListener('click', closeEmployeeModal);
    document.getElementById('cancelBtn')?.addEventListener('click', closeEmployeeModal);
    document.getElementById('employeeForm')?.addEventListener('submit', saveEmployeeForm);
}

// Вход
async function handleLogin(e) {
    e.preventDefault();
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    const errorDiv = document.getElementById('loginError');

    try {
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ email, password })
        });

        const data = await response.json();

        if (response.ok) {
            authToken = data.access_token;
            localStorage.setItem('auth_token', authToken);
            currentUser = data.user;
            showMainInterface();
            loadDashboard();
            errorDiv.textContent = '';
        } else {
            errorDiv.textContent = data.detail || 'Ошибка входа';
        }
    } catch (error) {
        errorDiv.textContent = 'Ошибка подключения к серверу';
        console.error('Login error:', error);
    }
}

// Выход
function handleLogout() {
    localStorage.removeItem('auth_token');
    authToken = null;
    currentUser = null;
    showLoginPage();
}

// Навигация
function navigateTo(page) {
    // Скрываем все страницы
    document.querySelectorAll('.page').forEach(p => {
        if (!p.id.includes('login')) {
            p.classList.add('hidden');
        }
    });

    // Показываем нужную страницу
    const targetPage = document.getElementById(`${page}Page`);
    if (targetPage) {
        targetPage.classList.remove('hidden');
    }

    // Обновляем активную ссылку
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.remove('active');
        if (link.getAttribute('href') === `#${page}`) {
            link.classList.add('active');
        }
    });

    // Загружаем данные для страницы
    if (page === 'dashboard') {
        loadDashboard();
    } else if (page === 'employees') {
        loadEmployees();
    } else if (page === 'settings') {
        loadSettings();
    }
}

// Загрузка дашборда
async function loadDashboard() {
    try {
        const response = await fetch(`${API_BASE}/dashboard/stats`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const stats = await response.json();
            document.getElementById('employeesCount').textContent = stats.employees_count;
            document.getElementById('departmentsCount').textContent = stats.departments_count;
            document.getElementById('workstationsCount').textContent = stats.workstations_count;
            document.getElementById('telegramUsersCount').textContent = stats.telegram_users_count;
        }
    } catch (error) {
        console.error('Error loading dashboard:', error);
    }
}

// Загрузка сотрудников
async function loadEmployees(searchQuery = '') {
    const tbody = document.getElementById('employeesTableBody');
    tbody.innerHTML = '<tr><td colspan="7" class="loading">Загрузка...</td></tr>';

    try {
        // Загружаем списки отделов и рабочих станций при первой загрузке
        if (departmentsList.length === 0 || workstationsList.length === 0) {
            await loadLists();
        }

        const url = searchQuery 
            ? `${API_BASE}/employees?search=${encodeURIComponent(searchQuery)}`
            : `${API_BASE}/employees?limit=1000`; // Загружаем больше данных для таблицы
        
        const response = await fetch(url, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const employees = await response.json();
            renderEmployees(employees);
        } else {
            tbody.innerHTML = '<tr><td colspan="7">Ошибка загрузки данных</td></tr>';
        }
    } catch (error) {
        console.error('Error loading employees:', error);
        tbody.innerHTML = '<tr><td colspan="7">Ошибка подключения</td></tr>';
    }
}

// Глобальные переменные для таблицы
let departmentsList = [];
let workstationsList = [];
let employeesData = new Map(); // Кэш данных сотрудников
let currentSort = { field: 'id', direction: 'asc' }; // Текущая сортировка по умолчанию - ID ASC
let saveCount = 0; // Счётчик сохранений для бэкапов

// Загрузка списков отделов и рабочих станций
async function loadLists() {
    try {
        // Загружаем отделы
        const deptResponse = await fetch(`${API_BASE}/employees/departments/list`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        if (deptResponse.ok) {
            departmentsList = await deptResponse.json();
        }

        // Загружаем рабочие станции
        const wsResponse = await fetch(`${API_BASE}/employees/workstations/list`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        if (wsResponse.ok) {
            workstationsList = await wsResponse.json();
        }
    } catch (error) {
        console.error('Error loading lists:', error);
    }
}

// Отображение сотрудников в редактируемой таблице
function renderEmployees(employees) {
    const tbody = document.getElementById('employeesTableBody');
    
    if (employees.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 2rem;">Нет данных. Нажмите "+ Добавить строку" для создания новой записи.</td></tr>';
        return;
    }

    // Сохраняем данные в кэш
    employees.forEach(emp => employeesData.set(emp.id, emp));
    
    // Сортируем по умолчанию по ID ASC
    if (currentSort.field === 'id' && currentSort.direction === 'asc') {
        employees.sort((a, b) => (a.id || 0) - (b.id || 0));
    }

    tbody.innerHTML = employees.map(emp => `
        <tr data-id="${emp.id}">
            <td class="cell-id">${emp.id}</td>
            <td class="editable-cell" data-field="full_name" data-required="true">
                <div class="cell-content">${escapeHtml(emp.full_name || '')}</div>
            </td>
            <td class="editable-cell" data-field="workstation_name">
                <div class="cell-content">${escapeHtml(emp.workstation_name || '')}</div>
            </td>
            <td class="editable-cell" data-field="department_name">
                <div class="cell-content">${escapeHtml(emp.department_name || '')}</div>
            </td>
            <td class="editable-cell" data-field="phone">
                <div class="cell-content">${escapeHtml(emp.phone || '')}</div>
            </td>
            <td class="editable-cell" data-field="email">
                <div class="cell-content">${escapeHtml(emp.email || '')}</div>
            </td>
            <td class="row-actions">
                <button class="btn-icon delete" onclick="deleteEmployee(${emp.id}, this)" title="Удалить">🗑️</button>
            </td>
        </tr>
    `).join('');

    // Настраиваем редактирование ячеек
    setupCellEditing();
    
    // Настраиваем сортировку
    setupSorting();
    // Устанавливаем начальную сортировку по ID
    const idHeader = document.querySelector('.sortable-table th[data-sort="id"]');
    if (idHeader) {
        idHeader.classList.add('sorted-asc');
        const icon = idHeader.querySelector('.sort-icon');
        if (icon) icon.textContent = '↑';
    }
}

// Настройка сортировки по столбцам
let sortingHandlersAttached = false;

function setupSorting() {
    // Добавляем обработчики только один раз
    if (sortingHandlersAttached) return;
    
    document.querySelectorAll('.sortable-table th.sortable').forEach(header => {
        header.addEventListener('click', (e) => {
            const field = header.dataset.sort;
            if (!field) return;
            
            // Определяем направление сортировки
            if (currentSort.field === field) {
                // Переключаем направление
                currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
            } else {
                // Новая сортировка
                currentSort.field = field;
                currentSort.direction = 'asc';
            }
            
            // Обновляем визуальные индикаторы
            document.querySelectorAll('.sortable-table th.sortable').forEach(th => {
                th.classList.remove('sorted-asc', 'sorted-desc');
                const icon = th.querySelector('.sort-icon');
                if (icon) icon.textContent = '⇅';
            });
            
            header.classList.add(`sorted-${currentSort.direction}`);
            const icon = header.querySelector('.sort-icon');
            if (icon) icon.textContent = currentSort.direction === 'asc' ? '↑' : '↓';
            
            // Применяем сортировку
            sortEmployees(currentSort.field, currentSort.direction);
        });
    });
    
    sortingHandlersAttached = true;
}

// Сортировка сотрудников
function sortEmployees(field, direction) {
    const tbody = document.getElementById('employeesTableBody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    
    if (rows.length === 0) return;
    
    rows.sort((a, b) => {
        const aId = a.dataset.id || '';
        const bId = b.dataset.id || '';
        
        // Пропускаем новые строки
        if ((aId && aId.startsWith('temp-')) || (bId && bId.startsWith('temp-'))) {
            return 0;
        }
        
        // Пропускаем строки без ID
        if (!aId || !bId) return 0;
        
        const aData = employeesData.get(parseInt(aId));
        const bData = employeesData.get(parseInt(bId));
        
        if (!aData || !bData) return 0;
        
        let aValue = aData[field];
        let bValue = bData[field];
        
        // Обработка null/undefined
        if (aValue === null || aValue === undefined) aValue = '';
        if (bValue === null || bValue === undefined) bValue = '';
        
        // Сравнение для чисел (ID)
        if (field === 'id') {
            const aNum = parseInt(aValue) || 0;
            const bNum = parseInt(bValue) || 0;
            return direction === 'asc' ? aNum - bNum : bNum - aNum;
        }
        
        // Сравнение строк
        const aStr = String(aValue).toLowerCase();
        const bStr = String(bValue).toLowerCase();
        
        let comparison = 0;
        if (aStr < bStr) comparison = -1;
        else if (aStr > bStr) comparison = 1;
        
        return direction === 'asc' ? comparison : -comparison;
    });
    
    // Переставляем строки
    rows.forEach(row => tbody.appendChild(row));
}

// Экранирование HTML
function escapeHtml(text) {
    if (text === null || text === undefined) {
        return '';
    }
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

// Настройка редактирования ячеек
let cellEditingHandlersAttached = new Set();

function setupCellEditing() {
    // Удаляем старые обработчики, чтобы избежать дублирования
    document.querySelectorAll('.editable-cell .cell-content').forEach(cell => {
        // Используем data-атрибут для отслеживания
        if (!cell.dataset.editingHandlerAttached) {
        cell.addEventListener('click', (e) => {
            e.stopPropagation();
            startEditing(cell);
        });
            cell.dataset.editingHandlerAttached = 'true';
        }
    });
}

// Начало редактирования ячейки
function startEditing(cellContent) {
    const cell = cellContent.closest('.editable-cell');
    const row = cell.closest('tr');
    const rowId = row.dataset.id || '';
    const isNewRow = row.classList.contains('new-row') || (rowId && rowId.startsWith('temp-'));
    const employeeId = isNewRow ? null : parseInt(rowId);
    const field = cell.dataset.field;
    const fieldType = cell.dataset.type || 'text';
    const isRequired = cell.dataset.required === 'true';
    
    const currentValue = cellContent.textContent.trim();
    let input;

    // Все поля теперь текстовые
        input = document.createElement('input');
        input.type = field === 'email' ? 'email' : 'text';
        input.className = 'cell-input';
        input.value = currentValue;
        if (isRequired) {
            input.required = true;
    }

    cellContent.classList.add('editing');
    cellContent.innerHTML = '';
    cellContent.appendChild(input);
    input.focus();
    
    // Выделяем весь текст при редактировании (как в Excel)
    if (input.tagName === 'INPUT') {
        input.select();
    }

    // Сохранение при потере фокуса
    input.addEventListener('blur', () => {
        const value = input.value;
        saveCell(cell, employeeId || rowId, field, value);
    });
    
    // Сохранение по Enter
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            input.blur();
        }
        if (e.key === 'Escape') {
            e.preventDefault();
            cancelEditing(cell, currentValue);
        }
    });
}

// Сохранение ячейки
async function saveCell(cell, employeeId, field, newValue) {
    const row = cell.closest('tr');
    const isNewRow = row.classList.contains('new-row') || row.dataset.id.startsWith('temp-');
    
    // Для новых строк - сохраняем всю строку
    if (isNewRow) {
        await saveNewRow(row);
        return;
    }
    
    // Для существующих строк - сохраняем только изменённую ячейку
    const oldData = employeesData.get(employeeId);
    let oldValue = oldData?.[field] || '';
        newValue = newValue.trim();
    
        if (oldValue === newValue) {
            cancelEditing(cell, oldValue);
            return;
    }

    // Показываем индикатор сохранения
    const indicator = document.createElement('span');
    indicator.className = 'saving-indicator';
    indicator.textContent = '💾';
    cell.appendChild(indicator);

    try {
        // Подготавливаем данные для обновления
        const updateData = {};
            updateData[field] = newValue || null;

        const response = await fetch(`${API_BASE}/employees/${employeeId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify(updateData)
        });

        if (response.ok) {
            const updated = await response.json();
            employeesData.set(employeeId, updated);
            
            // Обновляем отображение
            cell.innerHTML = `<div class="cell-content">${escapeHtml(newValue || '')}</div>`;
            
            // Показываем индикатор успеха
            const successIndicator = document.createElement('span');
            successIndicator.className = 'saved-indicator';
            successIndicator.textContent = '✓';
            cell.appendChild(successIndicator);
            
            setTimeout(() => {
                successIndicator.remove();
                setupCellEditing(); // Переинициализируем обработчики
            }, 1000);
            
            // Увеличиваем счётчик сохранений и проверяем бэкап
            saveCount++;
            if (saveCount >= 5) {
                await createBackup('auto');
                saveCount = 0;
            }
        } else {
            const error = await response.json();
            throw new Error(error.detail || 'Ошибка сохранения');
        }
    } catch (error) {
        console.error('Error saving cell:', error);
        
        // Показываем индикатор ошибки
        indicator.className = 'error-indicator';
        indicator.textContent = '✗';
        
        // Восстанавливаем старое значение
        cell.innerHTML = `<div class="cell-content">${escapeHtml(oldValue || '')}</div>`;
        
        setTimeout(() => {
            indicator.remove();
            setupCellEditing();
        }, 2000);
        
        alert('Ошибка сохранения: ' + error.message);
    }
}

// Отмена редактирования
function cancelEditing(cell, oldValue) {
    const cellContent = cell.querySelector('.cell-input, .cell-select');
    if (cellContent) {
        cell.innerHTML = `<div class="cell-content">${escapeHtml(oldValue || '')}</div>`;
        setupCellEditing();
    }
}

// Поиск сотрудников
function searchEmployees() {
    const query = document.getElementById('employeeSearch').value;
    loadEmployees(query);
}

// Открытие модального окна для сотрудника
async function openEmployeeModal(employeeId = null) {
    const modal = document.getElementById('employeeModal');
    const form = document.getElementById('employeeForm');
    const title = document.getElementById('modalTitle');

    // Загружаем списки отделов и рабочих станций
    await loadDepartments();
    await loadWorkstations();

    if (employeeId) {
        title.textContent = 'Редактировать сотрудника';
        await loadEmployee(employeeId);
    } else {
        title.textContent = 'Добавить сотрудника';
        form.reset();
        document.getElementById('employeeId').value = '';
    }

    modal.classList.remove('hidden');
}

// Закрытие модального окна
function closeEmployeeModal() {
    document.getElementById('employeeModal').classList.add('hidden');
}

// Загрузка отделов
async function loadDepartments() {
    try {
        const response = await fetch(`${API_BASE}/employees/departments/list`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const departments = await response.json();
            const select = document.getElementById('department');
            select.innerHTML = '<option value="">Не выбрано</option>' +
                departments.map(d => `<option value="${d.id}">${d.name}</option>`).join('');
        }
    } catch (error) {
        console.error('Error loading departments:', error);
    }
}

// Загрузка рабочих станций
async function loadWorkstations() {
    try {
        const response = await fetch(`${API_BASE}/employees/workstations/list`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const workstations = await response.json();
            const select = document.getElementById('workstation');
            select.innerHTML = '<option value="">Не выбрано</option>' +
                workstations.map(w => `<option value="${w.id}">${w.name}</option>`).join('');
        }
    } catch (error) {
        console.error('Error loading workstations:', error);
    }
}

// Загрузка сотрудника
async function loadEmployee(employeeId) {
    try {
        const response = await fetch(`${API_BASE}/employees/${employeeId}`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const emp = await response.json();
            document.getElementById('employeeId').value = emp.id;
            document.getElementById('fullName').value = emp.full_name;
            document.getElementById('workstation').value = emp.workstation_name || '';
            document.getElementById('department').value = emp.department_name || '';
            document.getElementById('phone').value = emp.phone || '';
            document.getElementById('employeeEmail').value = emp.email || '';
        }
    } catch (error) {
        console.error('Error loading employee:', error);
        alert('Ошибка загрузки данных сотрудника');
    }
}

// Сохранение формы сотрудника (если используется модальное окно)
async function saveEmployeeForm(e) {
    if (e) e.preventDefault();
    
    const employeeId = document.getElementById('employeeId')?.value;
    const fullName = document.getElementById('fullName')?.value;
    const workstation = document.getElementById('workstation')?.value;
    const department = document.getElementById('department')?.value;
    const phone = document.getElementById('phone')?.value;
    const email = document.getElementById('employeeEmail')?.value;
    
    if (!fullName) {
        alert('Пожалуйста, введите ФИО сотрудника');
        return;
    }
    
    try {
        const url = employeeId 
            ? `${API_BASE}/employees/${employeeId}`
            : `${API_BASE}/employees`;
        const method = employeeId ? 'PUT' : 'POST';
        
        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                full_name: fullName,
                workstation_name: workstation || null,
                department_name: department || null,
                phone: phone || null,
                email: email || null
            })
        });
        
        if (response.ok) {
            closeEmployeeModal();
            await loadEmployees();
        } else {
            const error = await response.json();
            alert(error.detail || 'Ошибка сохранения');
        }
    } catch (error) {
        console.error('Error saving employee:', error);
        alert('Ошибка подключения к серверу');
    }
}

// Старые функции модального окна оставлены для совместимости, но не используются

// Добавление новой строки
async function addNewEmployeeRow() {
    const tbody = document.getElementById('employeesTableBody');
    
    // Убираем сообщение "Нет данных"
    if (tbody.querySelector('td[colspan]')) {
        tbody.innerHTML = '';
    }
    
    // Загружаем списки, если ещё не загружены
    if (departmentsList.length === 0 || workstationsList.length === 0) {
        await loadLists();
    }
    
    // Создаём временную строку с временным ID
    const tempId = Date.now();
    const newRow = document.createElement('tr');
    newRow.className = 'new-row';
    newRow.dataset.id = `temp-${tempId}`;
    newRow.innerHTML = `
        <td class="cell-id">новый</td>
        <td class="editable-cell" data-field="full_name" data-required="true">
            <div class="cell-content"></div>
        </td>
        <td class="editable-cell" data-field="workstation_name">
            <div class="cell-content"></div>
        </td>
        <td class="editable-cell" data-field="department_name">
            <div class="cell-content"></div>
        </td>
        <td class="editable-cell" data-field="phone">
            <div class="cell-content"></div>
        </td>
        <td class="editable-cell" data-field="email">
            <div class="cell-content"></div>
        </td>
        <td class="row-actions">
            <button class="btn-icon delete" onclick="deleteEmployeeRow(this)" title="Отмена">✖</button>
        </td>
    `;
    
    tbody.insertBefore(newRow, tbody.firstChild);
    
    // Настраиваем редактирование
    setupCellEditing();
    
    // Начинаем редактирование ФИО
    const nameCell = newRow.querySelector('[data-field="full_name"] .cell-content');
    nameCell.click();
    
    // Больше не нужно - сохранение будет при потере фокуса через saveCell
}

// Сохранение новой строки
async function saveNewRow(row) {
    const fullNameCell = row.querySelector('[data-field="full_name"] .cell-content');
    const fullName = fullNameCell.textContent.trim();
    
    if (!fullName) {
        alert('ФИО обязательно для заполнения');
        return;
    }
    
    // Собираем данные из ячеек
    const workstationCell = row.querySelector('[data-field="workstation_name"] .cell-content');
    const departmentCell = row.querySelector('[data-field="department_name"] .cell-content');
    const phoneCell = row.querySelector('[data-field="phone"] .cell-content');
    const emailCell = row.querySelector('[data-field="email"] .cell-content');
    
    // Получаем текстовые значения
    const workstationName = workstationCell ? workstationCell.textContent.trim() : '';
    const departmentName = departmentCell ? departmentCell.textContent.trim() : '';
    
    const data = {
        full_name: fullName,
        workstation_name: workstationName,
        department_name: departmentName,
        phone: phoneCell?.textContent?.trim() || null,
        email: emailCell?.textContent?.trim() || null
    };
    
    try {
        const response = await fetch(`${API_BASE}/employees`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify(data)
        });
        
        if (response.ok) {
            const newEmployee = await response.json();
            employeesData.set(newEmployee.id, newEmployee);
            row.dataset.id = newEmployee.id;
            row.classList.remove('new-row');
            row.querySelector('.cell-id').textContent = newEmployee.id;
            
            // Обновляем кнопку удаления
            const deleteBtn = row.querySelector('.delete');
            deleteBtn.onclick = () => deleteEmployee(newEmployee.id, deleteBtn);
            deleteBtn.title = 'Удалить';
            deleteBtn.textContent = '🗑️';
            
            // Перезагружаем таблицу для синхронизации данных
            await loadEmployees();
        } else {
            const error = await response.json();
            throw new Error(error.detail || 'Ошибка создания');
        }
    } catch (error) {
        console.error('Error creating employee:', error);
        alert('Ошибка создания сотрудника: ' + error.message);
    }
}

// Получение ID по имени из списка
function getSelectValueByName(name, list) {
    if (!name) return null;
    const item = list.find(item => item.name === name);
    return item ? item.id : null;
}

// Удаление строки без сохранения
function deleteEmployeeRow(button) {
    const row = button.closest('tr');
    row.remove();
    
    // Если таблица пустая, показываем сообщение
    const tbody = document.getElementById('employeesTableBody');
    if (tbody.children.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 2rem;">Нет данных. Нажмите "+ Добавить строку" для создания новой записи.</td></tr>';
    }
}

// Удаление сотрудника
async function deleteEmployee(employeeId, button) {
    if (!confirm('Вы уверены, что хотите удалить этого сотрудника?')) {
        return;
    }

    const row = button.closest('tr');
    
    try {
        const response = await fetch(`${API_BASE}/employees/${employeeId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok || response.status === 204) {
            employeesData.delete(employeeId);
            row.remove();
            
            // Если таблица пустая, показываем сообщение
            const tbody = document.getElementById('employeesTableBody');
            if (tbody.children.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 2rem;">Нет данных. Нажмите "+ Добавить строку" для создания новой записи.</td></tr>';
            }
        } else {
            let errorMessage = 'Ошибка удаления';
            try {
                const errorText = await response.text();
                if (errorText) {
                    try {
                        const error = JSON.parse(errorText);
                        errorMessage = error.detail || error.message || errorMessage;
                    } catch {
                        errorMessage = errorText || errorMessage;
                    }
                }
            } catch (e) {
                console.error('Error parsing error response:', e);
            }
            alert(errorMessage);
        }
    } catch (error) {
        console.error('Error deleting employee:', error);
        let errorMessage = 'Ошибка удаления сотрудника';
        if (error.message) {
            errorMessage += ': ' + error.message;
        }
        alert(errorMessage);
    }
}

// Создание бэкапа
async function createBackup(type = 'auto') {
    try {
        const snapshotName = type === 'auto' 
            ? `auto_backup_${new Date().toISOString().replace(/[:.]/g, '-')}`
            : `manual_backup_${new Date().toISOString().replace(/[:.]/g, '-')}`;
        
        const response = await fetch(`${API_BASE}/employees/snapshots?snapshot_name=${encodeURIComponent(snapshotName)}`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`,
                'Content-Type': 'application/json'
            }
        });
        
        if (response.ok) {
            const result = await response.json();
            console.log(`Бэкап создан: ${result.snapshot_name} (${result.employees_count || 0} сотрудников)`);
            return result;
        } else {
            const errorText = await response.text();
            console.error('Ошибка создания бэкапа:', response.status, errorText);
            let errorMessage = 'Ошибка создания бэкапа';
            try {
                const errorJson = JSON.parse(errorText);
                errorMessage += ': ' + (errorJson.detail || errorText);
            } catch {
                errorMessage += ` (${response.status}): ${errorText}`;
            }
            alert(errorMessage);
            return null;
        }
    } catch (error) {
        console.error('Ошибка создания бэкапа:', error);
        alert('Ошибка создания бэкапа: ' + error.message);
        return null;
    }
}

// Показать модальное окно восстановления
async function showRestoreModal() {
    try {
        const response = await fetch(`${API_BASE}/employees/snapshots`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error('Error loading snapshots:', response.status, errorText);
            let errorMessage = 'Ошибка загрузки списка бэкапов';
            try {
                const errorJson = JSON.parse(errorText);
                const detail = errorJson.detail || errorJson.message || JSON.stringify(errorJson);
                errorMessage += ': ' + (typeof detail === 'string' ? detail : JSON.stringify(detail));
            } catch (e) {
                errorMessage += ` (${response.status}): ${errorText}`;
            }
            alert(errorMessage);
            return;
        }
        
        const snapshots = await response.json();
        
        if (!Array.isArray(snapshots)) {
            console.error('Invalid snapshots response:', snapshots);
            alert('Ошибка: получен неверный формат данных');
            return;
        }
        
        if (snapshots.length === 0) {
            alert('Нет доступных бэкапов');
            return;
        }
        
        // Форматируем дату безопасно
        const formatDate = (dateStr) => {
            if (!dateStr) return 'N/A';
            try {
                const date = new Date(dateStr);
                return date.toLocaleString('ru-RU', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit'
                });
            } catch {
                return dateStr.substring(0, 19) || dateStr;
            }
        };
        
        const snapshotList = snapshots.map(s => 
            `<option value="${s.id}">${s.snapshot_name} (${formatDate(s.created_at)}) - ${s.snapshot_type || 'manual'}</option>`
        ).join('');
        
        const snapshotText = snapshots.map((s, i) => 
            `${i + 1}. ${s.snapshot_name} (${formatDate(s.created_at)}) - ${s.snapshot_type || 'manual'}`
        ).join('\n');
        
        const snapshotId = prompt(`Выберите бэкап для восстановления:\n\n${snapshotText}\n\nВведите номер:`, '1');
        
        if (!snapshotId) return;
        
        const selectedIndex = parseInt(snapshotId) - 1;
        if (isNaN(selectedIndex) || selectedIndex < 0 || selectedIndex >= snapshots.length) {
            alert('Неверный номер бэкапа');
            return;
        }
        
        const selectedSnapshot = snapshots[selectedIndex];
        
        if (!confirm(`Вы уверены, что хотите восстановить данные из бэкапа "${selectedSnapshot.snapshot_name}"?\n\nЭто перезапишет текущие данные сотрудников!`)) {
            return;
        }
        
        const restoreResponse = await fetch(`${API_BASE}/employees/snapshots/${selectedSnapshot.id}/restore`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        if (restoreResponse.ok) {
            const result = await restoreResponse.json();
            alert(`Восстановлено ${result.restored_count || 0} записей из бэкапа "${result.snapshot_name || selectedSnapshot.snapshot_name}"`);
            await loadEmployees(); // Перезагружаем таблицу
        } else {
            let errorMessage = 'Ошибка восстановления';
            try {
            const error = await restoreResponse.json();
                errorMessage += ': ' + (error.detail || 'Неизвестная ошибка');
            } catch {
                const errorText = await restoreResponse.text();
                errorMessage += ` (${restoreResponse.status}): ${errorText}`;
            }
            alert(errorMessage);
        }
    } catch (error) {
        console.error('Error restoring snapshot:', error);
        alert('Ошибка восстановления бэкапа: ' + error.message);
    }
}

// Показать историю версий
async function showVersionHistory() {
    const modal = document.getElementById('versionHistoryModal');
    const listContainer = document.getElementById('versionHistoryList');
    
    modal.classList.remove('hidden');
    listContainer.innerHTML = '<div class="loading">Загрузка истории версий...</div>';
    
    try {
        const response = await fetch(`${API_BASE}/employees/versions`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        if (!response.ok) {
            const errorText = await response.text();
            let errorMessage = 'Ошибка загрузки истории версий';
            try {
                const errorJson = JSON.parse(errorText);
                const detail = errorJson.detail || errorJson.message || JSON.stringify(errorJson);
                errorMessage += ': ' + (typeof detail === 'string' ? detail : JSON.stringify(detail));
            } catch {
                errorMessage += ` (${response.status}): ${errorText}`;
            }
            listContainer.innerHTML = `<div style="color: var(--danger-color); padding: 1rem;">${errorMessage}</div>`;
            return;
        }
        
        const versions = await response.json();
        
        if (!Array.isArray(versions)) {
            listContainer.innerHTML = '<div style="color: var(--danger-color); padding: 1rem;">Ошибка: получен неверный формат данных</div>';
            return;
        }
        
        if (versions.length === 0) {
            listContainer.innerHTML = '<div style="padding: 2rem; text-align: center; color: var(--text-secondary);">История версий пуста</div>';
            return;
        }
        
        // Форматируем дату
        const formatDate = (dateStr) => {
            if (!dateStr) return 'N/A';
            try {
                const date = new Date(dateStr);
                return date.toLocaleString('ru-RU', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit'
                });
            } catch {
                return dateStr.substring(0, 19) || dateStr;
            }
        };
        
        // Создаём список версий
        const versionsHtml = versions.map((version, index) => {
            const isLatest = index === 0;
            const typeIcon = version.type === 'auto' ? '🔄' : '💾';
            const typeLabel = version.type === 'auto' ? 'Автоматическая' : 'Ручная';
            const versionName = version.name || version.snapshot_name || `Версия ${index + 1}`;
            const versionId = version.id;
            const versionDate = formatDate(version.created_at);
            
            // Всегда показываем кнопки для всех версий
            // Используем data-атрибуты вместо inline onclick для избежания проблем с экранированием
            let buttonsHtml = '';
            if (isLatest) {
                // Для текущей версии - кнопка сравнения
                buttonsHtml = `
                    <button class="btn btn-secondary compare-version-btn version-btn-full" 
                            data-version-id="null" 
                            data-version-name="Текущая версия" 
                            data-version-date="${escapeHtml(versionDate)}">
                        🔍 Сравнить с другой версией
                    </button>
                `;
            } else {
                // Для остальных версий - обе кнопки
                buttonsHtml = `
                    <div class="version-buttons">
                        <button class="btn btn-secondary compare-version-btn version-btn-half" 
                                data-version-id="${versionId}" 
                                data-version-name="${escapeHtml(versionName)}" 
                                data-version-date="${escapeHtml(versionDate)}">
                            🔍 Сравнить
                        </button>
                        <button class="btn btn-primary restore-version-btn version-btn-half" 
                                data-version-id="${versionId}" 
                                data-version-name="${escapeHtml(versionName)}">
                            ↩️ Восстановить
                        </button>
                    </div>
                `;
            }
            
            return `
                <div class="version-item ${isLatest ? 'latest' : ''}" data-version-id="${versionId}">
                    <div class="version-item-header">
                        <div>
                            <strong class="version-item-title">${isLatest ? '✓ Текущая версия' : `Версия ${index + 1}`}</strong>
                            ${isLatest ? '<span class="version-badge-active">АКТИВНА</span>' : ''}
                        </div>
                        <div class="version-item-date">
                            ${versionDate}
                        </div>
                    </div>
                    <div class="version-item-meta">
                        ${typeIcon} ${typeLabel} • ${version.employees_count || 0} сотрудников
                    </div>
                    ${version.description ? `<div class="version-item-description">${escapeHtml(version.description)}</div>` : ''}
                    <div class="version-item-author">
                        Автор: ${escapeHtml(version.created_by || 'Система')}
                    </div>
                    ${buttonsHtml}
                </div>
            `;
        }).join('');
        
        listContainer.innerHTML = versionsHtml;
        
        // Настраиваем обработчики для кнопок сравнения и восстановления
        listContainer.querySelectorAll('.compare-version-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                const versionId = this.dataset.versionId === 'null' ? null : parseInt(this.dataset.versionId);
                const versionName = this.dataset.versionName;
                const versionDate = this.dataset.versionDate;
                compareVersion(versionId, versionName, versionDate);
            });
        });
        
        listContainer.querySelectorAll('.restore-version-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                const versionId = parseInt(this.dataset.versionId);
                const versionName = this.dataset.versionName;
                restoreVersion(versionId, versionName);
            });
        });
        
    } catch (error) {
        console.error('Error loading version history:', error);
        listContainer.innerHTML = `<div style="color: var(--danger-color); padding: 1rem;">Ошибка загрузки истории версий: ${error.message}</div>`;
    }
}

// Сравнение версий
async function compareVersion(versionId1, versionName1, versionDate1) {
    // versionId1 может быть null для текущей версии
    const modal = document.getElementById('versionCompareModal');
    modal.classList.remove('hidden');
    
    // Устанавливаем названия версий
    document.getElementById('compareVersion1Name').textContent = versionName1;
    document.getElementById('compareVersion1Date').textContent = versionDate1;
    document.getElementById('compareVersion2Name').textContent = 'Загрузка...';
    document.getElementById('compareVersion2Date').textContent = '';
    
    // Загружаем первую версию
    let version1Data = null;
    try {
        if (versionId1 === null) {
            // Текущая версия
            const response = await fetch(`${API_BASE}/employees/versions/current`, {
                headers: { 'Authorization': `Bearer ${authToken}` }
            });
            if (response.ok) {
                version1Data = await response.json();
            }
        } else {
            const response = await fetch(`${API_BASE}/employees/versions/${versionId1}`, {
                headers: { 'Authorization': `Bearer ${authToken}` }
            });
            if (response.ok) {
                version1Data = await response.json();
            }
        }
    } catch (error) {
        console.error('Error loading version 1:', error);
        document.getElementById('compareTable1').innerHTML = `<div style="color: var(--danger-color); padding: 1rem;">Ошибка загрузки версии 1</div>`;
        return;
    }
    
    if (!version1Data) {
        document.getElementById('compareTable1').innerHTML = `<div style="color: var(--danger-color); padding: 1rem;">Не удалось загрузить версию 1</div>`;
        return;
    }
    
    // Сохраняем данные первой версии для сравнения
    window._compareVersion1Data = version1Data;
    window._compareVersion1Id = versionId1;
    
    // Показываем первую версию
    renderCompareTable(version1Data.employees || [], 'compareTable1', 'version1');
    
    // Загружаем список версий для выпадающего списка
    const versionsResponse = await fetch(`${API_BASE}/employees/versions`, {
        headers: { 'Authorization': `Bearer ${authToken}` }
    });
    
    if (!versionsResponse.ok) {
        document.getElementById('compareTable2').innerHTML = `<div style="color: var(--danger-color); padding: 1rem;">Ошибка загрузки списка версий</div>`;
        return;
    }
    
    const versions = await versionsResponse.json();
    
    // Фильтруем версии (исключаем уже выбранную)
    const availableVersions = versions.filter(v => v.id !== versionId1);
    
    // Заполняем выпадающий список
    const select = document.getElementById('compareVersion2Select');
    select.innerHTML = '<option value="">Выберите версию для сравнения...</option>';
    
    if (availableVersions.length === 0) {
        select.innerHTML = '<option value="">Нет других версий для сравнения</option>';
        select.disabled = true;
        return;
    }
    
    // Форматируем дату
    const formatDate = (dateStr) => {
        if (!dateStr) return 'N/A';
        try {
            const date = new Date(dateStr);
            return date.toLocaleString('ru-RU', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch {
            return dateStr.substring(0, 19) || dateStr;
        }
    };
    
    // Добавляем опции в выпадающий список
    availableVersions.forEach(version => {
        const option = document.createElement('option');
        option.value = version.id;
        const versionName = version.name || version.snapshot_name || `Версия ${version.id}`;
        option.textContent = `${versionName} (${formatDate(version.created_at)})`;
        select.appendChild(option);
    });
    
    // Обработчик выбора версии
    select.onchange = async function() {
        const selectedVersionId = parseInt(this.value);
        if (!selectedVersionId) {
            document.getElementById('compareTable2').innerHTML = '<div style="padding: 2rem; text-align: center; color: var(--text-secondary);">Выберите версию для сравнения</div>';
            document.getElementById('compareVersion2Name').textContent = 'Версия 2';
            document.getElementById('compareVersion2Date').textContent = '';
            return;
        }
        
        // Загружаем вторую версию
        let version2Data = null;
        try {
            const response = await fetch(`${API_BASE}/employees/versions/${selectedVersionId}`, {
                headers: { 'Authorization': `Bearer ${authToken}` }
            });
            if (response.ok) {
                version2Data = await response.json();
            }
        } catch (error) {
            console.error('Error loading version 2:', error);
            document.getElementById('compareTable2').innerHTML = `<div style="color: var(--danger-color); padding: 1rem;">Ошибка загрузки версии 2</div>`;
            return;
        }
        
        if (!version2Data) {
            document.getElementById('compareTable2').innerHTML = `<div style="color: var(--danger-color); padding: 1rem;">Не удалось загрузить версию 2</div>`;
            return;
        }
        
        // Устанавливаем название второй версии
        document.getElementById('compareVersion2Name').textContent = version2Data.name;
        document.getElementById('compareVersion2Date').textContent = formatDate(version2Data.created_at);
        
        // Сравниваем и показываем обе версии
        const comparison = compareVersions(version1Data.employees || [], version2Data.employees || []);
        renderCompareTable(version1Data.employees || [], 'compareTable1', 'version1', comparison);
        renderCompareTable(version2Data.employees || [], 'compareTable2', 'version2', comparison);
        
        // Синхронизируем прокрутку таблиц
        setupSyncScroll();
        
        // Обработчик для переключателя "Только изменённые"
        const showOnlyChangedCheckbox = document.getElementById('showOnlyChanged');
        if (showOnlyChangedCheckbox) {
            showOnlyChangedCheckbox.onchange = function() {
                const showOnly = this.checked;
                const tables = document.querySelectorAll('#compareTable1 tbody tr, #compareTable2 tbody tr');
                tables.forEach(row => {
                    const isChanged = row.dataset.isChanged === 'true';
                    if (!isChanged) {
                        row.style.display = showOnly ? 'none' : '';
                    }
                });
            };
        }
    };
}

// Сравнение двух версий
function compareVersions(employees1, employees2) {
    const comparison = {
        added: new Set(),      // ID добавленных сотрудников
        removed: new Set(),    // ID удалённых сотрудников
        changed: new Map(),    // ID -> {field: {old, new}}
        unchanged: new Set()   // ID без изменений
    };
    
    // Создаём карты для быстрого поиска
    const map1 = new Map(employees1.map(emp => [emp.id, emp]));
    const map2 = new Map(employees2.map(emp => [emp.id, emp]));
    
    // Находим добавленные и удалённые
    for (const emp of employees2) {
        if (!map1.has(emp.id)) {
            comparison.added.add(emp.id);
        }
    }
    
    for (const emp of employees1) {
        if (!map2.has(emp.id)) {
            comparison.removed.add(emp.id);
        }
    }
    
    // Находим изменённые
    for (const emp1 of employees1) {
        const emp2 = map2.get(emp1.id);
        if (emp2 && !comparison.removed.has(emp1.id)) {
            const changes = {};
            let hasChanges = false;
            
            const fields = ['full_name', 'workstation_id', 'department_id', 'phone', 'email', 'ad_account'];
            for (const field of fields) {
                const val1 = emp1[field] || '';
                const val2 = emp2[field] || '';
                if (String(val1) !== String(val2)) {
                    changes[field] = { old: val1, new: val2 };
                    hasChanges = true;
                }
            }
            
            if (hasChanges) {
                comparison.changed.set(emp1.id, changes);
            } else {
                comparison.unchanged.add(emp1.id);
            }
        }
    }
    
    return comparison;
}

// Отображение таблицы для сравнения
function renderCompareTable(employees, containerId, versionId, comparison = null) {
    const container = document.getElementById(containerId);
    
    if (employees.length === 0 && (!comparison || (comparison.added.size === 0 && comparison.removed.size === 0))) {
        container.innerHTML = '<div style="padding: 2rem; text-align: center; color: var(--text-secondary);">Нет данных</div>';
        return;
    }
    
    // Создаём объединённый список всех ID для правильного отображения
    const allIds = new Set();
    employees.forEach(emp => allIds.add(emp.id));
    if (comparison) {
        comparison.added.forEach(id => allIds.add(id));
        comparison.removed.forEach(id => allIds.add(id));
    }
    const sortedIds = Array.from(allIds).sort((a, b) => b - a);
    
    // Проверяем настройку "Только изменённые"
    const showOnlyChanged = document.getElementById('showOnlyChanged')?.checked ?? true;
    
    const tableHtml = `
        <table class="data-table" style="width: 100%; font-size: 0.85rem; border-collapse: separate; border-spacing: 0;">
            <thead>
                <tr>
                    <th style="padding: 0.875rem 1rem; background: linear-gradient(to bottom, #f8fafc, #f1f5f9); border: 1px solid #e2e8f0; border-bottom: 2px solid #cbd5e1; position: sticky; top: 0; z-index: 10; font-weight: 600; color: #475569; text-align: left; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">ID</th>
                    <th style="padding: 0.875rem 1rem; background: linear-gradient(to bottom, #f8fafc, #f1f5f9); border: 1px solid #e2e8f0; border-bottom: 2px solid #cbd5e1; position: sticky; top: 0; z-index: 10; font-weight: 600; color: #475569; text-align: left; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">ФИО</th>
                    <th style="padding: 0.875rem 1rem; background: linear-gradient(to bottom, #f8fafc, #f1f5f9); border: 1px solid #e2e8f0; border-bottom: 2px solid #cbd5e1; position: sticky; top: 0; z-index: 10; font-weight: 600; color: #475569; text-align: left; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">Рабочая станция</th>
                    <th style="padding: 0.875rem 1rem; background: linear-gradient(to bottom, #f8fafc, #f1f5f9); border: 1px solid #e2e8f0; border-bottom: 2px solid #cbd5e1; position: sticky; top: 0; z-index: 10; font-weight: 600; color: #475569; text-align: left; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">Отдел</th>
                    <th style="padding: 0.875rem 1rem; background: linear-gradient(to bottom, #f8fafc, #f1f5f9); border: 1px solid #e2e8f0; border-bottom: 2px solid #cbd5e1; position: sticky; top: 0; z-index: 10; font-weight: 600; color: #475569; text-align: left; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">Телефон</th>
                    <th style="padding: 0.875rem 1rem; background: linear-gradient(to bottom, #f8fafc, #f1f5f9); border: 1px solid #e2e8f0; border-bottom: 2px solid #cbd5e1; position: sticky; top: 0; z-index: 10; font-weight: 600; color: #475569; text-align: left; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">Email</th>
                </tr>
            </thead>
            <tbody>
                ${sortedIds.map(empId => {
                    const emp = employees.find(e => e.id === empId);
                    const exists = !!emp;
                    
                    let rowClass = '';
                    let rowStyle = '';
                    let rowMarker = '';
                    let isChanged = false;
                    
                    if (comparison) {
                        if (comparison.added.has(empId)) {
                            rowClass = 'added-row';
                            rowStyle = 'background: #dcfce7; border-left: 4px solid #86efac;';
                            rowMarker = '<span style="color: #16a34a; font-weight: bold; margin-right: 0.5rem;">+</span>';
                            isChanged = true;
                        } else if (comparison.removed.has(empId)) {
                            rowClass = 'removed-row';
                            rowStyle = 'background: #fee2e2; border-left: 4px solid #fca5a5; opacity: 0.7;';
                            rowMarker = '<span style="color: #dc2626; font-weight: bold; margin-right: 0.5rem;">-</span>';
                            isChanged = true;
                        } else if (comparison.changed.has(empId)) {
                            rowClass = 'changed-row';
                            rowStyle = 'background: #fef3c7; border-left: 4px solid #fcd34d;';
                            rowMarker = '<span style="color: #d97706; font-weight: bold; margin-right: 0.5rem;">~</span>';
                            isChanged = true;
                        }
                    }
                    
                    // Фильтруем по настройке "Только изменённые"
                    if (showOnlyChanged && !isChanged && exists) {
                        return '';
                    }
                    
                    if (!exists) {
                        // Строка существует только в другой версии
                        return `
                            <tr class="${rowClass}" style="${rowStyle}" data-emp-id="${empId}" data-is-changed="true">
                                <td style="padding: 1rem; border: 1px solid #e2e8f0; border-right: 1px solid #cbd5e1; text-align: center; font-weight: 600;">${rowMarker}<span style="color: #64748b;">${empId}</span></td>
                                <td colspan="5" style="padding: 1rem; border: 1px solid #e2e8f0; text-align: center; color: #64748b; font-style: italic; background: #f8fafc;">
                                    Запись отсутствует в этой версии
                                </td>
                            </tr>
                        `;
                    }
                    
                    const changes = comparison?.changed.get(empId) || {};
                    
                    return `
                        <tr class="${rowClass}" style="${rowStyle}" data-emp-id="${empId}" data-is-changed="${isChanged}">
                            <td style="padding: 1rem; border: 1px solid #e2e8f0; border-right: 1px solid #cbd5e1; text-align: center; font-weight: 600; background: ${rowStyle ? 'transparent' : '#ffffff'}; vertical-align: top;">
                                ${rowMarker}<span style="color: #64748b;">${emp.id || ''}</span>
                            </td>
                            <td style="padding: 1rem; border: 1px solid #e2e8f0; ${changes.full_name ? 'background: #fef3c7 !important;' : ''} vertical-align: top;">
                                <div style="display: flex; flex-direction: column; gap: 0.375rem;">
                                    <span style="font-weight: ${changes.full_name ? '600' : '400'}; color: ${changes.full_name ? '#92400e' : '#1e293b'};">${escapeHtml(emp.full_name || '')}</span>
                                    ${changes.full_name ? `<span style="font-size: 0.75rem; color: #991b1b; padding: 0.375rem 0.5rem; background: #fee2e2; border-radius: 0.25rem; border-left: 3px solid #dc2626;">Было: ${escapeHtml(String(changes.full_name.old || ''))}</span>` : ''}
                                </div>
                            </td>
                            <td style="padding: 1rem; border: 1px solid #e2e8f0; ${changes.workstation_id ? 'background: #fef3c7 !important;' : ''} vertical-align: top;">
                                <div style="display: flex; flex-direction: column; gap: 0.375rem;">
                                    <span style="font-weight: ${changes.workstation_id ? '600' : '400'}; color: ${changes.workstation_id ? '#92400e' : '#1e293b'};">${escapeHtml(emp.workstation_name || '')}</span>
                                    ${changes.workstation_id ? `<span style="font-size: 0.75rem; color: #991b1b; padding: 0.375rem 0.5rem; background: #fee2e2; border-radius: 0.25rem; border-left: 3px solid #dc2626;">Было: ${escapeHtml(String(changes.workstation_id.old || ''))}</span>` : ''}
                                </div>
                            </td>
                            <td style="padding: 1rem; border: 1px solid #e2e8f0; ${changes.department_id ? 'background: #fef3c7 !important;' : ''} vertical-align: top;">
                                <div style="display: flex; flex-direction: column; gap: 0.375rem;">
                                    <span style="font-weight: ${changes.department_id ? '600' : '400'}; color: ${changes.department_id ? '#92400e' : '#1e293b'};">${escapeHtml(emp.department_name || '')}</span>
                                    ${changes.department_id ? `<span style="font-size: 0.75rem; color: #991b1b; padding: 0.375rem 0.5rem; background: #fee2e2; border-radius: 0.25rem; border-left: 3px solid #dc2626;">Было: ${escapeHtml(String(changes.department_id.old || ''))}</span>` : ''}
                                </div>
                            </td>
                            <td style="padding: 1rem; border: 1px solid #e2e8f0; ${changes.phone ? 'background: #fef3c7 !important;' : ''} vertical-align: top;">
                                <div style="display: flex; flex-direction: column; gap: 0.375rem;">
                                    <span style="font-weight: ${changes.phone ? '600' : '400'}; color: ${changes.phone ? '#92400e' : '#1e293b'};">${escapeHtml(emp.phone || '')}</span>
                                    ${changes.phone ? `<span style="font-size: 0.75rem; color: #991b1b; padding: 0.375rem 0.5rem; background: #fee2e2; border-radius: 0.25rem; border-left: 3px solid #dc2626;">Было: ${escapeHtml(String(changes.phone.old || ''))}</span>` : ''}
                                </div>
                            </td>
                            <td style="padding: 1rem; border: 1px solid #e2e8f0; ${changes.email || changes.ad_account ? 'background: #fef3c7 !important;' : ''} vertical-align: top;">
                                <div style="display: flex; flex-direction: column; gap: 0.375rem;">
                                    <span style="font-weight: ${(changes.email || changes.ad_account) ? '600' : '400'}; color: ${(changes.email || changes.ad_account) ? '#92400e' : '#1e293b'};">${escapeHtml(emp.email || emp.ad_account || '')}</span>
                                    ${(changes.email || changes.ad_account) ? `<span style="font-size: 0.75rem; color: #991b1b; padding: 0.375rem 0.5rem; background: #fee2e2; border-radius: 0.25rem; border-left: 3px solid #dc2626;">Было: ${escapeHtml(String((changes.email || changes.ad_account)?.old || ''))}</span>` : ''}
                                </div>
                            </td>
                        </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
    `;
    
    container.innerHTML = tableHtml;
}

// Синхронизация прокрутки двух таблиц
function setupSyncScroll() {
    const container1 = document.getElementById('compareTable1Container');
    const container2 = document.getElementById('compareTable2Container');
    
    if (!container1 || !container2) return;
    
    // Удаляем старые обработчики, если они есть
    if (container1._syncScrollHandler) {
        container1.removeEventListener('scroll', container1._syncScrollHandler);
    }
    if (container2._syncScrollHandler) {
        container2.removeEventListener('scroll', container2._syncScrollHandler);
    }
    
    let isScrolling = false;
    
    // Синхронизация прокрутки по вертикали
    container1._syncScrollHandler = function() {
        if (!isScrolling) {
            isScrolling = true;
            container2.scrollTop = container1.scrollTop;
            setTimeout(() => { isScrolling = false; }, 10);
        }
    };
    
    container2._syncScrollHandler = function() {
        if (!isScrolling) {
            isScrolling = true;
            container1.scrollTop = container2.scrollTop;
            setTimeout(() => { isScrolling = false; }, 10);
        }
    };
    
    container1.addEventListener('scroll', container1._syncScrollHandler);
    container2.addEventListener('scroll', container2._syncScrollHandler);
}

// Загрузка настроек
async function loadSettings() {
    // TODO: Реализовать загрузку и отображение настроек
    document.getElementById('settingsContent').innerHTML = '<p>Настройки будут доступны в следующей версии</p>';
}


