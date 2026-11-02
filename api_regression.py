import gzip
import json
from pathlib import Path
from typing import TypedDict, cast

import requests
from deepdiff import DeepDiff
from slugify import slugify

cache_file = "results-prod.json.gz"
url_swagger = "https://geo.api.gouv.fr/definition.yml"


class CacheEntry(TypedDict):
    url: str
    response: str
    elapsed: str
    http_code: int


def flatten_comprehension(matrix):
    return [item for row in matrix for item in row]


def compare_json_deepdiff(json_1, json_2):
    dict_1 = json.loads(json_1)
    dict_2 = json.loads(json_2)
    diff = DeepDiff(dict_1, dict_2, ignore_order=True)
    return not diff


cache: dict[str, CacheEntry]

if not Path(cache_file).exists():
    cache = {}
    with open("urls_to_test.txt") as infile:
        content = [line.rstrip() for line in infile]
        for line in content:
            response = requests.get(line)
            if response.status_code == 200:
                print(line)
                response_content = response.json()
                elapsed = response.elapsed
                response_content_remote = json.dumps(
                    response_content, sort_keys=True, ensure_ascii=False
                )
                cache[slugify(line)] = {
                    "url": line,
                    "response": response_content_remote,
                    "elapsed": str(elapsed),
                    "http_code": response.status_code,
                }
            else:
                print(f"no_200, {response.status_code}, {line}")
    with gzip.open(cache_file, "wt", encoding="UTF-8") as f:
        json.dump(cache, f, ensure_ascii=False)
else:
    with gzip.open(cache_file, "rt", encoding="UTF-8") as zipfile:
        cache = cast(dict[str, CacheEntry], json.load(zipfile))
        # cache = json.load(zipfile)

errors: dict[str, list[dict]] = {
    "Response similar": [],
    "Issue for response content": [],
    "Issue for http call (e.g not 200)": [],
    "Search result could differs due to different indexing": [],
}

for k_cache, v_cache in cache.items():
    prod_url = v_cache["url"]
    local_url = prod_url.replace("https://geo.api.gouv.fr", "http://localhost:8000")
    print(k_cache, local_url)

"""
    response = requests.get(local_url)
    if response.status_code == 200:
        elapsed_local = str(response.elapsed)
        response_content_local = response.json()
        response_content_local = json.dumps(
            response_content_local, sort_keys=True, ensure_ascii=False
        )
        # if response_content == v_cache.get("response"):
        if compare_json_deepdiff(response_content_local, v_cache.get("response")):
            print("Response similar")
            errors["Response similar"].append(
                {
                    "url": local_url,
                    "elapsed": elapsed_local,
                    "http_code": response.status_code,
                    "http_code_prod": v_cache.get("http_code"),
                    "elapsed_prod": v_cache.get("elapsed"),
                    "type": "Response similar",
                }
            )
        else:
            if "nom=" in local_url:
                print("Search result could differs due to different indexing")
                errors["Search result could differs due to different indexing"].append(
                    {
                        "url": local_url,
                        "elapsed": elapsed_local,
                        "http_code": response.status_code,
                        "http_code_prod": v_cache.get("http_code"),
                        "elapsed_prod": v_cache.get("elapsed"),
                        "type": "Search result could differs due to different indexing",
                    }
                )
            elif local_url == "http://localhost:8000/communes/":
                # import ipdb;ipdb.set_trace()
                print(f"Compare key for {local_url}")
                if set(
                    flatten_comprehension(
                        [list(r.keys()) for r in json.loads(response_content_local)]
                    )
                ) == set(
                    flatten_comprehension(
                        [list(r.keys()) for r in json.loads(v_cache.get("response"))]
                    )
                ) and len(json.loads(response_content_local)) == len(
                    json.loads(v_cache.get("response"))
                ):
                    errors["Response similar"].append(
                        {
                            "url": local_url,
                            "elapsed": elapsed_local,
                            "http_code": response.status_code,
                            "http_code_prod": v_cache.get("http_code"),
                            "elapsed_prod": v_cache.get("elapsed"),
                            "type": "Response similar",
                        }
                    )
                else:
                    errors["Issue for response content"].append(
                        {
                            "url": local_url,
                            "elapsed": elapsed_local,
                            "http_code": response.status_code,
                            "http_code_prod": v_cache.get("http_code"),
                            "elapsed_prod": v_cache.get("elapsed"),
                            "type": "Issue for response content",
                        }
                    )
            else:
                print("Issue for response content")
                errors["Issue for response content"].append(
                    {
                        "url": local_url,
                        "elapsed": elapsed_local,
                        "http_code": response.status_code,
                        "http_code_prod": v_cache.get("http_code"),
                        "elapsed_prod": v_cache.get("elapsed"),
                        "type": "Issue for response content",
                    }
                )
    else:
        print("Issue for http call (e.g not 200)")
        errors["Issue for http call (e.g not 200)"].append(
            {
                "url": local_url,
                "elapsed": elapsed_local,
                "http_code": response.status_code,
                "http_code_prod": v_cache.get("http_code"),
                "elapsed_prod": v_cache.get("elapsed"),
                "type": "Issue for http call (e.g not 200)",
            }
        )

for k_error, v_error in errors.items():
    print(k_error, len(v_error), v_error)

errors_api_file_name_no_extension = "errors_api_file"
with gzip.open(
    f"{errors_api_file_name_no_extension}.json.gz", "wt", encoding="UTF-8"
) as f:
    json.dump(errors, f, ensure_ascii=False)

with open(f"{errors_api_file_name_no_extension}.csv", "w", newline="") as csvfile:
    fieldnames = [
        "type",
        "url",
        "http_code",
        "elapsed",
        "http_code_prod",
        "elapsed_prod",
    ]
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    for k_error, v_error in errors.items():
        writer.writerows(v_error)
"""
