/* Waitlist form: custom use-case dropdown, div-based submit, JSON submission to the site API */
(function () {
  if (!window.ZC) return;
  var USE_CASES = [
    { value: 'Model inference', label: 'Model inference' },
    { value: 'Fine-tuning / training', label: 'Fine-tuning / training' },
    { value: 'Batch data processing', label: 'Batch data processing' },
    { value: 'Something else', label: 'Something else' }
  ];
  var sel = document.getElementById('use-case-select');
  var state = sel ? ZC.initSelect(sel, USE_CASES) : { value: null };

  function showError(msg) {
    var e = document.getElementById('wl-error');
    e.textContent = msg;
    e.hidden = !msg;
  }

  ZC.submitWaitlist = function () {
    var email = (document.getElementById('wl-email').value || '').trim();
    if (!email || email.indexOf('@') === -1) { showError('Please enter a valid work email.'); return; }
    if (!state.value) { showError('Please choose your primary use case.'); return; }
    showError('');
    var btn = document.getElementById('wl-submit');
    btn.classList.add('disabled');
    btn.textContent = 'Submitting…';
    ZC.postEvent('waitlist_submit', { email: email, use_case: state.value })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r; })
      .then(function () {
        var card = document.getElementById('waitlist-card');
        card.className = 'card form-card success';
        card.innerHTML =
          '<h2>You’re on the list</h2>' +
          '<p>Thanks! We’ll email <strong>' + email.replace(/</g, '&lt;') + '</strong> as soon as your workspace is ready.</p>' +
          '<a class="btn btn-primary" href="thanks.html">Continue →</a>';
      })
      .catch(function (err) {
        btn.classList.remove('disabled');
        btn.textContent = 'Request early access';
        showError('Something went wrong (' + err.message + '). Please try again.');
      });
  };

  var submit = document.getElementById('wl-submit');
  if (submit) {
    submit.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); ZC.submitWaitlist(); }
    });
  }
})();
