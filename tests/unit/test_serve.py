"""`dorothea serve` and the link_index_html setting (#6)."""

import http.client
import re
import threading
from contextlib import contextmanager
from unittest import mock

import pytest
from click.testing import CliRunner

from dorothea.cli import main
from dorothea.config import DEFAULT_CONFIG, EXPOSE_DEFAULTS, Config, ConfigError
from dorothea.serve import make_server
from tests.conftest import make_generator, make_test_image


@pytest.fixture
def site(tmp_path):
    site = tmp_path / "_site"
    (site / "nature" / "mountains").mkdir(parents=True)
    (site / "index.html").write_text("<p>home</p>")
    (site / "nature" / "mountains" / "index.html").write_text("<p>mountains</p>")
    (site / "clip.mp4").write_bytes(bytes(range(100)))
    return site


@contextmanager
def running(site):
    server = make_server(site, port=0)
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def get(port, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path, headers=headers or {})
    response = conn.getresponse()
    body = response.read()
    conn.close()
    return response, body


class TestServer:
    def test_serves_index_and_gallery_pages(self, site):
        with running(site) as port:
            response, body = get(port, "/")
            assert response.status == 200 and body == b"<p>home</p>"
            assert response.getheader("Cache-Control") == "no-cache"
            # a gallery link (a folder) redirects to the folder, which serves its index.html
            response, _ = get(port, "/nature/mountains")
            assert response.status == 301
            assert response.getheader("Location") == "/nature/mountains/"
            response, body = get(port, "/nature/mountains/")
            assert response.status == 200 and body == b"<p>mountains</p>"

    def test_whole_file_advertises_ranges(self, site):
        with running(site) as port:
            response, body = get(port, "/clip.mp4")
        assert response.status == 200 and body == bytes(range(100))
        assert response.getheader("Accept-Ranges") == "bytes"
        assert response.getheader("Content-Type") == "video/mp4"

    @pytest.mark.parametrize(
        ("header", "expected", "content_range"),
        [
            ("bytes=10-19", range(10, 20), "bytes 10-19/100"),
            ("bytes=90-", range(90, 100), "bytes 90-99/100"),
            ("bytes=95-500", range(95, 100), "bytes 95-99/100"),
            ("bytes=-5", range(95, 100), "bytes 95-99/100"),
        ],
    )
    def test_byte_ranges(self, site, header, expected, content_range):
        """Safari/iOS only plays video from servers that answer range requests."""
        with running(site) as port:
            response, body = get(port, "/clip.mp4", {"Range": header})
        assert response.status == 206
        assert body == bytes(expected)
        assert response.getheader("Content-Range") == content_range
        assert response.getheader("Content-Length") == str(len(expected))
        assert response.getheader("Content-Type") == "video/mp4"

    def test_unsatisfiable_range(self, site):
        with running(site) as port:
            response, body = get(port, "/clip.mp4", {"Range": "bytes=200-"})
        assert response.status == 416
        assert response.getheader("Content-Range") == "bytes */100"
        assert body == b""

    def test_malformed_range_serves_the_whole_file(self, site):
        with running(site) as port:
            response, body = get(port, "/clip.mp4", {"Range": "lines=1-2"})
        assert response.status == 200 and len(body) == 100

    def test_range_on_missing_file(self, site):
        with running(site) as port:
            response, _ = get(port, "/nope.mp4", {"Range": "bytes=0-1"})
        assert response.status == 404

    def test_logs_only_errors(self, site, capsys):
        with running(site) as port:
            get(port, "/")
            get(port, "/missing.jpg")
        err = capsys.readouterr().err
        assert "missing.jpg" in err
        assert '"GET / ' not in err


def invoke(argv, cwd, monkeypatch):
    """Run the CLI with the build and the server loop mocked."""
    monkeypatch.chdir(cwd)
    with (
        mock.patch("dorothea.cli.ExposeGenerator") as gen_class,
        mock.patch("signal.signal"),
        mock.patch("atexit.register"),
        mock.patch("dorothea.serve.run") as run,
    ):
        result = CliRunner().invoke(main, argv, prog_name="dorothea")
    return result, gen_class, run


