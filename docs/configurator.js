/*
 * The configurator on the Configuration page (#30): a form built from the JSON Schema
 * (schema/config.json, written by scripts/build_schema.py) that makes a _config.json holding only
 * the settings that differ from the defaults, so future improvements to the defaults still apply.
 *
 * The functions before mount() hold the logic and are tested with node
 * (tests/js/configurator_test.js); mount() builds the form in the browser.
 */
(function () {
	'use strict';

	var SCHEMA_URL = 'https://dorothea.readthedocs.io/schema/config.json';

	function same(a, b) {
		return JSON.stringify(a) === JSON.stringify(b);
	}

	// [key, property] for each setting, in the docs' order. `legacy` is the "Start from" switch.
	function settings(schema) {
		return Object.keys(schema.properties)
			.filter(function (key) { return key !== '$schema' && key !== 'legacy'; })
			.map(function (key) { return [key, schema.properties[key]]; });
	}

	function defaults(schema, legacy) {
		var result = {};
		settings(schema).forEach(function (entry) {
			result[entry[0]] = legacy ? entry[1]['x-legacy-default'] : entry[1].default;
		});
		return result;
	}

	function show(value) {
		return Array.isArray(value) ? value.join(', ') : typeof value === 'string' ? '"' + value + '"' : String(value);
	}

	// Why a value doesn't fit a schema property, or '' if it does
	function check(prop, value) {
		var type = prop.type;
		if (type === 'boolean' && typeof value !== 'boolean') { return 'must be true or false'; }
		if (type === 'integer' && !Number.isInteger(value)) { return 'must be a whole number'; }
		if (type === 'number' && (typeof value !== 'number' || !isFinite(value))) { return 'must be a number'; }
		if (type === 'string' && typeof value !== 'string') { return 'must be text'; }
		if (type === 'array' && !Array.isArray(value)) { return 'must be a list'; }

		if (prop.enum && prop.enum.indexOf(value) < 0) { return 'must be one of ' + prop.enum.join(', '); }
		if (prop.minimum !== undefined && value < prop.minimum) { return 'must be at least ' + prop.minimum; }
		if (prop.maximum !== undefined && value > prop.maximum) { return 'must be at most ' + prop.maximum; }
		if (prop.exclusiveMinimum !== undefined && value <= prop.exclusiveMinimum) {
			return 'must be more than ' + prop.exclusiveMinimum;
		}
		if (prop.minLength !== undefined && value.length < prop.minLength) { return "can't be empty"; }
		if (prop.pattern && !new RegExp(prop.pattern, 'u').test(value)) {
			return prop['x-input'] === 'color' ? 'must be a CSS colour' : "isn't in the right format";
		}

		if (type === 'array') {
			if (prop.minItems !== undefined && value.length < prop.minItems) { return 'needs at least ' + prop.minItems + ' value(s)'; }
			if (prop.uniqueItems && new Set(value).size !== value.length) { return 'has the same value twice'; }
			for (var i = 0; i < value.length; i++) {
				var error = check(prop.items || {}, value[i]);
				if (error) { return show(value[i]) + ' ' + error; }
			}
		}
		return '';
	}

	// Split a comma-separated list, keeping commas inside brackets: "rgba(0,0,0,.5), #fff"
	function splitList(text) {
		var items = [], depth = 0, current = '';
		for (var i = 0; i < text.length; i++) {
			var ch = text[i];
			if (ch === '(') { depth++; } else if (ch === ')') { depth--; }
			if (ch === ',' && depth <= 0) {
				items.push(current);
				current = '';
			} else {
				current += ch;
			}
		}
		items.push(current);
		return items.map(function (item) { return item.trim(); }).filter(function (item) { return item !== ''; });
	}

	function parseScalar(type, text) {
		text = text.trim();
		if (type === 'integer' || type === 'number') {
			return text === '' ? NaN : Number(text);
		}
		return text;
	}

	// A field's text → {value} or {error}
	function parseField(prop, text) {
		var value;
		if (prop.type === 'array') {
			var itemType = (prop.items || {}).type;
			value = splitList(text).map(function (item) { return parseScalar(itemType, item); });
		} else {
			value = parseScalar(prop.type, text);
		}
		var error = check(prop, value);
		return error ? { error: error } : { value: value };
	}

	// The config file: "$schema", "legacy" if starting from expose.sh's defaults, then only the
	// settings that differ from the defaults it starts from
	function configFor(schema, legacy, values) {
		var base = defaults(schema, legacy);
		var config = { $schema: SCHEMA_URL };
		if (legacy) { config.legacy = true; }
		settings(schema).forEach(function (entry) {
			var key = entry[0];
			if (Object.prototype.hasOwnProperty.call(values, key) && !same(values[key], base[key])) {
				config[key] = values[key];
			}
		});
		return config;
	}

	// JSON with short lists on one line: "resolution": [2560, 1280]
	function format(config) {
		return JSON.stringify(config, null, 2).replace(/\[\n\s*([^\[\]{}]*?)\n\s*\]/g, function (match, inner) {
			return '[' + inner.split(/,\n\s*/).join(', ') + ']';
		}) + '\n';
	}

	// An existing _config.json → {legacy, values, warnings}; throws an Error if it isn't JSON
	function importConfig(schema, text) {
		var data = JSON.parse(text);
		if (!data || typeof data !== 'object' || Array.isArray(data)) {
			throw new Error('expected a JSON object: { "key": value, … }');
		}
		var result = { legacy: data.legacy === true, values: {}, warnings: [] };
		Object.keys(data).forEach(function (key) {
			if (key === '$schema' || key === 'legacy') { return; }
			var prop = schema.properties[key];
			if (!prop) {
				result.warnings.push('Unknown setting ' + key + ' left out (a typo?)');
				return;
			}
			var error = check(prop, data[key]);
			if (error) {
				result.warnings.push(key + ' ' + error + '; left out');
			} else {
				result.values[key] = data[key];
			}
		});
		return result;
	}

	// ---- the form ----

	function element(tag, attrs, children) {
		var el = document.createElement(tag);
		Object.keys(attrs || {}).forEach(function (name) {
			if (name === 'text') { el.textContent = attrs[name]; } else if (name === 'html') { el.innerHTML = attrs[name]; } else { el.setAttribute(name, attrs[name]); }
		});
		(children || []).forEach(function (child) { if (child) { el.appendChild(child); } });
		return el;
	}

	function mount(root, schema) {
		var state = { legacy: false, values: {}, errors: {} };
		var fields = {};
		root.textContent = '';

		// Start from
		var start = element('fieldset', { class: 'cfg-start' }, [element('legend', { text: 'Start from' })]);
		[['dorothea', "Dorothea's defaults", false], ['legacy', "expose.sh's defaults (legacy)", true]].forEach(function (option) {
			var input = element('input', { type: 'radio', name: 'cfg-start', id: 'cfg-start-' + option[0] });
			input.checked = option[2] === state.legacy;
			input.addEventListener('change', function () { state.legacy = option[2]; refresh(); });
			start.appendChild(element('label', { for: input.id }, [input, document.createTextNode(' ' + option[1])]));
		});
		root.appendChild(start);

		// Import
		var importText = element('textarea', { rows: '6', 'aria-label': 'Existing _config.json', placeholder: '{ "site_title": "My trip" }' });
		var importMessage = element('p', { class: 'cfg-message', role: 'status' });
		var importButton = element('button', { type: 'button', class: 'md-button', text: 'Load' });
		importButton.addEventListener('click', function () {
			try {
				var loaded = importConfig(schema, importText.value);
				state.legacy = loaded.legacy;
				state.values = loaded.values;
				state.errors = {};
				document.getElementById(state.legacy ? 'cfg-start-legacy' : 'cfg-start-dorothea').checked = true;
				refresh(true);
				importMessage.textContent = 'Loaded ' + Object.keys(loaded.values).length + ' setting(s).' +
					(loaded.warnings.length ? ' ' + loaded.warnings.join('. ') + '.' : '');
			} catch (error) {
				importMessage.textContent = "Couldn't read it: " + error.message;
			}
		});
		root.appendChild(element('details', { class: 'cfg-import' }, [
			element('summary', { text: 'Edit an existing _config.json' }),
			importText, importButton, importMessage,
		]));

		// Settings, grouped by section (all open, so Ctrl+F finds any of them)
		var form = element('div', { class: 'cfg-form' });
		var sections = {};
		settings(schema).forEach(function (entry) {
			var section = entry[1]['x-section'];
			if (!sections[section]) {
				sections[section] = element('section', { class: 'cfg-section' }, [element('h3', { text: section })]);
				form.appendChild(sections[section]);
			}
			sections[section].appendChild(field(entry[0], entry[1]));
		});

		// Result
		var output = element('code');
		var summary = element('p', { class: 'cfg-message', role: 'status' });
		var copy = element('button', { type: 'button', class: 'md-button md-button--primary', text: 'Copy' });
		var download = element('button', { type: 'button', class: 'md-button', text: 'Download _config.json' });
		copy.addEventListener('click', function () {
			navigator.clipboard.writeText(output.textContent).then(function () { summary.textContent = 'Copied.'; });
		});
		download.addEventListener('click', function () {
			var link = element('a', { href: URL.createObjectURL(new Blob([output.textContent], { type: 'application/json' })), download: '_config.json' });
			link.click();
			URL.revokeObjectURL(link.href);
		});
		var result = element('aside', { class: 'cfg-output', 'aria-label': 'Your _config.json' }, [
			element('p', { class: 'cfg-output-title', text: '_config.json' }),
			element('pre', {}, [output]), copy, download, summary,
		]);

		root.appendChild(element('div', { class: 'cfg-layout' }, [form, result]));

		function field(key, prop) {
			var id = 'cfg-' + key;
			var control, input, swatch;
			if (prop.type === 'boolean') {
				input = control = element('input', { type: 'checkbox', id: id });
				input.addEventListener('change', function () { set(key, input.checked); });
			} else if (prop.enum) {
				input = control = element('select', { id: id }, prop.enum.map(function (choice) {
					return element('option', { value: choice, text: choice });
				}));
				input.addEventListener('change', function () { set(key, input.value); });
			} else {
				var number = prop.type === 'integer' || prop.type === 'number';
				input = element('input', { type: number ? 'number' : 'text', id: id, spellcheck: 'false' });
				if (number) {
					if (prop.minimum !== undefined) { input.min = prop.minimum; }
					if (prop.maximum !== undefined) { input.max = prop.maximum; }
					input.step = prop.type === 'integer' ? '1' : 'any';
				}
				var parse = function () {
					var parsed = parseField(prop, input.value);
					if (parsed.error) {
						// left out of the file until fixed, rather than keeping an earlier value
						delete state.values[key];
						state.errors[key] = parsed.error;
						refresh();
					} else {
						set(key, parsed.value);
					}
				};
				input.addEventListener('input', parse);
				control = input;
				if (prop.examples) {
					var list = element('datalist', { id: id + '-choices' }, prop.examples.map(function (choice) {
						return element('option', { value: choice });
					}));
					input.setAttribute('list', list.id);
					control = element('span', { class: 'cfg-control' }, [input, list]);
				}
				if (prop['x-input'] === 'color') {
					swatch = element('input', { type: 'color', 'aria-label': key + ' colour picker' });
					swatch.addEventListener('input', function () { input.value = swatch.value; parse(); });
					control = element('span', { class: 'cfg-control' }, [input, swatch]);
				}
			}

			var reset = element('button', { type: 'button', class: 'cfg-reset', text: 'reset' });
			reset.addEventListener('click', function () {
				delete state.values[key];
				delete state.errors[key];
				refresh(true);
			});
			var error = element('p', { class: 'cfg-error', id: id + '-error' });
			var info = element('p', { class: 'cfg-default' });
			input.setAttribute('aria-describedby', error.id);
			fields[key] = { prop: prop, input: input, swatch: swatch, info: info, error: error, reset: reset };

			return element('div', { class: 'cfg-field' }, [
				element('div', { class: 'cfg-label' }, [element('label', { for: id }, [element('code', { text: key })]), reset]),
				control, error, info,
				// HTML that build_schema.py rendered from docs/configuration.md, served with this page
				element('div', { class: 'cfg-description', html: prop.description || '' }),
			]);
		}

		function set(key, value) {
			state.values[key] = value;
			delete state.errors[key];
			refresh();
		}

		// Show the current values; `all` also rewrites the field being typed in (after an import)
		function refresh(all) {
			var base = defaults(schema, state.legacy);
			Object.keys(fields).forEach(function (key) {
				var f = fields[key];
				var has = Object.prototype.hasOwnProperty.call(state.values, key);
				var value = has ? state.values[key] : base[key];
				if (all || document.activeElement !== f.input) {
					if (f.prop.type === 'boolean') {
						f.input.checked = value;
					} else if (!(key in state.errors) || all) {
						f.input.value = Array.isArray(value) ? value.join(', ') : value;
					}
				}
				if (f.swatch && /^#[0-9a-fA-F]{6}$/.test(f.input.value)) { f.swatch.value = f.input.value; }
				var changed = has && !same(value, base[key]);
				f.input.closest('.cfg-field').classList.toggle('cfg-changed', changed);
				f.reset.hidden = !has && !(key in state.errors);
				f.error.textContent = state.errors[key] || '';
				f.info.textContent = 'Default: ' + show(base[key]);
			});

			var config = configFor(schema, state.legacy, state.values);
			output.textContent = format(config);
			var count = Object.keys(config).length - 1 - (state.legacy ? 1 : 0);
			var errors = Object.keys(state.errors).length;
			summary.textContent = (count ? count + ' setting(s) changed.' : 'Everything at its default so far.') +
				(errors ? ' ' + errors + ' field(s) need fixing and are left out.' : '');
		}

		refresh(true);
	}

	var api = {
		SCHEMA_URL: SCHEMA_URL, settings: settings, defaults: defaults, check: check,
		splitList: splitList, parseField: parseField, configFor: configFor, format: format,
		importConfig: importConfig,
	};

	if (typeof module === 'object' && module.exports) {
		module.exports = api;
	} else if (typeof document !== 'undefined') {
		var start = function () {
			var root = document.getElementById('configurator');
			if (!root) { return; }
			fetch(root.getAttribute('data-schema'))
				.then(function (response) { return response.json(); })
				.then(function (schema) { mount(root, schema); })
				.catch(function () {
					root.textContent = "The configurator couldn't load. The settings are listed below.";
				});
		};
		if (document.readyState === 'loading') {
			document.addEventListener('DOMContentLoaded', start);
		} else {
			start();
		}
	}
})();
