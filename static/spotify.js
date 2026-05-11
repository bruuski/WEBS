// Spotify search widget.
// <div class="sp-widget" data-target-form="#song-form">
//   <div class="sp-search"><input ...><button>Search</button></div>
//   <div class="sp-results"></div>
// </div>
(function () {
    function el(html) {
        var t = document.createElement('template');
        t.innerHTML = html.trim();
        return t.content.firstChild;
    }

    function debounce(fn, ms) {
        var to;
        return function () {
            var ctx = this, args = arguments;
            clearTimeout(to);
            to = setTimeout(function () { fn.apply(ctx, args); }, ms);
        };
    }

    function init(widget) {
        var input    = widget.querySelector('input[type=search], input[type=text], input.sp-q');
        var results  = widget.querySelector('.sp-results');
        var targetSel = widget.getAttribute('data-target-form');
        var targetForm = targetSel ? document.querySelector(targetSel) : null;
        var mode     = widget.getAttribute('data-mode') || (targetForm ? 'fill' : 'link');

        function render(items, err) {
            results.innerHTML = '';
            if (err) {
                results.appendChild(el('<div class="sp-disabled">' + err + '</div>'));
                return;
            }
            if (!items.length) {
                results.appendChild(el('<div class="sp-disabled">No results.</div>'));
                return;
            }
            items.forEach(function (it) {
                var img = it.image
                    ? '<img src="' + it.image + '" alt="">'
                    : '<div style="width:48px;height:48px;background:#222;color:#888;display:flex;align-items:center;justify-content:center;font-family:monospace;font-size:10px;">♪</div>';
                var btn = el(
                    '<button type="button" class="sp-result">' +
                        img +
                        '<div>' +
                            '<div class="t"></div>' +
                            '<div class="a"></div>' +
                        '</div>' +
                        '<span class="sp-pill">Pick</span>' +
                    '</button>'
                );
                btn.querySelector('.t').textContent = it.name || '(untitled)';
                btn.querySelector('.a').textContent = (it.artists || '') + (it.album ? ' — ' + it.album : '') + (it.year ? ' (' + it.year + ')' : '');
                btn.addEventListener('click', function () { choose(it); });
                results.appendChild(btn);
            });
        }

        function choose(it) {
            if (mode === 'link') {
                if (it.url) window.open(it.url, '_blank', 'noopener');
                return;
            }
            if (!targetForm) return;
            function set(name, val) {
                var f = targetForm.querySelector('[name="' + name + '"]');
                if (f && val != null) f.value = val;
            }
            set('title',  it.name);
            set('artist', it.artists);
            set('album',  it.album);
            set('year',   it.year || '');
            set('link',   it.url);
            set('spotify_id',          it.id);
            set('spotify_url',         it.url);
            set('spotify_image',       it.image_lg || it.image);
            set('spotify_preview_url', it.preview);
            // visual confirm
            var preview = widget.querySelector('.sp-picked');
            if (preview) {
                preview.style.display = 'block';
                var img = preview.querySelector('img');
                if (img && it.image) img.src = it.image;
                var t = preview.querySelector('.t');
                if (t) t.textContent = it.name + ' — ' + it.artists;
            }
            results.innerHTML = '';
            input.value = it.name + ' — ' + it.artists;
        }

        async function search(q) {
            if (!q || q.length < 2) { results.innerHTML = ''; return; }
            results.innerHTML = '<div class="sp-disabled">Searching Spotify…</div>';
            try {
                var r = await fetch('/spotify/search?q=' + encodeURIComponent(q));
                var j = await r.json();
                if (j.error) { render([], j.error); return; }
                render(j.items || []);
            } catch (e) {
                render([], 'Search failed: ' + e);
            }
        }

        var debounced = debounce(function () { search(input.value.trim()); }, 350);
        input.addEventListener('input', debounced);
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); search(input.value.trim()); }
        });
        var go = widget.querySelector('.sp-go');
        if (go) go.addEventListener('click', function (e) { e.preventDefault(); search(input.value.trim()); });
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('.sp-widget').forEach(init);
    });
})();
