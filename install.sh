#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(realpath "${1:-$PWD}")"
conda_env="carlaAir"

if [[ ! -f "$repo_dir/scripts/run_phase3_skills.py" ]]; then
  echo "Usage: bash $0 /path/to/carla_demo" >&2
  exit 1
fi

# Locate Conda, including installations not initialized in this shell.
conda_exe="${CONDA_EXE:-}"
if [[ ! -x "$conda_exe" ]]; then
  conda_exe="$(command -v conda || true)"
fi
if [[ ! -x "$conda_exe" ]]; then
  for candidate in \
    "$HOME/miniconda3/bin/conda" \
    "$HOME/anaconda3/bin/conda" \
    "$HOME/miniforge3/bin/conda"; do
    if [[ -x "$candidate" ]]; then
      conda_exe="$candidate"
      break
    fi
  done
fi
if [[ ! -x "$conda_exe" ]]; then
  echo "Install Conda first, or set CONDA_EXE to its executable." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y \
  ca-certificates build-essential libgl1 libglib2.0-0t64

eval "$("$conda_exe" shell.bash hook)"

# Preserve an existing environment; require compatible Python.
if conda run -n "$conda_env" python -c 'pass' >/dev/null 2>&1; then
  conda run -n "$conda_env" python -c \
    'import sys; assert sys.version_info[:2] == (3, 10), "carlaAir requires Python 3.10 for this setup"'
else
  conda create -y -n "$conda_env" python=3.10 pip
fi

conda activate "$conda_env"
export PYTHONDONTWRITEBYTECODE=1

# Install compatible mock dependencies without editing requirements.txt.
python -m pip install \
  numpy==1.26.4 \
  opencv-contrib-python==4.11.0.86 \
  msgpack-python==0.5.6 \
  msgpack-rpc-python==0.4.1 \
  tornado==4.5.3 \
  setuptools==84.0.0 \
  wheel==0.48.0 \
  pytest==8.4.2

# AirSim's build imports its runtime dependencies.
python -m pip install --no-build-isolation airsim==1.8.1

python -m pip check
python -c \
  'import airsim, cv2, numpy, msgpackrpc; print("Dependencies OK")'

cd "$repo_dir"
python -m scripts.run_phase3_skills

printf '\nSetup complete. In your working shell, run:\n'
printf '  conda activate carlaAir\n'
printf '  export PYTHONDONTWRITEBYTECODE=1\n'
