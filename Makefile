.PHONY: setup test test-single rescore diff clean help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup: ## Create venv and install dependencies
	python3 -m venv venv
	./venv/bin/pip install -r requirements.txt
	@echo ""
	@echo "✅  Setup complete."
	@echo "    Copy .env.example → .env and add your ANTHROPIC_API_KEY."

test: ## Run the full evaluation suite
	./venv/bin/python run_eval.py

test-single: ## Run a single case (usage: make test-single CASE=voyager_heliopause)
	./venv/bin/python run_eval.py --case $(CASE)

repeats: ## Run with flakiness detection (usage: make repeats N=3)
	./venv/bin/python run_eval.py --repeats $(N)

rescore: ## Re-score cached traces (usage: make rescore RUN_ID=7607ca31)
	./venv/bin/python run_eval.py --rescore --run-id $(RUN_ID)

rescore-fixture: ## Re-score the committed fixture traces
	./venv/bin/python run_eval.py --rescore --run-id 7607ca31 --suite test_suite/cases.yaml

diff: ## Run suite and diff against a previous run (usage: make diff RUN_ID=7607ca31)
	./venv/bin/python run_eval.py --diff $(RUN_ID)

unit-test: ## Run unit tests (no API calls)
	./venv/bin/python -m pytest tests/ -v

clean: ## Remove generated reports and dev traces
	rm -rf reports/*.json reports/*_viewer.html traces/
