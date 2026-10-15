FROM python:3.13-alpine
WORKDIR /app
COPY server.py catalog-default.json /app/
COPY dashboard /app/dashboard
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8080), timeout=3).close()" || exit 1
CMD ["python", "server.py"]
