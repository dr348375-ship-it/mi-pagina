FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements-cloud.txt ./
RUN pip install --no-cache-dir -r requirements-cloud.txt
RUN useradd --create-home appuser
COPY --chown=appuser:appuser app.py storage.py ./
COPY --chown=appuser:appuser templates/ templates/
COPY --chown=appuser:appuser Imagenes/ Imagenes/
COPY --chown=appuser:appuser marca/ marca/
COPY --chown=appuser:appuser index.html styles.css script.js admin.css datos-iniciales.json ./
RUN mkdir instance && chown appuser:appuser instance
USER appuser
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 60 'app:create_app()'"]
