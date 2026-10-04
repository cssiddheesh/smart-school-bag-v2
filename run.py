"""Start the Smart School Bag server.   Usage:  python run.py"""

import logging

from app import create_app

app = create_app()
log = logging.getLogger("ssb")


def main() -> None:
    host, port = app.config["HOST"], app.config["PORT"]
    try:
        from waitress import serve
    except ImportError:
        log.warning("waitress is not installed; using Flask's built-in threaded server "
                    "(fine for a demo, install waitress for everyday use).")
        app.run(host=host, port=port, threaded=True, debug=False, use_reloader=False)
        return
    log.info("Serving on http://%s:%s (waitress)", host, port)
    serve(app, host=host, port=port, threads=6, ident="smart-school-bag")


if __name__ == "__main__":
    main()
