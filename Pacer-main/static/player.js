// Mini Player State Management
function showToast(message) {
  var existing = document.getElementById('app-toast');
  if (existing) existing.remove();
  var toast = document.createElement('div');
  toast.id = 'app-toast';
  toast.className = 'app-toast';
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(function() { toast.classList.add('show'); }, 10);
  setTimeout(function() {
    toast.classList.remove('show');
    setTimeout(function() { toast.remove(); }, 300);
  }, 2500);
}

const MiniPlayer = {
  currentTrack: null,

  init() {
    const saved = localStorage.getItem("miniPlayerTrack");
    if (saved) {
      try {
        this.currentTrack = JSON.parse(saved);
        this.updateDisplay();
      } catch (e) {}
    }
  },

  play(spotifyId, title, artist) {
    this.currentTrack = { spotifyId, title, artist };
    localStorage.setItem("miniPlayerTrack", JSON.stringify(this.currentTrack));
    this.updateIframe();
    this.updateDisplay();
  },

  updateIframe() {
    if (!this.currentTrack) return;
    const iframe = document.getElementById("spotify-mini-iframe");
    if (iframe) {
      iframe.src = "https://open.spotify.com/embed/track/" + this.currentTrack.spotifyId + "?theme=0";
      iframe.style.position = "absolute";
      iframe.style.left = "-9999px";
      iframe.width = "300";
      iframe.height = "80";
    }
  },

  updateDisplay() {
    const titleEl = document.getElementById("mini-player-title");
    if (titleEl && this.currentTrack) {
      titleEl.textContent = this.currentTrack.title + " - " + this.currentTrack.artist;
    }
    const btn = document.getElementById("mini-play-btn");
    if (btn && this.currentTrack) {
      btn.innerHTML = "&#10074;&#10074;";
    }
  },

  toggle() {
    const btn = document.getElementById("mini-play-btn");
    if (btn) {
      if (btn.innerHTML === "\u25B6") {
        btn.innerHTML = "&#10074;&#10074;";
        this.updateIframe();
      } else {
        btn.innerHTML = "&#9654;";
        const iframe = document.getElementById("spotify-mini-iframe");
        if (iframe) iframe.src = "";
      }
    }
  }
};

function playInMini(spotifyId, title, artist) {
  MiniPlayer.play(spotifyId, title, artist);
}

function miniToggle() {
  MiniPlayer.toggle();
}

function miniPrev() {
  // Future: queue navigation
}

function miniNext() {
  // Future: queue navigation
}

function toggleReply(id) {
  var el = document.getElementById('reply-' + id);
  if (el) {
    var isHidden = el.style.display === 'none';
    el.style.display = isHidden ? 'block' : 'none';
    // Fetch replies on first open
    if (isHidden && !el.dataset.loaded) {
      el.dataset.loaded = '1';
      var parts = id.split('-');
      var type = parts[0];
      var itemId = parts[1];
      var repliesDiv = document.getElementById('replies-' + id);
      if (repliesDiv) {
        fetch('/' + type + 's/' + itemId + '/replies')
          .then(function(r) { return r.text(); })
          .then(function(html) { repliesDiv.innerHTML = html; });
      }
    }
  }
}

function toggleReplySongSearch(id) {
  var el = document.getElementById('reply-song-search-' + id);
  if (el) {
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
  }
}

function toggleReplyAttachMenu(id) {
  var el = document.getElementById('reply-attach-menu-' + id);
  if (el) {
    el.style.display = el.style.display === 'none' ? 'flex' : 'none';
  }
}

var _replySongTimer = null;
function searchReplySong(q, id) {
  clearTimeout(_replySongTimer);
  var results = document.getElementById('reply-song-results-' + id);
  if (q.length < 2) { results.innerHTML = ''; return; }
  _replySongTimer = setTimeout(function() {
    fetch('/spotify/search?q=' + encodeURIComponent(q))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var html = '';
        var items = data.items || [];
        var tracks = items.filter(function(i) { return i.kind === 'track'; });
        tracks.slice(0, 5).forEach(function(t) {
          html += '<div class="attach-result" onclick="attachReplySong(\'' + t.id + '\', \'' + t.name.replace(/'/g, "\\'") + '\', \'' + t.artists.replace(/'/g, "\\'") + '\', \'' + id + '\')">';
          html += '🎵 <strong>' + t.name + '</strong> - ' + t.artists;
          html += '</div>';
        });
        if (!html) html = '<div class="attach-result">No results</div>';
        results.innerHTML = html;
      });
  }, 300);
}

function attachReplySong(spotifyId, title, artist, id) {
  fetch('/track/spotify/' + spotifyId, {method: 'GET', redirect: 'follow'})
    .then(function(r) {
      var match = r.url.match(/\/songs\/(\d+)/);
      if (match) {
        document.getElementById('reply-song-id-' + id).value = match[1];
        document.getElementById('reply-attachment-text-' + id).textContent = '🎵 ' + title + ' - ' + artist;
        document.getElementById('reply-attachment-preview-' + id).style.display = 'flex';
        document.getElementById('reply-song-search-' + id).style.display = 'none';
      }
    });
}

