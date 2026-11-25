import sys

from spotiyutu.cli import app


def main():
    # If launched without arguments (e.g. double clicked in Windows Explorer), default to launching the Web UI!
    if len(sys.argv) == 1:
        sys.argv.append("ui")
    app()


if __name__ == "__main__":
    main()
