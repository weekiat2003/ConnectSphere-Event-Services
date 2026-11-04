"""Serve the built Vue app for the e2e tests, like `python -m http.server`,
but with the single-page-app fallback a real web server would have.

`python -m http.server` returns 404 for a deep link such as /drafts or
/events/12, because no such file exists. The Vue router uses HTML5 history
URLs, so any path that is not a real file must return index.html and let the
router take over.

Usage: python e2e/spa_server.py <port> <directory>
       e.g. python e2e/spa_server.py 5173 staged/frontend
"""
import functools
import http.server
import os
import sys


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        path = self.translate_path(self.path)
        if not os.path.exists(path):
            self.path = "/index.html"
        return super().send_head()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5173
    directory = sys.argv[2] if len(sys.argv) > 2 else "."
    handler = functools.partial(SPAHandler, directory=directory)
    with http.server.ThreadingHTTPServer(("", port), handler) as server:
        print(f"Serving {directory} on port {port} with SPA fallback")
        server.serve_forever()


if __name__ == "__main__":
    main()
