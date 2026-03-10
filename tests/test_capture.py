"""Tests for Phase 6: Network and console capture."""

from pawgrab.engine.capture import ConsoleCapture, NetworkCapture


class MockRequest:
    def __init__(self, url, method="GET", resource_type="document"):
        self.url = url
        self.method = method
        self.resource_type = resource_type
        self.headers = {"accept": "text/html"}


class MockResponse:
    def __init__(self, url, status=200):
        self.url = url
        self.status = status
        self.headers = {"content-type": "text/html"}


class MockConsoleMessage:
    def __init__(self, msg_type, text):
        self.type = msg_type
        self.text = text


class TestNetworkCapture:
    def test_captures_request_response_pair(self):
        cap = NetworkCapture()
        req = MockRequest("https://example.com/page")
        cap.on_request(req)
        resp = MockResponse("https://example.com/page", 200)
        cap.on_response(resp)

        results = cap.get_results()
        assert len(results) == 1
        assert results[0]["url"] == "https://example.com/page"
        assert results[0]["method"] == "GET"
        assert results[0]["response_status"] == 200
        assert "response_time_ms" in results[0]

    def test_request_count(self):
        cap = NetworkCapture()
        for i in range(3):
            req = MockRequest(f"https://example.com/{i}")
            cap.on_request(req)
            resp = MockResponse(f"https://example.com/{i}")
            cap.on_response(resp)
        assert cap.request_count == 3


class TestConsoleCapture:
    def test_captures_messages(self):
        cap = ConsoleCapture()
        cap.on_console(MockConsoleMessage("log", "hello"))
        cap.on_console(MockConsoleMessage("error", "something broke"))

        results = cap.get_results()
        assert len(results) == 2
        assert results[0]["type"] == "log"
        assert results[0]["text"] == "hello"
        assert results[1]["type"] == "error"
