# Online News Scrapers – FastAPI Gateway

A minimal **FastAPI** service that spawns individual news‑site scrapers on demand and returns a clean JSON feed.
Out‑of‑the‑box it supports:

* Abp Live (`abp_live`)
* Aljazeera (`aljazeera`)
* BBC (`bbc`)
* Business Standard (`business_standard`)
* CNN (`cnn`)
* Daily Pioneer (`daily_pioneer`)
* Deccan Herald (`deccan_herald`)
* Economic Times (`economic_times`)
* Firstpost (`firstpost`)
* Hindustan Times (`hindustan_times`)
* India.com (`india_dotcom`)
* India Today (`india_today`)
* Indian Express (`indian_express`)
* Millennium Post (`millennium_post`)
* NDTV (`ndtv`)
* News18 (`news18`)
* Republic World (`republic_world`)
* Reuters (`reuters`)
* South Asia Monitor (`south_asia_monitor`)
* Statesman (`statesman`)
* Telegraph India (`telegraph_india`)
* The Diplomat (`the_diplomat`)
* The Guardian (`the_guardian`)
* The Hindu (`the_hindu`)
* The Quint (`the_quint`)
* The Tribune (`the_tribune`)
* Times of India (`times_of_india`)
* Washington Post (`washington_post`)
* Wion (`wion`)

> **Note**: Each request targets **one** outlet.  Aggregating across outlets should be handled by the upstream orchestrator.

---

## 1. Clone & install

```bash
# 1. Grab the repo
$ git clone https://github.com/<your-org>/shottify-scraping.git
$ cd shottify-scraping

# 2. Create & activate a virtualenv (recommended)
$ python -m venv .venv
$ source .venv/bin/activate      # PowerShell: .venv\Scripts\Activate.ps1

# 3. Install Python deps
$ pip install --upgrade pip
$ pip install -r requirements.txt
```

Python ≥ 3.10 is required.

---

## 2. Running the server

### a) Via **uvicorn** (hot‑reload‑friendly)

```bash
$ uvicorn server:app --reload --port 8000            # 0.0.0.0 by default
```

### b) Directly with **python**

```bash
$ python server.py                                   # defaults to :8000
```

FastAPI’s interactive docs are available at [**http://localhost:8000/**](http://localhost:8000/) once the server is up.

---

## 3. Endpoint

| Method | Path      | Description                           |
| ------ | --------- | ------------------------------------- |
| `POST` | `/scrape` | Trigger a scrape for a single outlet. |

### 3.1 Request body (JSON)

| Field       | Type          | Default        | Notes                                                                                                                                                                         |
| ----------- | ------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `outlet`    | `string`      | **required**   | One of `abp_live`, `aljazeera`, `bbc`, `business_standard`, `cnn`, `daily_pioneer`, `deccan_herald`, `economic_times`, `firstpost`, `hindustan_times`, `india_dotcom`, `india_today`, `indian_express`, `millennium_post`, `ndtv`, `news18`, `republic_world`, `reuters`, `south_asia_monitor`, `statesman`, `telegraph_india`, `the_guardian`, `the_hindu`, `the_quint`, `the_tribune`, `times_of_india`, `washington_post`, `wion`. |
| `keyword`   | `string`      | `"bangladesh"` | Search / topic keyword.                                                                                                                                                       |
| `limit`     | `int (1‒500)` | `30`           | Max articles to return.                                                                                                                                                       |
| `page_size` | `int (1‒100)` | `50`           | Batch size per remote request.                                                                                                                                                |

### 3.2 Successful response (`200 OK`)

A JSON array of Article objects:

```jsonc
[
  {
    "title": "…",
    "published_at": "2025-07-08T16:37:33.548Z",   // ISO‑8601 string
    "url": "https://…",
    "content": "long body …",
    "summary": "…",
    "author": "Alice" | ["Alice", "Bob"],         // string or array
    "media": [ { "url": "…", "caption": "…", "type": "image" } ],
    "outlet": "Republic World",
    "tags": [ "politics", "asia" ],
    "section": "business" | ["world", "asia"]
  },
  …
]
```

---

## 4. Example requests

### 4.1 cURL

```bash
curl -X POST http://localhost:8000/scrape \
     -H "Content-Type: application/json" \
     -d '{
           "outlet": "republic_world",
           "keyword": "bangladesh",
           "limit": 10,
           "page_size": 20
         }'
```

### 4.2 HTTPie

```bash
http POST :8000/scrape outlet=republic_world keyword=bangladesh limit:=10 page_size:=20
```

---

## 5. Sample response

```jsonc
[{
  "title": "Trump's Tariff On Bangladesh, Thailand: India’s Apparel Exports To Gain?",
  "published_at": "2025-07-08T16:37:33.548Z",
  "url": "https://www.republicworld.com/business/trump-announces-tariff-hike-on-bangladesh-thailand-what-does-it-signify-for-india-s-apparel-exports-to-us",
  "content": "India's export verticals ranging from footwear to apparel …",
  "summary": "Trump Announces Tariff Hike On Bangladesh & Thailand …",
  "author": null,
  "media": [{
      "url": "https://img.republicworld.com/all_images/global-leaders-puzzled-…",
      "caption": "Donald Trump I Tariff Imposition",
      "type": "image"
  }],
  "outlet": "Republic World",
  "tags": [],
  "section": "business"
},
  … truncated for brevity …
]
```

---

## 6. Troubleshooting & tips

| Issue                                               | Suggestion                                                                                          |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| \*Validation error for **`author`** / \**`section`* | The model accepts both strings and lists. Ensure the scraper returns one of those types.            |
| *Address already in use*                            | Another process is bound to port 8000. Choose a different port: `uvicorn server:app --port 8080`.   |
| *SSL / proxy errors while scraping*                 | Check outbound network access or corporate proxy settings; each scraper uses `requests` underneath. |

---

## 7. Contributing

Pull requests are welcome!  Please run `ruff` and `black` before submitting and include unit tests where appropriate.

---

© 2025 Nazmul Islam Ananto – MIT License

