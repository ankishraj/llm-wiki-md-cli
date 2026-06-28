# Project Wiki — developer tasks.
#
#   make wiki         build the reproducible wiki.pyz zipapp + checksum
#   make install      add bin/ to your shell PATH (so `wiki` works anywhere)
#   make test         run the test suite
#   make lint         run wiki lint against the repo
#   make verify       run wiki verify-diff
#   make install-hook install the git pre-commit hook
#   make clean        remove build artefacts

PYTHON ?= python3
SRC := tools/wiki-src

.PHONY: wiki install test lint verify install-hook clean

wiki:
	$(PYTHON) tools/build_pyz.py

install:
	$(PYTHON) tools/install.py

test:
	PYTHONPATH=$(SRC) $(PYTHON) -m pytest $(SRC)/tests -q

lint:
	$(PYTHON) tools/wiki.pyz lint

verify:
	$(PYTHON) tools/wiki.pyz verify-diff

install-hook:
	mkdir -p .git/hooks
	ln -sf ../../tools/hooks/pre-commit .git/hooks/pre-commit
	@echo "installed pre-commit hook"

clean:
	rm -f tools/wiki.pyz tools/wiki.pyz.sha256
	find $(SRC) -name '__pycache__' -type d -prune -exec rm -rf {} +
