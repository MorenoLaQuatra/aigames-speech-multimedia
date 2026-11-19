# Sourced by start.sh and add-user.sh: activates the conda env `ai-games`.
CONDA_SH="${HOME}/miniconda3/etc/profile.d/conda.sh"
if [ ! -f "$CONDA_SH" ]; then
    CONDA_SH="/mnt/disk1/mlaquatra/miniconda3/etc/profile.d/conda.sh"
fi
if [ ! -f "$CONDA_SH" ]; then
    echo "conda not found (looked for ~/miniconda3 and /mnt/disk1/mlaquatra/miniconda3)" >&2
    exit 1
fi
# shellcheck disable=SC1090
source "$CONDA_SH"
conda activate ai-games
