FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db
COPY worker.py /opt/skillscope/worker.py
USER 65534:65534
ENTRYPOINT ["python", "-I", "-B", "/opt/skillscope/worker.py"]
