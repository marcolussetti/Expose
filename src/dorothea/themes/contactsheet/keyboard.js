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
 *
 * The same keys are available to a theme's own viewer as window.dorotheaKeys.action(event), which
 * says 'next', 'previous', 'first', 'last' or null. data-slides="" scrolls nothing (contactsheet
 * only uses them in its lightbox, #28).
 *
 * Shared by the photoessay, medium and contactsheet themes: keep the copies identical.
 */
(function () {
	var script = document.currentScript;
	var attribute = script ? script.getAttribute('data-slides') : null;
	var selector = attribute === null ? '.slide' : attribute;
	var blockers = (script && script.getAttribute('data-blocked-by')) || '';
	var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

	// While a smooth scroll is running, keep counting from where it's going, not where it is
	var target = null;
	var targetUntil = 0;

	function slides() {
		return selector ? Array.prototype.slice.call(document.querySelectorAll(selector)) : [];
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

	// What a key press asks for, or null for other keys, with a modifier, or while typing
	function action(event) {
		if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) {
			return null;
		}
		var el = event.target;
		if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT|BUTTON|VIDEO|AUDIO)$/.test(el.tagName))) {
			return null;
		}
		switch (event.key) {
			case 'ArrowDown': case 'PageDown': case 'ArrowRight': case 'j':
				return 'next';
			case 'ArrowUp': case 'PageUp': case 'ArrowLeft': case 'k':
				return 'previous';
			case ' ': case 'Spacebar':
				return event.shiftKey ? 'previous' : 'next';
			case 'Home':
				return 'first';
			case 'End':
				return 'last';
			default:
				return null;
		}
	}

	window.dorotheaKeys = { action: action };

	document.addEventListener('keydown', function (event) {
		var wanted = action(event);
		if (wanted === null || (blockers !== '' && document.querySelector(blockers) !== null)) {
			return;
		}
		var list = slides();
		if (!list.length) {
			return;
		}
		event.preventDefault();
		if (wanted === 'first') {
			go(list, 0);
			return;
		}
		if (wanted === 'last') {
			go(list, list.length - 1);
			return;
		}
		var scrolling = target !== null && Date.now() < targetUntil;
		var current = scrolling ? target : currentIndex(list);
		var partlyScrolled = !scrolling && list[current].getBoundingClientRect().top < -5;
		if (wanted === 'previous' && partlyScrolled) {
			go(list, current);
		} else {
			go(list, step(list, current, wanted === 'next' ? 1 : -1));
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
