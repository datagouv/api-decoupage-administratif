import gzip
import json
from pathlib import Path

import requests
from slugify import slugify

cache_file = "results-prod.json.gz"
url_swagger = "https://geo.api.gouv.fr/definition.yml"

if not Path(cache_file).exists():
    cache = {}
    with open("urls_to_test.txt") as infile:
        content = [line.rstrip() for line in infile]
        for line in content:
            response = requests.get(line)
            if response.status_code == 200:
                print(line)
                response_content = response.json()
                response_content = json.dumps(
                    response_content, sort_keys=True, ensure_ascii=False
                )
                cache[slugify(line)] = {"url": line, "response": response_content}
            else:
                print(f"no_200 {line}")
    with gzip.open(cache_file, "wt", encoding="UTF-8") as f:
        json.dump(cache, f, ensure_ascii=False)
else:
    with gzip.open(cache_file, "rt", encoding="UTF-8") as zipfile:
        cache = json.load(zipfile)


errors: dict[str, list[str]] = {
    "Response similar": [],
    "Issue for response content": [],
    "Issue for http call (e.g not 200)": [],
    "Search result could differs due to different indexing": [],
}

for k, v in cache.items():
    local_url = v.get("url").replace("https://geo.api.gouv.fr", "http://localhost:8000")
    print(k, local_url)

    response = requests.get(local_url)
    if response.status_code == 200:
        response_content = response.json()
        response_content = json.dumps(
            response_content, sort_keys=True, ensure_ascii=False
        )
        if response_content == v.get("response"):
            print("Response similar")
            errors["Response similar"].append(local_url)
        else:
            if "nom=" in local_url:
                print("Search result could differs due to different indexing")
                errors["Search result could differs due to different indexing"].append(
                    local_url
                )
            else:
                print("Issue for response content")
                errors["Issue for response content"].append(local_url)
    else:
        print("Issue for http call (e.g not 200)")
        errors["Issue for http call (e.g not 200)"].append(local_url)

for k_error, v_error in errors.items():
    print(k_error, len(v_error), v_error)
