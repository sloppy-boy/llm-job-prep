FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY knowledge_base ./knowledge_base
COPY scripts ./scripts
COPY eval ./eval
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh
EXPOSE 8000
CMD ["./entrypoint.sh"]
