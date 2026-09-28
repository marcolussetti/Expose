/*
 * Photo details (#20): the ⓘ button the builder puts on each photo with exif_display: icon.
 *
 * Hovering or focusing the button shows its panel (that part is in the stylesheet). A click or
 * tap pins the panel open, which is how touch screens see it; clicking it again, clicking
 * anywhere else or pressing Escape closes it.
 *
 * Shared by the photoessay, medium and contactsheet themes: keep the copies identical.
 */
(function () {
	'use strict';

	function find(target, selector) {
		return target && target.closest ? target.closest(selector) : null;
	}

	function setPinned(info, pinned) {
		info.classList.toggle('pinned', pinned);
		info.querySelector('.photo-info-button').setAttribute('aria-expanded', pinned ? 'true' : 'false');
	}

	function closeAll(except) {
		var open = document.querySelectorAll('.photo-info.pinned');
		for (var i = 0; i < open.length; i++) {
			if (open[i] !== except) {
				setPinned(open[i], false);
			}
		}
	}

	// Capture phase, so a click on the details never reaches the photo's own handlers (medium
	// and contactsheet open a photo full screen when it's clicked)
	document.addEventListener('click', function (event) {
		var info = find(event.target, '.photo-info');
		if (!info) {
			closeAll(null);
			return;
		}
		event.stopPropagation();
		var button = find(event.target, '.photo-info-button');
		if (button) {
			event.preventDefault();
			var pinned = !info.classList.contains('pinned');
			closeAll(info);
			setPinned(info, pinned);
			if (!pinned) {
				button.blur(); // or focus would keep showing it
			}
		}
	}, true);

	document.addEventListener('keydown', function (event) {
		if (event.key === 'Escape' || event.key === 'Esc') {
			closeAll(null);
			if (find(document.activeElement, '.photo-info')) {
				document.activeElement.blur();
			}
		}
	});
})();
