// SoftBot Admin Panel - JavaScript

document.addEventListener('DOMContentLoaded', () => {
    // Initialize components
    initAlerts();
    initCodeInput();
});

// Auto-dismiss alerts after 5 seconds
function initAlerts() {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.opacity = '0';
            alert.style.transform = 'translateY(-10px)';
            setTimeout(() => alert.remove(), 300);
        }, 5000);
    });
}

// Format code input
function initCodeInput() {
    const codeInput = document.querySelector('.code-input');
    if (codeInput) {
        codeInput.addEventListener('input', (e) => {
            // Allow only numbers
            e.target.value = e.target.value.replace(/\D/g, '');
            
            // Auto-submit when 6 digits entered
            if (e.target.value.length === 6) {
                e.target.form?.submit();
            }
        });
    }
}

// Format timestamps
function formatDate(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Animate numbers
function animateNumber(element, target, duration = 500) {
    const start = parseInt(element.textContent) || 0;
    const increment = (target - start) / (duration / 16);
    let current = start;
    
    const timer = setInterval(() => {
        current += increment;
        if ((increment > 0 && current >= target) || (increment < 0 && current <= target)) {
            element.textContent = target;
            clearInterval(timer);
        } else {
            element.textContent = Math.round(current);
        }
    }, 16);
}

// Toast notifications
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.classList.add('show');
    }, 10);
    
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Confirm dialog
function confirmAction(message, callback) {
    if (confirm(message)) {
        callback();
    }
}