class TestServeCommand:
    def test_builds_then_serves(self, site, monkeypatch):
        result, gen_class, run = invoke(["serve", "--port", "0"], site.parent, monkeypatch)
        assert result.exit_code == 0, result.output
        gen_class.return_value.run.assert_called_once()
        server, served = run.call_args.args
        assert served == site
        server.server_close()

    def test_no_build(self, site, monkeypatch):
        result, gen_class, run = invoke(
            ["serve", "--no-build", "--port", "0"], site.parent, monkeypatch
        )
        assert result.exit_code == 0, result.output
        gen_class.assert_not_called()
        run.call_args.args[0].server_close()

    def test_build_options_before_or_after_serve(self, site, monkeypatch):
        for argv in (["-d", "serve", "--port", "0"], ["serve", "-d", "--port", "0"]):
            result, gen_class, run = invoke(argv, site.parent, monkeypatch)
            assert result.exit_code == 0, result.output
            assert gen_class.call_args.kwargs["draft"] is True
            run.call_args.args[0].server_close()

    def test_nothing_to_serve(self, tmp_path, monkeypatch):
        result, _, run = invoke(["serve", "--no-build"], tmp_path, monkeypatch)
        assert result.exit_code == 2
        assert "no site to serve" in result.output
        run.assert_not_called()

    def test_port_in_use(self, site, monkeypatch):
        with running(site) as port:
            result, _, run = invoke(
                ["serve", "--no-build", "--port", str(port)], site.parent, monkeypatch
            )
        assert result.exit_code == 2
        assert f"can't listen on 127.0.0.1:{port}" in result.output
        run.assert_not_called()

    def test_dry_run_is_refused(self, site, monkeypatch):
        result, gen_class, _ = invoke(["serve", "-n"], site.parent, monkeypatch)
        assert result.exit_code == 2
        assert "--dry-run" in result.output
        gen_class.assert_not_called()

    def test_plain_build_still_works(self, tmp_path, monkeypatch):
        result, gen_class, run = invoke([], tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        gen_class.return_value.run.assert_called_once()
        run.assert_not_called()

    def test_help_lists_serve(self, tmp_path, monkeypatch):
        result, _, _ = invoke(["--help"], tmp_path, monkeypatch)
        assert "serve" in result.output
        result, _, _ = invoke(["serve", "--help"], tmp_path, monkeypatch)
        for flag in ("--port", "--bind", "--no-build", "--draft", "--set"):
            assert flag in result.output


class TestLinkIndexHtml:
    def _nav_links(self, tmp_path, **overrides):
        for gallery in ("nature/mountains", "nature/lakes", "city"):
            (tmp_path / gallery).mkdir(parents=True, exist_ok=True)
            make_test_image(tmp_path / gallery / "photo.jpg", 64, 48, "blue")
        gen = make_generator(tmp_path, overrides)
        gen.scan_directories()
        gen.read_files()
        gen.build_html()
        pages = {
            path: re.findall(r'<a href="([^"#]+)"><span>', path.read_text())
            for path in [
                tmp_path / "_site" / "index.html",
                tmp_path / "_site" / "nature" / "lakes" / "index.html",
            ]
        }
        return list(pages.values())

    def test_default_links_to_folders(self, tmp_path):
        root, lakes = self._nav_links(tmp_path)
        assert root == ["./city", "./nature/lakes", "./nature/mountains"]
        assert lakes == ["../../city", "../../nature/lakes", "../../nature/mountains"]

    def test_links_to_index_html(self, tmp_path):
        root, lakes = self._nav_links(tmp_path, link_index_html=True)
        assert root == [
            "./city/index.html",
            "./nature/lakes/index.html",
            "./nature/mountains/index.html",
        ]
        assert lakes == [
            "../../city/index.html",
            "../../nature/lakes/index.html",
            "../../nature/mountains/index.html",
        ]

    def test_off_in_both_default_sets(self):
        assert DEFAULT_CONFIG["link_index_html"] is False
        assert EXPOSE_DEFAULTS["link_index_html"] is False

    def test_must_be_a_bool(self, tmp_path):
        with pytest.raises(ConfigError, match="link_index_html must be true or false"):
            Config({**DEFAULT_CONFIG, "link_index_html": "yes"}).validate()
