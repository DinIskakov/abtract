/* Limits page: sandbox limits accordion. Panel content is inserted into the DOM on first open. */
(function () {
  var CONTENT = {
    'sandbox-timeout':
      '<p>The maximum timeout for a sandbox is <strong>24 hours</strong> (86,400 seconds). ' +
      'A sandbox is terminated when its timeout elapses, regardless of activity. Pass a shorter value with ' +
      '<code>zephyr.Sandbox.create(timeout=...)</code>; the default is 10 minutes.</p>',
    'sandbox-memory':
      '<p>A sandbox can request up to <strong>256 GiB</strong> of memory. Sandboxes that exceed their request are OOM-killed and ' +
      'exit with status 137.</p>',
    'sandbox-concurrency':
      '<p>Each workspace can run up to <strong>100 sandboxes</strong> at the same time. Additional <code>Sandbox.create()</code> ' +
      'calls block until a slot frees up.</p>',
    'sandbox-disk':
      '<p>Every sandbox gets <strong>100 GiB</strong> of ephemeral disk under <code>/tmp</code>. Attach a volume for anything ' +
      'that must outlive the sandbox.</p>'
  };
  Array.prototype.forEach.call(document.querySelectorAll('.acc-item'), function (item) {
    var btn = item.querySelector('.acc-btn');
    var panel = item.querySelector('.acc-panel');
    btn.addEventListener('click', function () {
      var open = item.classList.toggle('open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open && !panel.innerHTML) panel.innerHTML = CONTENT[item.getAttribute('data-key')] || '';
    });
  });
})();
