"""
setup.py — One-time setup: checks Python version, installs dependencies,
verifies Ollama, creates materials folder.
Run once before using the agent: python setup.py
"""

import sys
import subprocess
import shutil
from pathlib import Path

def ensure_venv():
    print_step("Setting up virtual environment...")
    venv_path = Path(__file__).parent / ".venv"

    if not venv_path.exists():
        print("  Creating .venv ...")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_path)])
    else:
        print("  ✓ Virtual environment already exists.")

    if sys.platform == "win32":
        python_path = venv_path / "Scripts" / "python.exe"
    else:
        python_path = venv_path / "bin" / "python"

    return python_path

def print_step(msg: str):
    print(f"\n{'─'*50}")
    print(f"  {msg}")
    print('─'*50)


def check_python():
    print_step("Checking Python version...")
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        print(f"  ✗ Python 3.10+ required. You have {v.major}.{v.minor}")
        sys.exit(1)
    print(f"  ✓ Python {v.major}.{v.minor}.{v.micro}")


def install_dependencies(python_path):
    print_step("Installing Python dependencies...")

    req_file = Path(__file__).parent / "requirements.txt"
    if not req_file.exists():
        print("  ✗ requirements.txt not found!")
        sys.exit(1)

    subprocess.check_call([str(python_path), "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call([str(python_path), "-m", "pip", "install", "-r", str(req_file)])

    print("  ✓ All dependencies installed.")


def check_ollama():
    print_step("Checking Ollama installation...")
    if shutil.which("ollama"):
        print("  ✓ Ollama found in PATH.")
    else:
        print("  ✗ Ollama not found.")
        print()
        print("  Please install Ollama from: https://ollama.com/download")
        print()
        print("  macOS:   Download from https://ollama.com/download/mac")
        print("  Windows: Download from https://ollama.com/download/windows")
        print("  Linux:   curl -fsSL https://ollama.com/install.sh | sh")
        print()
        print("  After installing, run: ollama serve")
        print("  Then run this setup again: python setup.py")
        sys.exit(1)


def check_ollama_running():
    print_step("Checking if Ollama is running...")
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434", timeout=3)
        print("  ✓ Ollama server is running.")
    except Exception:
        print("  ⚠ Ollama server is not running.")
        print()
        print("  Start it in a separate terminal with: ollama serve")
        print()
        print("  On macOS, you can also open the Ollama app from Applications.")
        print()
        print("  Once it's running, start the agent with: python main.py")
        print("  (The agent will download the model automatically on first run.)")


def create_materials_folder():
    print_step("Setting up materials folder...")
    folder = Path(__file__).parent / "materials"
    folder.mkdir(exist_ok=True)

    readme = folder / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Study Materials\n\n"
            "Put your study documents here:\n\n"
            "- PDF files (.pdf)\n"
            "- Word documents (.docx)\n"
            "- Plain text files (.txt)\n"
            "- Markdown files (.md)\n\n"
            "Subfolders are supported — the agent will scan everything recursively.\n\n"
            "To change this folder, edit `study_folder` in `config.yaml`.\n"
            "To switch subjects, either:\n"
            "  - Change the folder contents and run `python main.py --reindex`\n"
            "  - Point to a different folder: `python main.py --folder /path/to/other/folder`\n"
        )
    print(f"  ✓ Materials folder ready: {folder}")
    print("    Add your study documents there before running the agent.")


def print_final_instructions():
    print()
    print("=" * 52)
    print("  ✅  Setup complete!")
    print("=" * 52)
    print()
    print("  Next steps:")
    print()
    print("  1. Make sure Ollama is running:")
    print("       ollama serve")
    print()
    print("  2. Add your study documents to:")
    print("       ./materials/")
    print()
    print("  3. Start the agent:")
    print("       python main.py")
    print()
    print("  Optional — switch study subject:")
    print("       python main.py --folder ./materials/biology")
    print()
    print("  Optional — use a different model:")
    print("       python main.py --model llama3.2:3b")
    print()


if __name__ == "__main__":
    print()
    print("  Study Agent — One-time Setup")
    print()

    check_python()
    venv_python = ensure_venv()
    install_dependencies(venv_python)
    check_ollama()
    check_ollama_running()
    create_materials_folder()
    print_final_instructions()
