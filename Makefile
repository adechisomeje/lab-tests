.PHONY: all fetch parse build validate test test-go test-ts test-py clean refresh

all: build validate test

## Fetch sources from mft.nhs.uk (polite: rate-limited, resumable)
fetch:
	python3 scripts/fetch_az.py
	python3 scripts/parse_az_list.py
	python3 scripts/fetch_pdfs.py

## Parse cached sources into intermediate JSON
parse:
	python3 scripts/parse_az_list.py
	python3 scripts/parse_pdfs.py
	python3 scripts/parse_biochem_ranges.py

## Build the published dataset in data/
build: parse
	python3 scripts/build.py

## Check schema conformance and referential integrity
validate:
	python3 scripts/validate.py

## Run every implementation against the shared conformance suite
test: test-go test-ts test-py

test-go:
	go vet ./...
	go test ./...

test-ts:
	npm --prefix packages/typescript test

test-py:
	cd packages/python && python3 -m pytest tests -q

## Full refresh from the live site
refresh: fetch build validate

clean:
	rm -rf data/tests.json data/index.json data/by-department data/by-clinic
