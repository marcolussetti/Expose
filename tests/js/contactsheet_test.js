// Tests for the contactsheet theme's contactsheet.js (#28), run by tests/test_themes.py (needs
// node). Loads it without a DOM, so only the pure parts on window.contactsheet run.
'use strict';

const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const SOURCE = fs.readFileSync(process.argv[2], 'utf8');
const window = {};
vm.runInNewContext(SOURCE, { window, Math, Number, String });
const cs = window.contactsheet;

// A lightbox over `count` items that records what it was asked to draw
function lightbox(count) {
	const calls = [];
	const box = new cs.Lightbox(count, {
		show: (index, opening) => calls.push(opening ? `open ${index}` : `show ${index}`),
		hide: (index) => calls.push(`hide ${index}`),
	});
	return { box, calls };
}

const tests = {
	'resolutions: the config widths, smallest first'() {
		assert.deepStrictEqual(Array.from(cs.resolutions('3840 1024 640 1920')), [640, 1024, 1920, 3840]);
		assert.deepStrictEqual(Array.from(cs.resolutions(' 1024 ')), [1024]);
		assert.deepStrictEqual(Array.from(cs.resolutions('')), []);
		assert.deepStrictEqual(Array.from(cs.resolutions(undefined)), []);
	},
	'pickWidth: the smallest encoded width that is enough'() {
		const widths = [640, 1024, 1920, 3840];
		assert.strictEqual(cs.pickWidth(widths, 3840, 700), 1024);
		assert.strictEqual(cs.pickWidth(widths, 3840, 1024), 1024);
		assert.strictEqual(cs.pickWidth(widths, 3840, 100), 640);
		// never more than the item has
		assert.strictEqual(cs.pickWidth(widths, 1920, 3000), 1920);
		// an item smaller than every width only has the smallest
		assert.strictEqual(cs.pickWidth(widths, 640, 3000), 640);
		assert.strictEqual(cs.pickWidth([1024], 1024, 50), 1024);
	},
	'fitWidth: the width of an item fitted into the screen'() {
		assert.strictEqual(cs.fitWidth(1600, 1000, 1000, 1000), 1000); // wide: fills the width
		assert.strictEqual(cs.fitWidth(1000, 2000, 1000, 800), 400); // tall: fills the height
		assert.strictEqual(cs.fitWidth(0, 0, 1000, 800), 1000);
	},
	'rowSpan: enough grid rows for a tile'() {
		// 4px rows, 8px gaps: a row and its gap take 12px
		assert.strictEqual(cs.rowSpan(100, 4, 8), 9); // (100 + 8) / 12
		assert.strictEqual(cs.rowSpan(101, 4, 8), 10);
		assert.strictEqual(cs.rowSpan(0, 4, 8), 1);
		assert.strictEqual(cs.rowSpan(10, 4, 0), 3);
	},
	'swipe: sideways far enough is next or previous'() {
		assert.strictEqual(cs.swipe(-120, 10), 'next');
		assert.strictEqual(cs.swipe(120, -10), 'previous');
		assert.strictEqual(cs.swipe(-30, 0), null); // too short
		assert.strictEqual(cs.swipe(-80, 200), null); // mostly vertical: scrolling the caption
	},
	'lightbox opens, steps through the items and closes'() {
		const { box, calls } = lightbox(4);
		assert.strictEqual(box.isOpen(), false);
		box.open(1);
		assert.strictEqual(box.isOpen(), true);
		assert.strictEqual(box.handle('next'), true);
		assert.strictEqual(box.handle('previous'), true);
		box.handle('last');
		box.handle('first');
		box.close();
		assert.deepStrictEqual(calls, ['open 1', 'show 2', 'show 1', 'show 3', 'show 0', 'hide 0']);
		assert.strictEqual(box.isOpen(), false);
	},
	'lightbox stops at the first and last item'() {
		const { box, calls } = lightbox(2);
		box.open(0);
		box.handle('previous');
		box.handle('first');
		box.handle('next');
		box.handle('next');
		box.handle('last');
		assert.deepStrictEqual(calls, ['open 0', 'show 1']);
	},
	'lightbox ignores other actions, and moving while closed'() {
		const { box, calls } = lightbox(3);
		assert.strictEqual(box.handle(null), false);
		box.handle('next');
		box.close();
		assert.deepStrictEqual(calls, []);
		box.open(9); // out of range: the last one
		assert.deepStrictEqual(calls, ['open 2']);
		assert.strictEqual(lightbox(0).box.open(0), undefined);
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