function clearReplyAttachments(id) {
  var songId = document.getElementById('reply-song-id-' + id);
  var imageCid = document.getElementById('reply-image-cid-' + id);
  var preview = document.getElementById('reply-attachment-preview-' + id);
  if (songId) songId.value = '';
  if (imageCid) imageCid.value = '';
  if (preview) preview.style.display = 'none';
}

document.addEventListener("DOMContentLoaded", function() {
  MiniPlayer.init();
});

function togglePlaylistDropdown(songId) {
  var el = document.getElementById('playlist-dropdown-' + songId);
  if (el.style.display === 'none') {
    el.style.display = 'block';
    // Fetch user's playlists
    fetch('/profile/playlists/mine')
      .then(function(r) { return r.json(); })
      .then(function(playlists) {
        var list = document.getElementById('playlist-list-' + songId);
        if (playlists.length === 0) {
          list.innerHTML = '<div style="font-size:12px; color:#666;">No playlists yet. Create one below.</div>';
        } else {
          var html = '';
          playlists.forEach(function(p) {
            html += '<div class="playlist-option" onclick="addToPlaylist(' + p.id + ', ' + songId + ')">' + p.name + '</div>';
          });
          list.innerHTML = html;
        }
      });
  } else {
    el.style.display = 'none';
  }
}

function addToPlaylist(playlistId, songId) {
  var formData = new FormData();
  formData.append('song_id', songId);
  fetch('/profile/playlists/' + playlistId + '/add', { method: 'POST', body: formData })
    .then(function(r) {
      if (r.ok) {
        showToast('Song added to playlist!');
        var el = document.getElementById('playlist-dropdown-' + songId);
        if (el) el.style.display = 'none';
      } else {
        showToast('Failed to add song.');
      }
    });
}

function createPlaylistAndAdd(songId) {
  var nameInput = document.getElementById('new-playlist-name-' + songId);
  var name = nameInput.value.trim();
  if (!name) { showToast('Enter a playlist name'); return; }
  var formData = new FormData();
  formData.append('name', name);
  formData.append('description', '');
  fetch('/profile/playlists/new', { method: 'POST', body: formData, redirect: 'follow' })
    .then(function(r) {
      // Extract playlist ID from redirect URL
      var match = r.url.match(/playlists\/(\d+)/);
      if (match) {
        addToPlaylist(parseInt(match[1]), songId);
        nameInput.value = '';
      }
    });
}

function _escHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function _escJs(s) {
  return String(s == null ? '' : s).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

var _playlistSearchTimer = null;
function searchPlaylistSong(q, playlistId) {
  clearTimeout(_playlistSearchTimer);
  var results = document.getElementById('playlist-add-results');
  if (q.length < 2) { results.innerHTML = ''; return; }
  _playlistSearchTimer = setTimeout(function() {
    results.innerHTML = '<div class="attach-result" style="opacity:0.6;">Searching…</div>';
    fetch('/spotify/search?q=' + encodeURIComponent(q))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var html = '';
        if (data.error) {
          html = '<div class="attach-result" style="opacity:0.7;">' + _escHtml(data.error) + '</div>';
        } else {
          var items = data.items || [];
          if (items.length) {
            items.slice(0, 5).forEach(function(item) {
              var did = item.discogs_id;
              if (did == null) return;
              var title = item.title || '';
              var meta = [item.label, item.year, (item.format || []).join(', ')]
                .filter(Boolean).join(' · ');
              var safeTitle = _escJs(title);
              html += '<div class="attach-result" onclick="addDiscogsReleaseToPlaylist(\'' + did + '\', ' + playlistId + ')">';
              html += '🎵 <strong>' + _escHtml(title) + '</strong>';
              if (meta) html += '<div class="attach-meta">' + _escHtml(meta) + '</div>';
              html += '</div>';
            });
          } else {
            html = '<div class="attach-result">No results</div>';
          }
        }
        if (!html) html = '<div class="attach-result">No results</div>';
        results.innerHTML = html;
      })
      .catch(function() {
        results.innerHTML = '<div class="attach-result">Search failed. Try again.</div>';
      });
  }, 300);
}

function addDiscogsReleaseToPlaylist(discogsId, playlistId) {
  // Resolve the Discogs release to a local song id via the deep-link route
  // (numeric = Discogs release id), then add to the playlist.
  fetch('/track/spotify/' + encodeURIComponent(discogsId), {method: 'GET', redirect: 'follow'})
    .then(function(r) {
      var match = r.url.match(/\/songs\/(\d+)/);
      if (match) {
        addToPlaylist(playlistId, parseInt(match[1]));
        document.getElementById('playlist-add-results').innerHTML = '';
      } else {
        alert("Couldn't resolve that release to a song.");
      }
    })
    .catch(function() { alert("Attach failed. Please try again."); });
}

