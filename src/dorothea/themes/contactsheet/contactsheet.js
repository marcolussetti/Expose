/*
 * contactsheet (#28): lays the tiles out as a masonry grid and opens them in a lightbox.
 *
 * Grid: each tile spans as many of the grid's small rows as its height needs (see global.css).
 * Lightbox: a <dialog> showing one photo at the largest size that fits the screen (the smallest
 * encoded width that's enough), or its video; with the caption and photo details.
 *   next / previous / first / last: the keys of keyboard.js (window.dorotheaKeys), the buttons,
 *   or a swipe; Escape, the close button or a click beside the photo closes it.
 * The address follows the open photo (#3 is the third), so links to it open it, and Back closes
 * the lightbox.
 *
 * The pure parts are on window.contactsheet, for tests/js/contactsheet_test.js.
 */
(function (root) {
	'use strict';

	var VIDEO_FORMATS = {
		h265: { extension: 'mp4', type: 'video/mp4; codecs=hev1.1.2.L93.B0' },
		h264: { extension: 'mp4', type: 'video/mp4' },
		vp9: { extension: 'webm', type: 'video/webm; codecs=vp9' },
		vp8: { extension: 'webm', type: 'video/webm; codecs=vp8' },
		ogv: { extension: 'ogv', type: 'video/ogg' }
	};

	var SWIPE = 50; // px a finger must travel sideways for a swipe

	// The config's widths (the body's data-resolution), smallest first
	function resolutions(value) {
		return String(value || '').split(/\s+/).filter(Boolean).map(Number).filter(function (v) {
			return v > 0;
		}).sort(function (a, b) { return a - b; });
	}

	// The smallest encoded width of at least `needed` px. An item has every width up to its
	// largest (`maxwidth`), and always the smallest.
	function pickWidth(widths, maxwidth, needed) {
		var made = widths.filter(function (v) { return v <= maxwidth; });
		if (!made.length) {
			return widths.length ? widths[0] : maxwidth;
		}
		for (var i = 0; i < made.length; i++) {
			if (made[i] >= needed) {
				return made[i];
			}
		}
		return made[made.length - 1];
	}

	// CSS width of a width x height item fitted into a screen
	function fitWidth(width, height, screenWidth, screenHeight) {
		if (!width || !height) {
			return screenWidth;
		}
		return Math.min(screenWidth, screenHeight * width / height);
	}

	// Grid rows a tile `height` px tall spans, with rows `row` px apart and `gap` px between them
	function rowSpan(height, row, gap) {
		return Math.max(1, Math.ceil((height + gap) / (row + gap)));
	}

	// 'next' / 'previous' for a sideways swipe, else null
	function swipe(dx, dy) {
		if (Math.abs(dx) < SWIPE || Math.abs(dx) <= Math.abs(dy)) {
			return null;
		}
		return dx < 0 ? 'next' : 'previous';
	}

	// Which item is open, and moving between them. `view` draws it: view.show(index, opening)
	// and view.hide(index).
	function Lightbox(count, view) {
		this.count = count;
		this.view = view;
		this.index = -1;
	}

	Lightbox.prototype.isOpen = function () {
		return this.index >= 0;
	};

	Lightbox.prototype.open = function (index) {
		if (!this.count) {
			return;
		}
		var opening = !this.isOpen();
		this.index = Math.max(0, Math.min(this.count - 1, index));
		this.view.show(this.index, opening);
	};

	Lightbox.prototype.go = function (index) {
		index = Math.max(0, Math.min(this.count - 1, index));
		if (this.isOpen() && index !== this.index) {
			this.open(index);
		}
	};

	Lightbox.prototype.close = function () {
		if (this.isOpen()) {
			var index = this.index;
			this.index = -1;
			this.view.hide(index);
		}
	};

	// Do what an action from dorotheaKeys.action / swipe asks; true if it was one
	Lightbox.prototype.handle = function (action) {
		switch (action) {
			case 'next': this.go(this.index + 1); return true;
			case 'previous': this.go(this.index - 1); return true;
			case 'first': this.go(0); return true;
			case 'last': this.go(this.count - 1); return true;
			default: return false;
		}
	};

	root.contactsheet = {
		resolutions: resolutions,
		pickWidth: pickWidth,
		fitWidth: fitWidth,
		rowSpan: rowSpan,
		swipe: swipe,
		Lightbox: Lightbox
	};

	if (typeof document === 'undefined') {
		return;
	}

	function start() {
		var body = document.body;
		var sheet = document.getElementById('sheet');
		var dialog = document.getElementById('lightbox');
		if (!sheet || !dialog) {
			return;
		}
		var tiles = Array.prototype.slice.call(sheet.querySelectorAll('.tile'));
		var widths = resolutions(body.getAttribute('data-resolution'));
		var formats = String(body.getAttribute('data-videoformats') || '').split(/\s+/).filter(function (v) {
			return VIDEO_FORMATS[v];
		});
		var respath = body.getAttribute('data-respath') || '';
		var stage = dialog.querySelector('.stage');
		var details = dialog.querySelector('.details');
		var previousButton = dialog.querySelector('.previous');
		var nextButton = dialog.querySelector('.next');
		var pushed = false; // an entry of our own in the history, which Back removes

		// Captions: drop empty ones, and mark tiles that have text (touch screens show a mark)
		tiles.forEach(function (tile) {
			var caption = tile.querySelector('.caption');
			if (!caption) {
				return;
			}
			if (caption.textContent.trim() === '' && caption.children.length === 0) {
				caption.parentNode.removeChild(caption);
			} else {
				tile.classList.add('has-text');
			}
		});

		// Masonry, unless the browser does it itself
		var native = root.CSS && CSS.supports && (CSS.supports('grid-template-rows', 'masonry') ||
			CSS.supports('display', 'grid-lanes'));
		if (!native) {
			sheet.classList.add('masonry');
			var span = function (tile) {
				var style = getComputedStyle(sheet);
				var row = parseFloat(style.gridAutoRows) || 4;
				var gap = parseFloat(style.rowGap) || 0;
				tile.style.gridRowEnd = 'span ' + rowSpan(tile.getBoundingClientRect().height, row, gap);
			};
			tiles.forEach(span);
			if (root.ResizeObserver) {
				// Tiles change height with the column width, and when a caption's fonts arrive
				var observer = new ResizeObserver(function (entries) {
					entries.forEach(function (entry) { span(entry.target); });
				});
				tiles.forEach(function (tile) { observer.observe(tile); });
			} else {
				var pending = false;
				root.addEventListener('resize', function () {
					if (!pending) {
						pending = true;
						requestAnimationFrame(function () {
							pending = false;
							tiles.forEach(span);
						});
					}
				});
			}
		}

		function url(tile) {
			return respath + tile.getAttribute('data-url');
		}

		function width(tile) {
			var maxwidth = Number(tile.getAttribute('data-maxwidth'));
			var maxheight = Number(tile.getAttribute('data-maxheight'));
			var needed = fitWidth(maxwidth, maxheight, root.innerWidth, root.innerHeight) * (root.devicePixelRatio || 1);
			return pickWidth(widths, maxwidth, Math.ceil(needed));
		}

		function media(tile) {
			var base = url(tile) + '/' + width(tile);
			if (tile.getAttribute('data-type') === 'video' && formats.length) {
				var video = document.createElement('video');
				video.controls = true;
				video.autoplay = true;
				video.loop = true;
				video.playsInline = true;
				video.poster = base + '.jpg';
				formats.forEach(function (format) {
					var source = document.createElement('source');
					source.src = base + '-' + format + '.' + VIDEO_FORMATS[format].extension;
					source.type = VIDEO_FORMATS[format].type;
					video.appendChild(source);
				});
				return video;
			}
			var img = document.createElement('img');
			img.src = base + '.jpg';
			img.alt = '';
			img.width = Number(tile.getAttribute('data-maxwidth'));
			img.height = Number(tile.getAttribute('data-maxheight'));
			return img;
		}

		function preload(index) {
			var tile = tiles[index];
			if (tile && tile.getAttribute('data-type') !== 'video') {
				new Image().src = url(tile) + '/' + width(tile) + '.jpg';
			}
		}

		function address(index) {
			return index < 0 ? root.location.pathname + root.location.search : '#' + (index + 1);
		}

		var lightbox = new Lightbox(tiles.length, {
			show: function (index, opening) {
				var tile = tiles[index];
				var shot = document.createElement('div');
				shot.className = 'shot';
				var ratio = Number(tile.getAttribute('data-maxwidth')) / Number(tile.getAttribute('data-maxheight'));
				if (ratio > 0) {
					shot.style.setProperty('--ratio', String(ratio));
				}
				shot.appendChild(media(tile));
				var info = tile.querySelector('.photo-info');
				if (info) {
					info = info.cloneNode(true);
					info.classList.remove('pinned');
					shot.appendChild(info);
				}
				stage.textContent = ''; // stops the previous video
				stage.appendChild(shot);

				details.textContent = '';
				var caption = tile.querySelector('.caption');
				if (caption) {
					Array.prototype.forEach.call(caption.children, function (child) {
						details.appendChild(child.cloneNode(true));
					});
				}
				previousButton.hidden = index === 0;
				nextButton.hidden = index === tiles.length - 1;

				if (opening) {
					if (dialog.showModal) {
						dialog.showModal();
					} else {
						dialog.setAttribute('open', '');
					}
					dialog.focus();
					if (root.location.hash !== address(index)) {
						root.history.pushState({ contactsheet: true }, '', address(index));
						pushed = true;
					}
				} else {
					root.history.replaceState(root.history.state, '', address(index));
				}
				preload(index + 1);
				preload(index - 1);
			},
			hide: function (index) {
				stage.textContent = '';
				details.textContent = '';
				if (dialog.open) {
					dialog.close ? dialog.close() : dialog.removeAttribute('open');
				}
				if (pushed) {
					pushed = false;
					root.history.back();
				} else {
					root.history.replaceState(null, '', address(-1));
				}
				var frame = tiles[index].querySelector('.frame');
				if (frame) {
					frame.focus({ preventScroll: true });
				}
			}
		});

		sheet.addEventListener('click', function (event) {
			var frame = event.target.closest && event.target.closest('.frame');
			if (!frame || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) {
				return;
			}
			event.preventDefault();
			lightbox.open(tiles.indexOf(frame.closest('.tile')));
		});

		// Escape closes a dialog by itself; keep up with it
		dialog.addEventListener('close', function () { lightbox.close(); });

		function pressed(action, event) {
			if (lightbox.handle(action)) {
				// After a click, keys go back to the lightbox rather than staying on the button
				if (event && event.detail > 0) {
					dialog.focus();
				}
			}
		}
		previousButton.addEventListener('click', function (event) { pressed('previous', event); });
		nextButton.addEventListener('click', function (event) { pressed('next', event); });
		dialog.querySelector('.close').addEventListener('click', function () { lightbox.close(); });
		stage.addEventListener('click', function (event) {
			if (event.target === stage) {
				lightbox.close();
			}
		});

		document.addEventListener('keydown', function (event) {
			if (!lightbox.isOpen() || !root.dorotheaKeys) {
				return;
			}
			if (lightbox.handle(root.dorotheaKeys.action(event))) {
				event.preventDefault();
			}
		});

		var touch = null;
		stage.addEventListener('touchstart', function (event) {
			touch = event.touches.length === 1 ? { x: event.touches[0].clientX, y: event.touches[0].clientY } : null;
		}, { passive: true });
		stage.addEventListener('touchend', function (event) {
			if (touch && event.changedTouches.length === 1) {
				var t = event.changedTouches[0];
				lightbox.handle(swipe(t.clientX - touch.x, t.clientY - touch.y));
			}
			touch = null;
		}, { passive: true });

		// Back (or anything else that leaves our history entry) closes it
		root.addEventListener('popstate', function () {
			pushed = false;
			lightbox.close();
		});

		// Opened at a photo (#3), e.g. from the feed
		function fromAddress() {
			var match = /^#(\d+)$/.exec(root.location.hash);
			var index = match ? Number(match[1]) - 1 : -1;
			if (index >= 0 && index < tiles.length) {
				lightbox.open(index);
			}
		}
		fromAddress();
		root.addEventListener('hashchange', fromAddress);

		// Galleries menu on small screens
		var menubutton = document.getElementById('menubutton');
		var sidebar = document.getElementById('sidebar');
		if (menubutton && sidebar) {
			menubutton.addEventListener('click', function () {
				var open = sidebar.classList.toggle('open');
				menubutton.setAttribute('aria-expanded', open ? 'true' : 'false');
			});
		}
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', start);
	} else {
		start();
	}
})(typeof window !== 'undefined' ? window : this);
