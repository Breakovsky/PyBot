// UI БЛОКИРОВКА: Предотвращает закрытие без времени
(function() {
  document.addEventListener('DOMContentLoaded', function() {
    const statusSelect = document.querySelector('#issue_status_id');
    const timeEntryHours = document.querySelector('#time_entry_hours');
    const submitButton = document.querySelector('input[name=commit]');
    
    
    function validateTime() {
      const statusId = statusSelect.value;
      const hours = parseFloat(timeEntryHours?.value || '0');
      const requiredStatuses = ['5']; // Можно загрузить из настроек
      
      if (requiredStatuses.includes(statusId) && hours <= 0) {
        submitButton.disabled = true;
        submitButton.title = '🚫 Добавьте трудозатраты!';
        if (timeEntryHours) timeEntryHours.style.border = '2px solid red';
        return false;
      }
      
      submitButton.disabled = false;
      submitButton.title = '';
      if (timeEntryHours) timeEntryHours.style.border = '';
      return true;
    }
    
    statusSelect.addEventListener('change', validateTime);
    if (timeEntryHours) timeEntryHours.addEventListener('input', validateTime);
    validateTime(); // Проверка при загрузке
  });
})();
