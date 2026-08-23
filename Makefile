.PHONY: all fetch parse build validate test clean refresh

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

## Run the Go library test suite
test:
	go vet ./...
	go test ./...

## Full refresh from the live site
refresh: fetch build validate

clean:
	rm -rf data/tests.json data/index.json data/by-department data/by-clinic