// Blog Thread Attach Functions
function toggleThreadAttachMenu() {
  var el = document.getElementById('thread-attach-menu');
  if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}
function triggerThreadImage() {
  document.getElementById('thread-image-file').click();
}
function uploadThreadImage(input) {
  if (!input.files || !input.files[0]) return;
  var formData = new FormData();
  formData.append('file', input.files[0]);
  fetch('/feed/upload-image', { method: 'POST', body: formData })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.cid) {
        document.getElementById('thread-image-cid').value = data.cid;
        document.getElementById('thread-attachment-text').textContent = '🖼 Image attached';
        document.getElementById('thread-attachment-preview').style.display = 'flex';
      } else {
        showToast(data.error || 'Upload failed');
      }
    });
}
function toggleThreadSongSearch() {
  var el = document.getElementById('thread-song-search');
  if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}
var _threadSongTimer = null;
function searchThreadSong(q) {
  clearTimeout(_threadSongTimer);
  var results = document.getElementById('thread-song-results');
  if (q.length < 2) { results.innerHTML = ''; return; }
  _threadSongTimer = setTimeout(function() {
    fetch('/spotify/search?q=' + encodeURIComponent(q))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var html = '';
        var items = data.items || [];
        var tracks = items.filter(function(i) { return i.kind === 'track'; });
        tracks.slice(0, 5).forEach(function(t) {
          html += '<div class="attach-result" onclick="selectThreadSong(\'' + t.id + '\', \'' + t.name.replace(/\'/g, "\\'") + '\', \'' + t.artists.replace(/\'/g, "\\'") + '\')">';
          html += '🎵 <strong>' + t.name + '</strong> - ' + t.artists;
          html += '</div>';
        });
        if (!html) html = '<div class="attach-result">No results</div>';
        results.innerHTML = html;
      });
  }, 300);
}
function selectThreadSong(spotifyId, name, artist) {
  document.getElementById('thread-song-id').value = spotifyId;
  document.getElementById('thread-attachment-text').textContent = '🎵 ' + name + ' - ' + artist;
  document.getElementById('thread-attachment-preview').style.display = 'flex';
  document.getElementById('thread-song-search').style.display = 'none';
}
function clearThreadAttachments() {
  document.getElementById('thread-image-cid').value = '';
  document.getElementById('thread-song-id').value = '';
  document.getElementById('thread-attachment-preview').style.display = 'none';
}

// Blog Thread Reply Attach Functions
function toggleTreplyAttachMenu() {
  var el = document.getElementById('treply-attach-menu');
  if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}
function triggerTreplyImage() {
  document.getElementById('treply-image-file').click();
}
function uploadTreplyImage(input) {
  if (!input.files || !input.files[0]) return;
  var formData = new FormData();
  formData.append('file', input.files[0]);
  fetch('/feed/upload-image', { method: 'POST', body: formData })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.cid) {
        document.getElementById('treply-image-cid').value = data.cid;
        document.getElementById('treply-attachment-text').textContent = '🖼 Image attached';
        document.getElementById('treply-attachment-preview').style.display = 'flex';
      } else {
        showToast(data.error || 'Upload failed');
      }
    });
}
function toggleTreplySongSearch() {
  var el = document.getElementById('treply-song-search');
  if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}
var _treplySongTimer = null;
function searchTreplySong(q) {
  clearTimeout(_treplySongTimer);
  var results = document.getElementById('treply-song-results');
  if (q.length < 2) { results.innerHTML = ''; return; }
  _treplySongTimer = setTimeout(function() {
    fetch('/spotify/search?q=' + encodeURIComponent(q))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var html = '';
        var items = data.items || [];
        var tracks = items.filter(function(i) { return i.kind === 'track'; });
        tracks.slice(0, 5).forEach(function(t) {
          html += '<div class="attach-result" onclick="selectTreplySong(\'' + t.id + '\', \'' + t.name.replace(/\'/g, "\\'") + '\', \'' + t.artists.replace(/\'/g, "\\'") + '\')">';
          html += '🎵 <strong>' + t.name + '</strong> - ' + t.artists;
          html += '</div>';
        });
        if (!html) html = '<div class="attach-result">No results</div>';
        results.innerHTML = html;
      });
  }, 300);
}
function selectTreplySong(spotifyId, name, artist) {
  document.getElementById('treply-song-id').value = spotifyId;
  document.getElementById('treply-attachment-text').textContent = '🎵 ' + name + ' - ' + artist;
  document.getElementById('treply-attachment-preview').style.display = 'flex';
  document.getElementById('treply-song-search').style.display = 'none';
}
function clearTreplyAttachments() {
  document.getElementById('treply-image-cid').value = '';
  document.getElementById('treply-song-id').value = '';
  document.getElementById('treply-attachment-preview').style.display = 'none';
}
