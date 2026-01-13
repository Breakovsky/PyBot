// IP Addresses Management JavaScript

// Modal functions
function showAddGroupModal() {
    document.getElementById('add-group-form').reset();
    document.getElementById('add-group-modal').classList.add('active');
    document.getElementById('group-name-input').focus();
}

function showEditGroupModal(groupName) {
    document.getElementById('edit-group-old-name').value = groupName;
    document.getElementById('edit-group-name-input').value = groupName;
    document.getElementById('edit-group-modal').classList.add('active');
    document.getElementById('edit-group-name-input').focus();
}

function showAddDeviceModal(groupName) {
    document.getElementById('add-device-form').reset();
    document.getElementById('add-device-group-name').value = groupName;
    document.getElementById('add-device-modal').classList.add('active');
    document.getElementById('add-device-name-input').focus();
}

function showEditDeviceModal(groupName, deviceName, deviceIp) {
    document.getElementById('edit-device-group-name').value = groupName;
    document.getElementById('edit-device-old-name').value = deviceName;
    document.getElementById('edit-device-name-input').value = deviceName;
    document.getElementById('edit-device-ip-input').value = deviceIp;
    document.getElementById('edit-device-modal').classList.add('active');
    document.getElementById('edit-device-name-input').focus();
}

function closeModal(modalId) {
    document.getElementById(modalId).classList.remove('active');
}

// Close modal on outside click
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal')) {
        e.target.classList.remove('active');
    }
});

// Close modal on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal.active').forEach(modal => {
            modal.classList.remove('active');
        });
    }
});

// Notification system
function showNotification(message, type = 'success') {
    const notificationArea = document.getElementById('notification-area');
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <span>${message}</span>
        <button onclick="this.parentElement.remove()" class="btn-icon-sm">
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
                <path d="M5 5L15 15M15 5L5 15" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
        </button>
    `;
    
    notificationArea.appendChild(notification);
    
    setTimeout(() => {
        notification.classList.add('show');
    }, 10);
    
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// API functions
async function apiCall(url, method, data) {
    try {
        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
            },
            body: data ? JSON.stringify(data) : null
        });
        
        const result = await response.json();
        
        if (!response.ok) {
            throw new Error(result.error || 'Ошибка сервера');
        }
        
        return result;
    } catch (error) {
        throw error;
    }
}

// Group handlers
async function handleAddGroup(e) {
    e.preventDefault();
    const formData = new FormData(e.target);
    const name = formData.get('name').trim();
    
    try {
        await apiCall('/api/ip-groups/add', 'POST', { name });
        showNotification('Группа успешно добавлена', 'success');
        closeModal('add-group-modal');
        setTimeout(() => location.reload(), 500);
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

async function handleEditGroup(e) {
    e.preventDefault();
    const formData = new FormData(e.target);
    const oldName = document.getElementById('edit-group-old-name').value;
    const newName = formData.get('name').trim();
    
    try {
        await apiCall('/api/ip-groups/update', 'POST', {
            old_name: oldName,
            new_name: newName
        });
        showNotification('Группа успешно обновлена', 'success');
        closeModal('edit-group-modal');
        setTimeout(() => location.reload(), 500);
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

async function deleteGroup(groupName) {
    if (!confirm(`Вы уверены, что хотите удалить группу "${groupName}"? Это действие нельзя отменить.`)) {
        return;
    }
    
    try {
        await apiCall('/api/ip-groups/delete', 'POST', { name: groupName });
        showNotification('Группа успешно удалена', 'success');
        setTimeout(() => location.reload(), 500);
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

function editGroupName(groupName) {
    showEditGroupModal(groupName);
}

// Device handlers
async function handleAddDevice(e) {
    e.preventDefault();
    const formData = new FormData(e.target);
    const groupName = document.getElementById('add-device-group-name').value;
    const name = formData.get('name').trim();
    const ip = formData.get('ip').trim();
    
    try {
        await apiCall('/api/ip-devices/add', 'POST', {
            group_name: groupName,
            name: name,
            ip: ip
        });
        showNotification('Устройство успешно добавлено', 'success');
        closeModal('add-device-modal');
        setTimeout(() => location.reload(), 500);
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

async function handleEditDevice(e) {
    e.preventDefault();
    const formData = new FormData(e.target);
    const groupName = document.getElementById('edit-device-group-name').value;
    const oldName = document.getElementById('edit-device-old-name').value;
    const newName = formData.get('name').trim();
    const newIp = formData.get('ip').trim();
    
    try {
        await apiCall('/api/ip-devices/update', 'POST', {
            group_name: groupName,
            old_name: oldName,
            new_name: newName,
            ip: newIp
        });
        showNotification('Устройство успешно обновлено', 'success');
        closeModal('edit-device-modal');
        setTimeout(() => location.reload(), 500);
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

async function deleteDevice(groupName, deviceName) {
    if (!confirm(`Вы уверены, что хотите удалить устройство "${deviceName}"?`)) {
        return;
    }
    
    try {
        await apiCall('/api/ip-devices/delete', 'POST', {
            group_name: groupName,
            name: deviceName
        });
        showNotification('Устройство успешно удалено', 'success');
        setTimeout(() => location.reload(), 500);
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

function editDevice(groupName, deviceName, deviceIp) {
    showEditDeviceModal(groupName, deviceName, deviceIp);
}

