#!/bin/sh
set -eu
if [ "${SERVICE_ROLE:-web}" = "worker" ]; then
  exec python -m opinionsim.worker
fi
exec streamlit run app.py --server.address=0.0.0.0 --server.port="${PORT:-8501}" --server.headless=true --browser.gatherUsageStats=false --server.maxUploadSize=20
