// Tests for the themes' keyboard.js, run by tests/test_keyboard_js.py (needs node).
// A stub DOM: "slides" at fixed page offsets; scrollIntoView jumps the page there.
'use strict';

const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const SOURCE = fs.readFileSync(process.argv[2], 'utf8');

function page(offsets, { attrs = {}, blocked = false } = {}) {
	let scrollY = 0;
	let now = 1000;
	let handler = null;
	const slides = offsets.map((offset) => ({
		getBoundingClientRect: () => ({ top: offset - scrollY }),
		scrollIntoView: () => { scrollY = offset; },
	}));
	const document = {
		currentScript: { getAttribute: (name) => (name in attrs ? attrs[name] : null) },
		querySelectorAll: () => slides,
		querySelector: () => (blocked ? {} : null),
		addEventListener: (type, fn) => { if (type === 'keydown') handler = fn; },
	};
	const context = {
		document,
		window: { matchMedia: () => ({ matches: false }) },
		Date: { now: () => now },
		Math,
		Array,
	};
	vm.runInNewContext(SOURCE, context);

	function press(key, extra = {}) {
		let prevented = false;
		handler({
			key,
			shiftKey: false, altKey: false, ctrlKey: false, metaKey: false,
			defaultPrevented: false,
			target: { tagName: 'BODY', isContentEditable: false },
			preventDefault: () => { prevented = true; },
			...extra,
		});
		return prevented;
	}
	return {
		press,
		get y() { return scrollY; },
		scrollTo(y) { scrollY = y; },
		wait() { now += 1000; }, // let any smooth scroll "finish"
	};
}

const tests = {
	'next and previous keys step through photos'() {
		const p = page([0, 1000, 2000, 3000]);
		for (const key of ['ArrowDown', 'PageDown', 'ArrowRight']) { p.press(key); }
		assert.strictEqual(p.y, 3000);
		p.wait();
		for (const key of ['ArrowUp', 'PageUp', 'ArrowLeft']) { p.press(key); }
		assert.strictEqual(p.y, 0);
		p.press('j'); p.press('j'); p.press('k');
		assert.strictEqual(p.y, 1000);
	},
	'space and shift+space'() {
		const p = page([0, 1000, 2000]);
		p.press(' ');
		assert.strictEqual(p.y, 1000);
		p.wait();
		p.press(' ', { shiftKey: true });
		assert.strictEqual(p.y, 0);
	},
	'home and end'() {
		const p = page([0, 1000, 2000, 3000]);
		p.press('End');
		assert.strictEqual(p.y, 3000);
		p.press('Home');
		assert.strictEqual(p.y, 0);
	},
	'stops at the first and last photo'() {
		const p = page([0, 1000]);
		p.press('k');
		assert.strictEqual(p.y, 0);
		p.press('End'); p.wait(); p.press('j');
		assert.strictEqual(p.y, 1000);
	},
	'counts from where a smooth scroll is heading'() {
		const p = page([0, 1000, 2000, 3000]);
		p.press('j');
		p.scrollTo(400); // animation still under way
		p.press('j');
		assert.strictEqual(p.y, 2000);
	},
	'previous returns to the top of a partly scrolled photo first'() {
		const p = page([0, 1000, 2000]);
		p.scrollTo(1500);
		p.press('ArrowUp');
		assert.strictEqual(p.y, 1000);
		p.wait();
		p.press('ArrowUp');
		assert.strictEqual(p.y, 0);
	},
	'photos side by side in a row are one stop'() {
		const p = page([0, 0, 0, 800, 800, 1600]);
		p.press('j');
		assert.strictEqual(p.y, 800);
		p.wait(); p.press('j');
		assert.strictEqual(p.y, 1600);
		p.wait(); p.press('k');
		assert.strictEqual(p.y, 800);
		p.wait(); p.press('k');
		assert.strictEqual(p.y, 0);
	},
	'leaves other keys, modifiers and typing alone'() {
		const p = page([0, 1000]);
		assert.strictEqual(p.press('a'), false);
		assert.strictEqual(p.press('j', { ctrlKey: true }), false);
		assert.strictEqual(p.press('j', { target: { tagName: 'INPUT', isContentEditable: false } }), false);
		assert.strictEqual(p.press('j', { target: { tagName: 'DIV', isContentEditable: true } }), false);
		assert.strictEqual(p.y, 0);
	},
	'paused while a full-screen viewer is open'() {
		const p = page([0, 1000], { attrs: { 'data-blocked-by': '#fullscreen.active' }, blocked: true });
		assert.strictEqual(p.press('j'), false);
		assert.strictEqual(p.y, 0);
	},
};

let failed = 0;
for (const [name, test] of Object.entries(tests)) {
	try {
		test();
		console.log(`ok - ${name}`);
	} catch (error) {
		failed += 1;
		console.log(`FAIL - ${name}\n  ${error.message}`);
	}
}
process.exit(failed ? 1 : 0);
