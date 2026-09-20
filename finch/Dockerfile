FROM python:3.10-slim

WORKDIR /app

# Install only dependencies required by the evaluator.
# This layer remains cached unless evaluator dependencies change.
COPY finch/requirements-evaluator.txt ./
RUN pip install --no-cache-dir -r requirements-evaluator.txt

# Copy package metadata separately.
COPY pyproject.toml README.md ./

# Copy evaluator/application source.
COPY kriterion ./kriterion
COPY cedar ./cedar
COPY fixtures ./fixtures

# Install Kriterion itself without reinstalling dependencies.
RUN pip install --no-cache-dir --no-deps .

ENTRYPOINT ["python", "-m", "kriterion"]