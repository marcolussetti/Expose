/*
 * Keyboard navigation between photos (#16).
 *
 *   next:     Down, Page Down, Right, Space, j
 *   previous: Up, Page Up, Left, Shift+Space, k
 *   first / last: Home / End
 *
 * The script tag says which elements are the photos: <script src="keyboard.js" data-slides=".slide">
 * and, optionally, what pauses navigation (data-blocked-by="#fullscreen.active").
 * "Previous" first returns to the top of the current photo if it's partly scrolled past; photos
 * side by side in a row count as one stop.
 * Keys are left alone while typing, when a modifier is held, or while a full-screen viewer is open.
 */
(function () {
	var script = document.currentScript;
	var selector = (script && script.getAttribute('data-slides')) || '.slide';
	var blockers = (script && script.getAttribute('data-blocked-by')) || '';
	var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

	// While a smooth scroll is running, keep counting from where it's going, not where it is
	var target = null;
	var targetUntil = 0;

	function slides() {
		return Array.prototype.slice.call(document.querySelectorAll(selector));
	}

	// Index of the photo at the top of the screen: the last one whose top is at or above it
	function currentIndex(list) {
		var index = 0;
		for (var i = 0; i < list.length; i++) {
			if (list[i].getBoundingClientRect().top <= 5) {
				index = i;
			}
		}
		return index;
	}

	function go(list, index) {
		index = Math.max(0, Math.min(list.length - 1, index));
		target = index;
		targetUntil = Date.now() + 700;
		list[index].scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
	}

	function ignored(event) {
		if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) {
			return true;
		}
		var el = event.target;
		if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT|BUTTON|VIDEO|AUDIO)$/.test(el.tagName))) {
			return true;
		}
		return blockers !== '' && document.querySelector(blockers) !== null;
	}

	document.addEventListener('keydown', function (event) {
		if (ignored(event)) {
			return;
		}
		var list = slides();
		if (!list.length) {
			return;
		}
		var scrolling = target !== null && Date.now() < targetUntil;
		var current = scrolling ? target : currentIndex(list);
		var partlyScrolled = !scrolling && list[current].getBoundingClientRect().top < -5;
		var forward;

		switch (event.key) {
			case 'ArrowDown': case 'PageDown': case 'ArrowRight': case 'j':
				forward = true; break;
			case 'ArrowUp': case 'PageUp': case 'ArrowLeft': case 'k':
				forward = false; break;
			case ' ': case 'Spacebar':
				forward = !event.shiftKey; break;
			case 'Home':
				event.preventDefault(); go(list, 0); return;
			case 'End':
				event.preventDefault(); go(list, list.length - 1); return;
			default:
				return;
		}
		event.preventDefault();
		if (!forward && partlyScrolled) {
			go(list, current);
		} else {
			go(list, step(list, current, forward ? 1 : -1));
		}
	});

	// Next photo in a direction that starts at a different height: photos laid out side by side
	// in a row (e.g. a width: 32.5 grid) count as one stop
	function step(list, from, direction) {
		var top = list[from].getBoundingClientRect().top;
		var i = from + direction;
		while (i >= 0 && i < list.length && Math.abs(list[i].getBoundingClientRect().top - top) <= 5) {
			i += direction;
		}
		// Going back, land on the first photo of that row
		if (direction < 0 && i >= 0) {
			var rowTop = list[i].getBoundingClientRect().top;
			while (i > 0 && Math.abs(list[i - 1].getBoundingClientRect().top - rowTop) <= 5) {
				i--;
			}
		}
		return i;
	}
})();
