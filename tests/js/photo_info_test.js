// Tests for the themes' photo-info.js (#20), run by tests/test_themes.py (needs node).
// A stub DOM: .photo-info boxes, each with a button and a panel; events are dispatched to the
// document's listeners the way the browser would call them.
'use strict';

const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const SOURCE = fs.readFileSync(process.argv[2], 'utf8');

function element(classes, parent) {
	const el = {
		parent,
		attrs: {},
		blurred: false,
		classes: new Set(classes),
		classList: {
			contains: (c) => el.classes.has(c),
			toggle: (c, on) => { if (on) { el.classes.add(c); } else { el.classes.delete(c); } },
		},
		setAttribute: (name, value) => { el.attrs[name] = value; },
		blur: () => { el.blurred = true; },
		closest(selector) {
			const wanted = selector.replace('.', '');
			for (let node = el; node; node = node.parent) {
				if (node.classes.has(wanted)) { return node; }
			}
			return null;
		},
	};
	return el;
}

function page(count) {
	const listeners = {};
	const body = element(['body'], null);
	const infos = [];
	for (let i = 0; i < count; i++) {
		const info = element(['photo-info'], body);
		info.button = element(['photo-info-button'], info);
		info.panel = element(['photo-info-panel'], info);
		info.querySelector = () => info.button;
		infos.push(info);
	}
	const document = {
		activeElement: body,
		querySelectorAll: (selector) => infos.filter((info) => selector !== '.photo-info.pinned' || info.classes.has('pinned')),
		addEventListener: (type, fn, capture) => { listeners[type] = { fn, capture }; },
	};
	vm.runInNewContext(SOURCE, { document });

	function click(target) {
		const event = { target, stopped: false, prevented: false,
			stopPropagation() { this.stopped = true; }, preventDefault() { this.prevented = true; } };
		listeners.click.fn(event);
		return event;
	}
	function key(name) {
		listeners.keydown.fn({ key: name });
	}
	return { infos, body, document, click, key, listeners };
}

const pinned = (info) => info.classes.has('pinned');

const tests = {
	'clicks are handled in the capture phase'() {
		assert.strictEqual(page(1).listeners.click.capture, true);
	},
	'a click pins the panel, a second one unpins and blurs'() {
		const p = page(1);
		const [info] = p.infos;
		const event = p.click(info.button);
		assert.ok(pinned(info));
		assert.strictEqual(info.button.attrs['aria-expanded'], 'true');
		assert.ok(event.stopped, "the photo's own click handler must not run");
		p.click(info.button);
		assert.ok(!pinned(info));
		assert.strictEqual(info.button.attrs['aria-expanded'], 'false');
		assert.ok(info.button.blurred);
	},
	'pinning one closes the others'() {
		const p = page(2);
		p.click(p.infos[0].button);
		p.click(p.infos[1].button);
		assert.ok(!pinned(p.infos[0]));
		assert.ok(pinned(p.infos[1]));
	},
	'clicks in the panel keep it open and stay there'() {
		const p = page(1);
		p.click(p.infos[0].button);
		const event = p.click(p.infos[0].panel);
		assert.ok(pinned(p.infos[0]));
		assert.ok(event.stopped);
	},
	'a click elsewhere closes it and passes through'() {
		const p = page(1);
		p.click(p.infos[0].button);
		const event = p.click(p.body);
		assert.ok(!pinned(p.infos[0]));
		assert.ok(!event.stopped && !event.prevented);
	},
	'Escape closes it'() {
		const p = page(1);
		p.click(p.infos[0].button);
		p.document.activeElement = p.infos[0].button;
		p.key('Escape');
		assert.ok(!pinned(p.infos[0]));
		assert.ok(p.infos[0].button.blurred);
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
