// Music search widget (Spotify-powered, lands on Pacer pages).
// Markup:
//   <div class="sp-widget">
//     <div class="sp-search"><input class="sp-q"><button class="sp-go">Search</button></div>
//     <div class="sp-results"></div>
//   </div>
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
        var input    = widget.querySelector('input.sp-q, input[type=search], input[type=text]');
        var results  = widget.querySelector('.sp-results');
        if (!input || !results) return;

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
                    : '<div class="sp-ph" style="width:48px;height:48px;background:#222;color:#888;display:flex;align-items:center;justify-content:center;font-family:monospace;font-size:14px;">♪</div>';
                var kindPill = it.kind === 'album'
                    ? '<span class="sp-pill alb">Album</span>'
                    : '<span class="sp-pill">Track</span>';
                var btn = el(
                    '<a class="sp-result" href="#">' +
                        img +
                        '<div>' +
                            '<div class="t"></div>' +
                            '<div class="a"></div>' +
                        '</div>' +
                        kindPill +
                    '</a>'
                );
                btn.querySelector('.t').textContent = it.name || '(untitled)';
                var sub = (it.artists || '');
                if (it.kind === 'track' && it.album) sub += ' — ' + it.album;
                if (it.year) sub += ' (' + it.year + ')';
                btn.querySelector('.a').textContent = sub;
                var path = it.kind === 'album'
                    ? '/album/spotify/' + encodeURIComponent(it.id)
                    : '/track/spotify/' + encodeURIComponent(it.id);
                btn.setAttribute('href', path);
                results.appendChild(btn);
            });
        }

        async function search(q) {
            if (!q || q.length < 2) { results.innerHTML = ''; return; }
            results.innerHTML = '<div class="sp-disabled">Searching…</div>';
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
