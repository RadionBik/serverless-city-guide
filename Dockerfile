# Pre-bake job image — vLLM base + this package.
# The endpoint needs no custom image: it runs the stock vllm/vllm-openai image
# with the model as an argument (see scripts/deploy_endpoint.sh).

FROM vllm/vllm-openai:latest

WORKDIR /app

COPY pyproject.toml README.md ./
COPY city_guide ./city_guide

RUN pip install --no-cache-dir httpx pydantic python-dotenv && \
    pip install --no-cache-dir --no-deps .

# vllm-openai's entrypoint starts the API server — the job runs the batch script instead
ENTRYPOINT ["python3", "-m", "city_guide.prebake"]
