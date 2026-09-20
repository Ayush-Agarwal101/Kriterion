.PHONY: demo benchmark test metrics

demo:
	python -m kriterion demo

benchmark:
	python -m kriterion benchmark
	python -m kriterion metrics aggregate --runs artifacts/runs --output artifacts/metrics/summary.json

metrics:
	python -m kriterion metrics aggregate --runs artifacts/runs --output artifacts/metrics/summary.json

test:
	python -m unittest discover -s tests
