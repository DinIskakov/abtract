/* Regions page: custom dropdown populated by JS; details shown after a region is chosen */
(function () {
  var REGIONS = [
    { id: 'us-iad1', city: 'Ashburn, Virginia', country: 'United States', area: 'US East',    gpus: 'H100, A100, L40S, T4' },
    { id: 'us-ord1', city: 'Chicago, Illinois', country: 'United States', area: 'US Central', gpus: 'A100, L40S, T4' },
    { id: 'us-sjc1', city: 'San Jose, California', country: 'United States', area: 'US West', gpus: 'H100, L40S, T4' },
    { id: 'eu-fra1', city: 'Frankfurt', country: 'Germany', area: 'Europe',           gpus: 'H100, A100, L40S' },
    { id: 'eu-lhr1', city: 'London', country: 'United Kingdom', area: 'Europe',       gpus: 'A100, T4' },
    { id: 'ap-sin1', city: 'Singapore', country: 'Singapore', area: 'Asia-Pacific',  gpus: 'H100, L40S, T4' }
  ];
  var el = document.getElementById('region-select');
  if (!el || !window.ZC) return;
  var options = REGIONS.map(function (r) {
    return { value: r.id, label: r.city + ', ' + r.country + ' (' + r.id + ')' };
  });
  ZC.initSelect(el, options, function (opt) {
    var r = REGIONS.filter(function (x) { return x.id === opt.value; })[0];
    var d = document.getElementById('region-details');
    d.innerHTML =
      '<h3 style="margin-top:0">' + r.city + ', ' + r.country + '</h3>' +
      '<dl class="kv">' +
      '<dt>Region ID</dt><dd><code>' + r.id + '</code></dd>' +
      '<dt>Area</dt><dd>' + r.area + '</dd>' +
      '<dt>GPU types</dt><dd>' + r.gpus + '</dd>' +
      '<dt>Status</dt><dd><span class="pill">Available</span></dd>' +
      '</dl>';
    d.hidden = false;
  });
})();
