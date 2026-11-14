"""python -m studio --platform http://127.0.0.1:8700 [--host 127.0.0.1] [--port 8950]"""

import argparse

from .server import serve


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m studio", description="Autology Studio (interim workspace shell)")
    p.add_argument("--platform", required=True, help="the Autology platform's base URL, e.g. http://127.0.0.1:8700")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8950)
    a = p.parse_args()
    serve(a.platform, a.host, a.port)


if __name__ == "__main__":  # pragma: no cover
    main()
