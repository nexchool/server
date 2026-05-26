.PHONY: test test-cov

test:
	pytest tests/ -v

test-cov:
	pytest tests/ --cov --cov-report=term-missing --cov-report=html --cov-fail-under=100
