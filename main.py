"""Launch the first MVP; --prototype retains the original demonstration."""

from pathlib import Path
import sys


def main() -> int:
    if "--prototype" in sys.argv[1:]:
        sys.argv.remove("--prototype")
        print("Historical scripted prototype: not a general firmware/circuit simulator.")
        from main_prototype import main as prototype_main
        return prototype_main()
    here = Path(__file__).resolve()
    # A pyvsm clone beside this one first, then the original local layout.
    for package_root in (here.parents[1] / "pyvsm", here.parents[2] / "VSM_Python" / "pyvsm_replica"):
        if (package_root / "pyvsm" / "__main__.py").is_file():
            sys.path.insert(0, str(package_root))
            break
    try:
        from pyvsm.__main__ import main as mvp_main
    except ImportError:
        raise SystemExit(
            "MVP package missing: clone the pyvsm repository beside this folder, "
            "or install it (python -m pip install <path-to-pyvsm>) and run python -m pyvsm."
        ) from None
    return mvp_main()


if __name__ == "__main__":
    raise SystemExit(main())

