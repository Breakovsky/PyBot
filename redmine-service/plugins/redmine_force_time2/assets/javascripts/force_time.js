(function() {
  var form = document.getElementById(\"issue-form\");
  if (!form) return;
  
  var statusSelect = document.getElementById(\"issue_status_id\");
  var hoursField = document.querySelector(\"input[name*=hours]\");
  var submitBtn = form.querySelector(\"input[type=submit]\");
  
  if (!statusSelect || !submitBtn) return;
  
  function validate() {
    var statusId = statusSelect.value;
    var hours = parseFloat(hoursField ? hoursField.value : 0) || 0;
    if (statusId == \"5\" && hours <= 0) {
      submitBtn.disabled = true;
      submitBtn.value = \"Добавьте время!\";
      if (hoursField) hoursField.style.border = \"3px solid red\";
    } else {
      submitBtn.disabled = false;
      submitBtn.value = \"Сохранить\";
      if (hoursField) hoursField.style.border = \"\";
    }
  }
  
  statusSelect.addEventListener(\"change\", validate);
  if (hoursField) hoursField.addEventListener(\"input\", validate);
  validate();
})();
