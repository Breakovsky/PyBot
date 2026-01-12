(function() {
  'use strict';
  
  const statusSelect = document.querySelector('#issue_status_id');
  const hoursField = document.querySelector('#time_entry_hours, input[name*="hours"]');
  const submitBtn = document.querySelector('input[type="submit"], input[name="commit"]');
  
  
  function checkTimeEntry() {
    const statusId = statusSelect.value;
    const hours = parseFloat(hoursField?.value || 0);
    const requiredStatuses = ['5']; // hardcoded для простоты
    
    if (requiredStatuses.includes(statusId) && hours <= 0) {
      submitBtn.disabled = true;
      submitBtn.value = '🚫 Добавьте время!';
      if (hoursField) {
        hoursField.style.border = '3px solid #dc3545';
        hoursField.title = 'Требуются трудозатраты!';
      }
    } else {
      submitBtn.disabled = false;
      submitBtn.value = submitBtn.defaultValue || 'Сохранить';
      if (hoursField) {
        hoursField.style.border = '';
        hoursField.title = '';
      }
    }
  }
  
  statusSelect.addEventListener('change', checkTimeEntry);
  if (hoursField) hoursField.addEventListener('input', checkTimeEntry);
  checkTimeEntry();
})();
