# Bill Extractor

## Commands
- Run tests: `/Users/pasili001/miniforge3/envs/receipt-ai/bin/python -m pytest`
- Start server: `bill-extractor` (port 8080) or `uvicorn bill_extractor.app:app --port 8080`

## Frontend (`bill_extractor/templates/index.html`)
- Vue 3 Composition API, CDN only, no build step — single ~1400-line file; always read with offset/limit
- **No PrimeVue** — was tried and abandoned; UMD component registration fails silently in Brave browser
- `histHandle` MUST be `shallowRef(null)` — `ref()` wraps FSA FileSystemFileHandle in a Proxy, causing IDB structured-clone errors
- All IDB/file writes must strip Vue reactivity: `JSON.parse(JSON.stringify(allRecords.value))` before writing

## Architecture notes
- Server is fully stateless — no DB, no file storage, no session
- History lives entirely in the browser (IndexedDB + optional FSA file)
- See `PLAN.md` for phase status and open decisions
