FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt /app/
RUN pip install -r requirements.txt && useradd --create-home --uid 10001 lab
COPY --chown=lab:lab . /app
USER lab
EXPOSE 8501
CMD ["sh", "start.sh"]
