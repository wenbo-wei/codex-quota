export PYTHONDONTWRITEBYTECODE := 1

.PHONY: check
check:
	python3 -c "import ast,pathlib; [ast.parse(p.read_text()) for p in [*pathlib.Path('.').glob('*.py'), *pathlib.Path('tests').glob('*.py')]]"
	node --check extensions/codex-quota@wenbo-wei/extension.js
	python3 -m json.tool extensions/codex-quota@wenbo-wei/metadata.json >/dev/null
	python3 -m unittest discover -s tests -v
