FROM python:3.11-alpine
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
WORKDIR /app
COPY . /app
RUN chown -R appuser:appgroup /app
ENV PYTHONPATH=/app
RUN pip install --no-cache-dir -r requirements.txt
USER appuser
EXPOSE 5000
ENTRYPOINT ["python", "app.py"]