# UNPAM Smart Campus Navigation (Flask + Three.js + Vanilla Framework)

    pip install -r requirements.txt
    python app.py                 # open http://127.0.0.1:5000
    python app.py --selftest      # algorithm check without the server
    python -m unittest -v         # unit tests

Features: Dijkstra routing from scratch, accessible (no stairs/escalator) routes, 3D campus with
the room layout of the PDF plans, light / dark theme (button in the header, remembered in the browser).

Files
- dijkstra.py       Dijkstra from scratch (heapq); accessibility = skip blocked edge types
- extract_plans.py  PDF -> plans.json (room boxes + labels). Only needed if the PDF changes (pip install pymupdf)
- plans.json        Every room box of the 20 PDF pages (position / size in PDF points)
- campus_data.py    plans.json -> weighted graph. Scale constants S_MAIN / S_WING (metres per PDF point)
- app.py            Flask API: /api/init_data, /api/find_path, /api/benchmark
- templates/, static/   Vanilla Framework 4.59.0 UI, Font Awesome icons, Three.js viewer (CDN)

Internet access is needed in the browser for the Vanilla, Font Awesome and Three.js CDNs.
