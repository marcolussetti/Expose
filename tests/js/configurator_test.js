// Tests for the docs' configurator logic (docs/configurator.js), run by
// tests/unit/test_configurator.py (needs node) with the schema scripts/build_schema.py builds.
'use strict';

const fs = require('fs');
const assert = require('assert');

const cfg = require(process.argv[2]);
const schema = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const prop = (key) => schema.properties[key];

const tests = {
	'defaults for both starting points'() {
		assert.strictEqual(cfg.defaults(schema, false).theme_dir, 'photoessay');
		assert.strictEqual(cfg.defaults(schema, true).theme_dir, 'theme1');
		assert.ok(!('legacy' in cfg.defaults(schema, false)), 'legacy is the switch, not a field');
	},
	'the file only has what differs from the defaults'() {
		const values = { theme_dir: 'photoessay', site_title: 'Iceland', jpeg_quality: 92 };
		assert.deepStrictEqual(cfg.configFor(schema, false, values), {
			$schema: cfg.SCHEMA_URL, site_title: 'Iceland',
		});
	},
	'starting from expose.sh adds legacy and compares with its defaults'() {
		const values = { theme_dir: 'photoessay', sort: 'name' };
		assert.deepStrictEqual(cfg.configFor(schema, true, values), {
			$schema: cfg.SCHEMA_URL, legacy: true, theme_dir: 'photoessay',
		});
	},
	'lists are compared by value'() {
		const config = cfg.configFor(schema, false, { video_formats: ['h264', 'vp9'], resolution: [1920, 640] });
		assert.deepStrictEqual(Object.keys(config), ['$schema', 'resolution']);
	},
	'output keeps short lists on one line'() {
		const text = cfg.format({ $schema: 'x', resolution: [1920, 640], default_palette: ['#000', 'rgba(0, 0, 0, .5)'] });
		assert.ok(text.includes('"resolution": [1920, 640]'), text);
		assert.ok(text.includes('"default_palette": ["#000", "rgba(0, 0, 0, .5)"]'), text);
		assert.deepStrictEqual(JSON.parse(text).default_palette, ['#000', 'rgba(0, 0, 0, .5)']);
	},
	'fields are parsed and checked'() {
		assert.deepStrictEqual(cfg.parseField(prop('jpeg_quality'), ' 85 '), { value: 85 });
		assert.ok(cfg.parseField(prop('jpeg_quality'), '101').error.includes('at most 100'));
		assert.ok(cfg.parseField(prop('jpeg_quality'), '').error);
		assert.ok(cfg.parseField(prop('jpeg_quality'), '8.5').error.includes('whole number'));
		assert.deepStrictEqual(cfg.parseField(prop('resolution'), '2560, 1280,640'), { value: [2560, 1280, 640] });
		assert.ok(cfg.parseField(prop('resolution'), '').error.includes('at least 1'));
		assert.ok(cfg.parseField(prop('resolution'), '1920, 0').error.includes('0 must be at least 1'));
		assert.deepStrictEqual(cfg.parseField(prop('bitrate'), '12.5, 2'), { value: [12.5, 2] });
		assert.ok(cfg.parseField(prop('video_formats'), 'h264, av1').error.includes('"av1" must be one of'));
		assert.ok(cfg.parseField(prop('video_formats'), 'h264, h264').error.includes('twice'));
		assert.ok(cfg.parseField(prop('site_url'), 'example.com').error);
		assert.deepStrictEqual(cfg.parseField(prop('site_url'), 'https://example.com/'), { value: 'https://example.com/' });
		assert.deepStrictEqual(cfg.parseField(prop('site_url'), ''), { value: '' });
		assert.ok(cfg.parseField(prop('ffmpeg'), '').error);
	},
	'colour lists keep commas inside brackets'() {
		assert.deepStrictEqual(cfg.splitList('rgba(0,0,0,.5), #fff ,'), ['rgba(0,0,0,.5)', '#fff']);
	},
	'importing a config'() {
		const loaded = cfg.importConfig(schema, JSON.stringify({
			$schema: cfg.SCHEMA_URL, legacy: true, site_title: 'Iceland', site_titel: 'typo', jpeg_quality: 500,
		}));
		assert.strictEqual(loaded.legacy, true);
		assert.deepStrictEqual(loaded.values, { site_title: 'Iceland' });
		assert.strictEqual(loaded.warnings.length, 2);
		assert.ok(loaded.warnings[0].includes('site_titel'));
		assert.ok(loaded.warnings[1].includes('jpeg_quality must be at most 100'));
	},
	'an import round-trips'() {
		const values = { site_title: 'Iceland', resolution: [2560, 640], exif_display: 'caption' };
		const text = cfg.format(cfg.configFor(schema, false, values));
		const loaded = cfg.importConfig(schema, text);
		assert.deepStrictEqual(loaded.values, values);
		assert.deepStrictEqual(loaded.warnings, []);
	},
	'importing something that is not a config'() {
		assert.throws(() => cfg.importConfig(schema, '[1, 2]'), /JSON object/);
		assert.throws(() => cfg.importConfig(schema, '{ site_title: x }'));
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
