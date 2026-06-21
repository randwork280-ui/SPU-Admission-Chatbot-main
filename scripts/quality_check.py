from __future__ import annotations

import argparse
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {
    ".git",
    ".github",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "qdrant_storage",
    "venv",
}


def iter_python_files() -> Iterable[Path]:
    for path in ROOT.rglob("*.py"):
        if any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts):
            continue
        yield path


def compile_python() -> None:
    failures: List[str] = []
    for path in iter_python_files():
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"{path.relative_to(ROOT)}: {exc.msg}")
    if failures:
        raise RuntimeError("Python compile failed:\n" + "\n".join(failures))
    print("Python compile passed")


def run_command(command: List[str], cwd: Path = ROOT) -> None:
    print("+ " + " ".join(command))
    subprocess.run(command, cwd=str(cwd), check=True)


def frontend_available() -> bool:
    return (ROOT / "Services" / "spu-ai-connect-main" / "package.json").exists()


def frontend_build_command() -> List[str]:
    if shutil.which("npm"):
        return ["npm", "run", "build"]
    if shutil.which("pnpm"):
        return ["pnpm", "run", "build"]
    raise RuntimeError("Frontend build requested, but neither npm nor pnpm is available in PATH")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local quality checks for the SPU chatbot.")
    parser.add_argument(
        "--frontend-build",
        action="store_true",
        help="Also run npm build in the frontend directory. Requires dependencies to be installed.",
    )
    args = parser.parse_args()

    try:
        compile_python()
        run_command([sys.executable, "scripts/check_encoding.py"])
        run_command([sys.executable, "evaluate_system.py", "--validate-only"])
        run_command([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"])
        if args.frontend_build:
            if not frontend_available():
                raise RuntimeError("Frontend package.json not found")
            run_command(frontend_build_command(), cwd=ROOT / "Services" / "spu-ai-connect-main")
    except subprocess.CalledProcessError as exc:
        return exc.returncode or 1
    except Exception as exc:
        print(f"Quality check failed: {exc}", file=sys.stderr)
        return 1

    print("Quality check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
