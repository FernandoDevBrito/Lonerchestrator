"""What every part of the web API shares: the error type and the route table.

A handler is registered where it is written:

    @route("POST", "/api/move", takes="body")
    def move(self, body): ...

`takes` says what the handler receives: nothing, the JSON body ("body"), the ?card= query value ("card"), the rest of the path after a prefix route
("tail"), or that rest and the whole query as a dict ("tailq")."""
import re

ID = re.compile(r"^[\w.-]{1,80}$")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")           # colour codes in an agent's output: shown as plain text on the page
ROUTES = {}                                              # (method, path) -> (handler name, takes)


class Bad(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def route(method, path, takes=None):
    def register(fn):
        ROUTES[(method, path)] = (fn.__name__, takes)
        return fn
    return register


def find_route(method, path):
    """(handler name, takes, tail) for a request, or None. A path ending in "/" in the table is a prefix route (the tail is what follows it)."""
    hit = ROUTES.get((method, path))
    if hit and hit[1] not in ("tail", "tailq"):        # a prefix route needs something after the prefix
        return hit[0], hit[1], None
    for (m, p), (name, takes) in ROUTES.items():
        if m == method and p.endswith("/") and path.startswith(p) and len(path) > len(p):
            return name, takes, path[len(p):]
    return None
