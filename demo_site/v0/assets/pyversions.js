/* Python versions page: expand the table on "Show all" */
(function () {
  var ROWS = [
    ['3.9',  'Supported', 'Oldest supported version. Consider upgrading; upstream ships security fixes only.'],
    ['3.10', 'Supported', ''],
    ['3.11', 'Supported', 'Recommended for CPU-heavy workloads (faster interpreter).'],
    ['3.12', 'Supported · Default', 'Used when <code>python_version</code> is omitted.'],
    ['3.13', 'Supported', 'Free-threaded builds are not available yet.']
  ];
  var btn = document.getElementById('show-all');
  if (!btn) return;
  btn.addEventListener('click', function () {
    var tbody = document.getElementById('py-rows');
    tbody.innerHTML = ROWS.map(function (r) {
      var pill = r[1].indexOf('Default') !== -1 ? '<span class="pill blue">' + r[1] + '</span>' : '<span class="pill">' + r[1] + '</span>';
      return '<tr><td><strong>Python ' + r[0] + '</strong></td><td>' + pill + '</td><td>' + r[2] + '</td></tr>';
    }).join('');
  });
})();
